"""
Get production and status information from the Huawei Inverter using Modbus over TCP
"""
import asyncio
from collections import namedtuple
from contextlib import asynccontextmanager
from hashlib import sha256
import hmac
import logging
import secrets
import sys
import typing as t

import backoff
from pymodbus.constants import Endian
from pymodbus.exceptions import ConnectionException as ModbusConnectionException
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder
from pymodbus.pdu import ExceptionResponse, ModbusExceptions, ModbusRequest
from pymodbus.utilities import checkCRC, computeCRC

import huawei_solar.register_names as rn

from . import register_values as rv
from .exceptions import (
    ConnectionException,
    ConnectionInterruptedException,
    HuaweiSolarException,
    PermissionDenied,
    ReadException,
    SlaveBusyException,
    SlaveFailureException,
    WriteException,
)
from .modbus import (
    AsyncHuaweiSolarModbusSerialClient,
    AsyncHuaweiSolarModbusTcpClient,
    CompleteUploadModbusRequest,
    CompleteUploadModbusResponse,
    PrivateHuaweiModbusRequest,
    StartUploadModbusRequest,
    StartUploadModbusResponse,
    UploadModbusRequest,
    UploadModbusResponse,
)
from .registers import REGISTERS, RegisterDefinition

LOGGER = logging.getLogger(__name__)

Result = namedtuple("Result", "value unit")


DEFAULT_TCP_PORT = 502
DEFAULT_BAUDRATE = 9600

DEFAULT_SLAVE = 0
DEFAULT_TIMEOUT = 10  # especially the SDongle can react quite slowly
DEFAULT_WAIT = 1
DEFAULT_COOLDOWN_TIME = 0.05

HEARTBEAT_REGISTER = 49999

FILE_UPLOAD_MAX_RETRIES = 6
FILE_UPLOAD_RETRY_TIMEOUT = 10

PERMISSION_DENIED_EXCEPTION_CODE = 0x80


def _compute_digest(password, seed):
    hashed_password = sha256(password).digest()

    return hmac.digest(key=hashed_password, msg=seed, digest=sha256)


class AsyncHuaweiSolar:
    """Async interface to the Huawei solar inverter"""

    def __init__(
        self,
        client: t.Union[AsyncHuaweiSolarModbusSerialClient, AsyncHuaweiSolarModbusTcpClient],
        slave: int = DEFAULT_SLAVE,
        timeout: int = DEFAULT_TIMEOUT,
        cooldown_time: float = DEFAULT_COOLDOWN_TIME,
    ):
        """DO NOT USE THIS CONSTRUCTOR DIRECTLY. Use AsyncHuaweiSolar.create() instead"""
        self._client = client
        self._timeout = timeout
        self._cooldown_time = cooldown_time
        self.slave = slave

        # use this lock to prevent concurrent requests, as the
        # Huawei inverters can't cope with those
        self.__communication_lock = asyncio.Lock()

        self.__cooled_down = asyncio.Event()
        self.__cooled_down.set()

        # These values are set by the `initialize()` method
        self.time_zone = None
        self.battery_type = None

    async def _initialize(self):
        # get some registers which are needed to correctly decode all values

        self.time_zone = (await self.get(rn.TIME_ZONE)).value
        await self._determine_battery_type()

    async def _determine_battery_type(self, slave_id: t.Optional[int] = None):
        # Skip if the battery type was already determined via another slave
        if self.battery_type is not None and self.battery_type != rv.StorageProductModel.NONE:
            return

        try:
            self.battery_type = (await self.get(rn.STORAGE_UNIT_1_PRODUCT_MODEL, slave_id or self.slave)).value

            if self.battery_type == rv.StorageProductModel.NONE:
                self.battery_type = (await self.get(rn.STORAGE_UNIT_2_PRODUCT_MODEL, slave_id or self.slave)).value

        except ReadException as rerr:
            if "IllegalAddress" in str(rerr):
                LOGGER.info(
                    "Received IllegalAddress-error while determining battery support. Setting it to None.",
                    exc_info=rerr,
                )
                # inverter doesn't seem to support a battery
                self.battery_type = None
            else:
                LOGGER.exception("Got error %s while trying to determine battery.", rerr)
                raise rerr

    @asynccontextmanager
    async def _communication_lock(self):
        async with self.__communication_lock:
            if not self._client.connected_event.is_set():
                LOGGER.info("Waiting for connection ...")
            await self._client.connected_event.wait()

            await self.__cooled_down.wait()
            self.__cooled_down.clear()

            try:
                yield
            finally:

                async def _perform_cooldown():
                    await asyncio.sleep(self._cooldown_time)
                    self.__cooled_down.set()

                asyncio.create_task(_perform_cooldown())

    @classmethod
    async def create(
        cls,
        host,
        port: int = DEFAULT_TCP_PORT,
        slave: int = DEFAULT_SLAVE,
        timeout: int = DEFAULT_TIMEOUT,
        cooldown_time: int = DEFAULT_COOLDOWN_TIME,
    ):  # pylint: disable=too-many-arguments
        """Creates an AsyncHuaweiSolar instance."""

        client = None
        try:
            client = AsyncHuaweiSolarModbusTcpClient(host, port, timeout)
            await client.connect()

            huawei_solar = cls(client, slave, timeout, cooldown_time)

            await huawei_solar._initialize()

            return huawei_solar
        except Exception as err:
            # if an error occurs, we need to make sure that the Modbus-client is stopped,
            # otherwise it can stay active and cause even more problems ...
            LOGGER.exception("Aborting client creation due to error.")

            if client is not None:
                await client.close()
            raise ConnectionException from err

    @classmethod
    async def create_rtu(
        cls,
        port,
        baudrate: int = DEFAULT_BAUDRATE,
        slave: int = DEFAULT_SLAVE,
        timeout: int = DEFAULT_TIMEOUT,
        cooldown_time: int = DEFAULT_COOLDOWN_TIME,
        **serial_kwargs,
    ):
        """Create a serial client"""
        client = None
        try:
            client = AsyncHuaweiSolarModbusSerialClient(port, baudrate, timeout, **serial_kwargs)
            await client.connect()

            # wait a little bit to prevent a timeout on the first request
            await asyncio.sleep(1)

            huawei_solar = cls(client, slave, timeout, cooldown_time)
            await huawei_solar._initialize()

            return huawei_solar
        except Exception as err:
            # if an error occurs, we need to make sure that the Modbus-client is stopped,
            # otherwise it can stay active and cause even more problems ...
            LOGGER.exception("Aborting client creation due to error.")
            raise ConnectionException from err

    async def stop(self):
        """Stop the modbus client."""
        await self._client.close()

    async def _decode_response(self, reg: RegisterDefinition, decoder: BinaryPayloadDecoder):
        """Decodes a modbus register and puts it into a Result object."""
        result = reg.decode(decoder, self)

        if not hasattr(reg, "unit") or callable(reg.unit) or isinstance(reg.unit, dict):
            return Result(result, None)
        return Result(result, reg.unit)

    async def get(self, name, slave=None):
        """get named register from device"""
        return (await self.get_multiple([name], slave))[0]

    async def get_multiple(self, names: list[str], slave=None):
        """Read multiple registers at the same time.

        This is only possible if the registers are consecutively available in the
        inverters' memory.
        """

        if len(names) == 0:
            raise ValueError("Expected at least one register name")

        registers = list(map(REGISTERS.get, names))

        if None in registers:
            raise ValueError("Did not recognize all register names")

        for register, register_name in zip(registers, names):
            if not register.readable:
                raise ValueError(f"Trying to read unreadable register {register_name}")

        for idx in range(1, len(names)):
            if registers[idx - 1].register + registers[idx - 1].length > registers[idx].register:
                raise ValueError(
                    f"Requested registers must be in monotonically increasing order, "
                    f"but {registers[idx-1].register} + {registers[idx-1].length} > {registers[idx].register}!"
                )

            register_distance = registers[idx - 1].register + registers[idx - 1].length - registers[idx].register

            if register_distance > 64:
                raise ValueError("Gap between requested registers is too large. Split it in two requests")

        total_length = registers[-1].register + registers[-1].length - registers[0].register

        response = await self._read_registers(registers[0].register, total_length, slave)

        decoder = BinaryPayloadDecoder.fromRegisters(response.registers, byteorder=Endian.Big, wordorder=Endian.Big)

        result = [await self._decode_response(registers[0], decoder)]
        for idx in range(1, len(registers)):
            skip_registers = registers[idx].register - (registers[idx - 1].register + registers[idx - 1].length)
            decoder.skip_bytes(skip_registers * 2)  # registers are 16-bit, so we need to multiply by two
            result.append(await self._decode_response(registers[idx], decoder))

        return result

    async def _read_registers(self, register: int, length: int, slave: t.Optional[int]):
        """
        Async read register from device.

        The device needs a bit of time between the connection and the first request
        and between requests if there is a long time between them, else it will fail.

        This is solved by sleeping between the first connection and a request,
        and up to 5 retries between following requests.

        It seems to only support connections from one device at the same time.
        """

        def backoff_giveup(details):
            raise ReadException(f"Failed to read register {register} after {details['tries']} tries")

        @backoff.on_exception(
            backoff.expo,
            (asyncio.TimeoutError, SlaveBusyException, SlaveFailureException, ConnectionInterruptedException),
            max_tries=6,
            jitter=None,
            on_backoff=lambda details: LOGGER.debug(
                "Received %s: backing off reading for %0.1f seconds after %d tries",
                sys.exc_info()[0],
                details["wait"],
                details["tries"],
            ),
            on_giveup=backoff_giveup,
        )
        async def _do_read():
            if not self._client.connected:
                message = "Modbus client is not connected to the inverter."
                LOGGER.exception(message)
                raise ConnectionInterruptedException(message)
            try:
                response = await self._client.read_holding_registers(
                    register,
                    length,
                    slave=slave or self.slave,
                )

                # trigger a backoff if we get a SlaveBusy-exception
                if isinstance(response, ExceptionResponse):
                    if response.exception_code == ModbusExceptions.SlaveBusy:
                        LOGGER.debug(
                            "Got a SlaveBusy Modbus Exception while reading %d (length %d) from slave %d",
                            register,
                            length,
                            slave or self.slave,
                        )
                        raise SlaveBusyException()

                    if response.exception_code == ModbusExceptions.SlaveFailure:
                        LOGGER.debug(
                            "Got a SlaveFailure Modbus Exception while reading %d (length %d) from slave %d",
                            register,
                            length,
                            slave or self.slave,
                        )
                        raise SlaveFailureException()

                    # Not a SlaveBusy or SlaveFailure exception
                    raise ReadException(
                        f"Got error while reading from register {register} with length {length}: {response}",
                        modbus_exception_code=response.exception_code,
                    )

                if len(response.registers) != length:
                    raise SlaveBusyException(
                        f"Mismatch between number of requested registers ({length}) "
                        f"and number of received registers ({len(response.registers)})"
                    )

                return response

            except ModbusConnectionException as err:
                message = "Could not read register value, has another device interrupted the connection?"
                LOGGER.error(message)
                raise ConnectionInterruptedException(message) from err

        async with self._communication_lock():
            LOGGER.debug("Reading register %d with length %d from slave %s", register, length, slave or self.slave)
            return await _do_read()

    async def get_file(self, file_type, customized_data=None, slave: t.Optional[int] = None) -> bytes:
        """Reads a 'file' as defined by the 'Uploading Files'
        process described in 6.3.7.1 of the
        Solar Inverter Modbus Interface Definitions"""

        def backoff_giveup(details):
            raise ReadException(f"Failed to read file {file_type} after {details['tries']} tries")

        @backoff.on_exception(
            backoff.constant,
            (asyncio.TimeoutError, SlaveBusyException, SlaveFailureException),
            interval=FILE_UPLOAD_RETRY_TIMEOUT,
            max_tries=FILE_UPLOAD_MAX_RETRIES,
            jitter=None,
            on_backoff=lambda details: LOGGER.debug(
                "Received %s: backing off file upload for %0.1f seconds after %d tries",
                sys.exc_info()[0],
                details["wait"],
                details["tries"],
            ),
            on_giveup=backoff_giveup,
        )
        async def _perform_request(request: ModbusRequest, response_type):
            response = await self._client.execute(request)

            if isinstance(response, ExceptionResponse):
                if response.exception_code == PERMISSION_DENIED_EXCEPTION_CODE:
                    raise PermissionDenied("Permission denied")
                if response.exception_code == ModbusExceptions.SlaveBusy:
                    raise SlaveBusyException()
                if response.exception_code == ModbusExceptions.SlaveFailure:
                    raise SlaveFailureException()
                raise ReadException(
                    f"Exception occured while trying to read file {hex(file_type)}: {hex(response.exception_code)}",
                    modbus_exception_code=response.exception_code,
                )

            return response_type(response.content)

        async def _do_read_file():
            # Start the upload
            start_upload_response = await _perform_request(
                StartUploadModbusRequest(file_type, customized_data, slave=slave or self.slave),
                StartUploadModbusResponse,
            )

            data_frame_length = start_upload_response.data_frame_length
            file_length = start_upload_response.file_length

            # Request the data in 'frames'

            file_data = b""
            next_frame_no = 0

            while (next_frame_no * data_frame_length) < file_length:
                data_upload_response = await _perform_request(
                    UploadModbusRequest(file_type, next_frame_no, slave=slave or self.slave),
                    UploadModbusResponse,
                )

                file_data += data_upload_response.frame_data
                next_frame_no += 1

            # Complete the upload and check the CRC
            complete_upload_response = await _perform_request(
                CompleteUploadModbusRequest(file_type, slave=slave or self.slave),
                CompleteUploadModbusResponse,
            )

            file_crc = complete_upload_response.file_crc
            # swap upper and lower two bytes to match how computeCRC works
            swapped_crc = ((file_crc << 8) & 0xFF00) | ((file_crc >> 8) & 0x00FF)

            if not checkCRC(file_data, swapped_crc):
                raise ReadException(
                    f"Computed CRC {computeCRC(file_data):x} for file {file_type} "
                    f"does not match expected value {swapped_crc}"
                )

            return file_data

        async with self._communication_lock():
            LOGGER.debug("Reading file %#x from slave %d", file_type, slave or self.slave)
            return await _do_read_file()

    async def set(self, name, value, slave=None):
        """set named register from device"""
        try:
            reg = REGISTERS[name]
        except KeyError as err:
            raise ValueError("Invalid Register Name") from err

        if not reg.writeable:
            raise WriteException("Register is not writable")

        builder = BinaryPayloadBuilder(byteorder=Endian.Big, wordorder=Endian.Big)
        reg.encode(value, builder)
        value = builder.to_registers()

        if len(value) != reg.length:
            raise WriteException("Wrong number of registers to write")

        def backoff_giveup(details):
            raise ReadException(f"Failed to write to register after {details['tries']} tries")

        @backoff.on_exception(
            backoff.expo,
            (asyncio.TimeoutError, SlaveBusyException, ConnectionInterruptedException),
            max_tries=3,
            jitter=None,
            on_backoff=lambda details: LOGGER.debug(
                "Received %s: backing off writing for %0.1f seconds after %d tries",
                sys.exc_info()[0],
                details["wait"],
                details["tries"],
            ),
            on_giveup=backoff_giveup,
        )
        async def _do_set():
            return await self._write_registers(reg.register, builder.to_registers(), slave)

        async with self._communication_lock():
            LOGGER.debug("Writing to register %s value %s on slave %s", name, value, slave or self.slave)
            return await _do_set()

    async def _write_registers(self, register: int, value: list[int], slave=None) -> bool:
        """
        Async write register to device.
        """

        if not self._client.connected:
            message = "Modbus client is not connected to the inverter."
            LOGGER.exception(message)
            raise ConnectionInterruptedException(message)
        try:
            LOGGER.debug("Writing to %d: %s on slave %d", register, value, slave or self.slave)

            single_register = len(value) == 1
            if single_register:
                response = await self._client.write_register(
                    register,
                    value[0],
                    slave=slave or self.slave,
                )

            else:
                response = await self._client.write_registers(register, value, slave=slave or self.slave)

            if isinstance(response, ExceptionResponse):
                if response.exception_code == PERMISSION_DENIED_EXCEPTION_CODE:
                    raise PermissionDenied("Permission denied")
                raise WriteException(
                    f"Failed to write value {value} to register {register}: "
                    f"{ModbusExceptions.decode(response.exception_code)}",
                    modbus_exception_code=response.exception_code,
                )

            if single_register:
                return response.address == register and response.value == value[0]
            else:
                return response.address == register and response.count == len(value)
        except ModbusConnectionException as err:
            LOGGER.exception("Failed to connect to device, is the host correct?")
            raise ConnectionInterruptedException(err) from err

    async def login(self, username: str, password: str, slave: t.Optional[int] = None):
        """Login into the inverter."""

        def backoff_giveup(details):
            raise ReadException(f"Failed to login after {details['tries']} tries")

        @backoff.on_exception(
            backoff.expo,
            (asyncio.TimeoutError, SlaveBusyException, SlaveFailureException, SlaveFailureException),
            max_tries=4,
            jitter=None,
            on_backoff=lambda details: LOGGER.debug(
                "Received %s: backing off login for %0.1f seconds after %d tries",
                sys.exc_info()[0],
                details["wait"],
                details["tries"],
            ),
            on_giveup=backoff_giveup,
        )
        async def _do_login():
            # Get challenge
            challenge_request = PrivateHuaweiModbusRequest(36, bytes([1, 0]), slave=slave or self.slave)

            challenge_response = await self._client.execute(challenge_request)

            assert challenge_response.content[0] == 0x11
            inverter_challenge = challenge_response.content[1:17]

            client_challenge = secrets.token_bytes(16)

            encoded_username = username.encode("utf-8")
            hashed_password = _compute_digest(password.encode("utf-8"), inverter_challenge)

            login_bytes = bytes(
                [
                    len(client_challenge) + 1 + len(encoded_username) + 1 + len(hashed_password),
                    *client_challenge,
                    len(encoded_username),
                    *encoded_username,
                    len(hashed_password),
                    *hashed_password,
                ]
            )
            await asyncio.sleep(0.05)
            login_request = PrivateHuaweiModbusRequest(37, login_bytes, slave=slave or self.slave)
            login_response = await self._client.execute(login_request)

            if login_response.content[1] == 0:
                # check if inverter returned the right hash of the password as well
                inverter_mac_response_lengths = login_response.content[2]

                inverter_mac_response = login_response.content[3 : 3 + inverter_mac_response_lengths]

                if not _compute_digest(password.encode("utf-8"), client_challenge) == inverter_mac_response:
                    LOGGER.error(
                        "Inverter response contains an invalid challenge answer. This could indicate a MitM-attack!"
                    )

                return True
            return False

        async with self._communication_lock():
            LOGGER.debug("Logging in")
            return await _do_login()

    async def heartbeat(self, slave_id):
        """Performs the heartbeat command. Only useful when maintaining a session."""
        if not self._client.connected:
            return False
        try:
            # 49999 is the magic register used to keep the connection alive
            response = await self._client.write_register(HEARTBEAT_REGISTER, 0x1, slave=slave_id or self.slave)
            if isinstance(response, ExceptionResponse):
                LOGGER.warning(
                    "Received an error after sending the heartbeat command: %s",
                    ModbusExceptions.decode(response.exception_code),
                )
                return False
            LOGGER.debug("Heartbeat succeeded")
            return True
        except HuaweiSolarException as err:
            LOGGER.exception("Exception during heartbeat: %s", err)
            return False
