"""Low-level Modbus logic."""

import asyncio
import hmac
import logging
import secrets
import struct
import sys
import time
import typing as t
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

import backoff
from pymodbus.exceptions import ConnectionException as ModbusConnectionException
from pymodbus.framer import FramerRTU
from pymodbus.pdu import ExceptionResponse, ModbusPDU
from pymodbus.pdu.register_message import (
    WriteMultipleRegistersResponse,
    WriteSingleRegisterResponse,
)

from .const import DEVICE_INFOS_START_OBJECT_ID, MAX_BATCHED_REGISTERS_COUNT
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
    PrivateHuaweiModbusResponse,
    ReadDeviceIdentifierRequest,
    ReadDeviceIdentifierResponse,
    StartUploadModbusRequest,
    StartUploadModbusResponse,
    UploadModbusRequest,
    UploadModbusResponse,
)
from .registers import REGISTERS, RegisterDefinition

LOGGER = logging.getLogger(__name__)


class Result(t.NamedTuple):
    """Modbus register value."""

    value: t.Any
    unit: str | None


DEFAULT_TCP_PORT = 502
DEFAULT_BAUDRATE = 9600

DEFAULT_SLAVE_ID = 0
DEFAULT_TIMEOUT = 10  # especially the SDongle can react quite slowly
DEFAULT_WAIT = 1
DEFAULT_COOLDOWN_TIME = 0.05
WAIT_FOR_CONNECTION_TIMEOUT = 5

HEARTBEAT_REGISTER = 49999

FILE_UPLOAD_MAX_RETRIES = 6
FILE_UPLOAD_RETRY_TIMEOUT = 10

PERMISSION_DENIED_EXCEPTION_CODE = 0x80

LOGIN_CHALLENGE_SUBCOMMAND = 0x11


def _compute_digest(password, seed):
    hashed_password = sha256(password).digest()

    return hmac.digest(key=hashed_password, msg=seed, digest=sha256)


@dataclass(frozen=True)
class DeviceInfo:
    """Device information."""

    model: str | None
    software_version: str | None
    interface_protocol_version: str | None
    esn: str | None
    device_id: int | None
    feature_version: str | None
    unknown_field: str | None
    product_type: str | None


@dataclass(frozen=True)
class DeviceIdentifier:
    """Device identifier information."""

    vendor: str
    product_code: str
    main_revision_version: str
    other_data: dict[int, bytes]


class AsyncHuaweiSolar:
    """Async interface to the Huawei solar inverter."""

    _reconnect_task: asyncio.Task | None = None
    __last_call_finished_at: float | None = None

    def __init__(
        self,
        client: AsyncHuaweiSolarModbusSerialClient | AsyncHuaweiSolarModbusTcpClient,
        slave_id: int = DEFAULT_SLAVE_ID,
        timeout: int = DEFAULT_TIMEOUT,
        cooldown_time: float = DEFAULT_COOLDOWN_TIME,
    ):
        """DO NOT USE THIS CONSTRUCTOR DIRECTLY. Use AsyncHuaweiSolar.create() instead."""
        self._client = client
        self._timeout = timeout
        self._cooldown_time = cooldown_time
        self.slave_id = slave_id

        # use this lock to prevent concurrent requests, as the
        # Huawei inverters can't cope with those
        self.__communication_lock = asyncio.Lock()

    @asynccontextmanager
    async def _communication_lock(self):
        async with self.__communication_lock:
            if not self._client.connected_event.is_set():
                LOGGER.info("Waiting for connection")

            try:
                await asyncio.wait_for(
                    self._client.connected_event.wait(),
                    WAIT_FOR_CONNECTION_TIMEOUT,
                )
            except TimeoutError:
                LOGGER.exception(
                    "Timeout while waiting for connection. Reconnecting",
                )
                self._reconnect_task = asyncio.create_task(self._reconnect())
                raise

            if self.__last_call_finished_at:
                cooldown_time_needed = (self.__last_call_finished_at + self._cooldown_time) - time.time()
                if cooldown_time_needed > 0:
                    LOGGER.debug(
                        "Sleeping for %f seconds before making next call",
                        cooldown_time_needed,
                    )
                    await asyncio.sleep(cooldown_time_needed)

            try:
                yield
            finally:
                self.__last_call_finished_at = time.time()

    @classmethod
    async def create(  # noqa: PLR0913
        cls,
        host,
        port: int = DEFAULT_TCP_PORT,
        slave: int = DEFAULT_SLAVE_ID,
        timeout: int = DEFAULT_TIMEOUT,  # noqa: ASYNC109
        cooldown_time: float = DEFAULT_COOLDOWN_TIME,
    ):
        """Create an AsyncHuaweiSolar instance."""
        client = None
        try:
            client = AsyncHuaweiSolarModbusTcpClient(host, port, timeout)
            await client.connect()

            huawei_solar = cls(client, slave, timeout, cooldown_time)
        except Exception as err:
            # if an error occurs, we need to make sure that the Modbus-client is stopped,
            # otherwise it can stay active and cause even more problems ...
            LOGGER.exception("Aborting client creation due to error")

            if client:
                client.close()
            raise ConnectionException from err
        else:
            return huawei_solar

    @classmethod
    async def create_rtu(  # noqa: PLR0913
        cls,
        port,
        baudrate: int = DEFAULT_BAUDRATE,
        slave: int = DEFAULT_SLAVE_ID,
        timeout: int = DEFAULT_TIMEOUT,  # noqa: ASYNC109
        cooldown_time: float = DEFAULT_COOLDOWN_TIME,
        **serial_kwargs,
    ):
        """Create a serial client."""
        client = None
        try:
            client = AsyncHuaweiSolarModbusSerialClient(
                port,
                baudrate,
                timeout,
                **serial_kwargs,
            )
            await client.connect()

            # wait a little bit to prevent a timeout on the first request
            await asyncio.sleep(1)

            huawei_solar = cls(client, slave, timeout, cooldown_time)
        except Exception as err:
            # if an error occurs, we need to make sure that the Modbus-client is stopped,
            # otherwise it can stay active and cause even more problems ...
            LOGGER.exception("Aborting client creation due to error")
            raise ConnectionException from err
        else:
            return huawei_solar

    async def stop(self):
        """Stop the modbus client."""
        if self._reconnect_task:
            self._reconnect_task.cancel()

        self._client.close()

    async def _reconnect(self):
        """Reconnect to the inverter."""
        self._client.close()
        await self._client.connect()

    async def _decode_response(
        self,
        reg: RegisterDefinition,
        registers: list[int],
    ):
        """Decode a modbus register and puts it into a Result object."""
        result = reg.decode(registers)

        if not hasattr(reg, "unit") or callable(reg.unit) or isinstance(reg.unit, dict):
            return Result(result, None)
        return Result(result, reg.unit)

    async def get(self, name, slave=None):
        """Get named register from device."""
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
            missing_registers = set(names) - set(REGISTERS.keys())
            if missing_registers:
                raise ValueError(f"Did not recognize register names: {', '.join(missing_registers)}")
            raise ValueError("Did not recognize all register names")
        registers = t.cast(list[RegisterDefinition], registers)

        for register, register_name in zip(registers, names, strict=False):
            if not register.readable:
                raise ValueError(f"Trying to read unreadable register {register_name}")

        for idx in range(1, len(names)):
            if registers[idx - 1].register + registers[idx - 1].length > registers[idx].register:
                raise ValueError(
                    f"Requested registers must be in monotonically increasing order, "
                    f"but {registers[idx-1].register} + {registers[idx-1].length} > {registers[idx].register}!",
                )

            register_distance = registers[idx - 1].register + registers[idx - 1].length - registers[idx].register

            if register_distance > MAX_BATCHED_REGISTERS_COUNT:
                raise ValueError(
                    "Gap between requested registers is too large. Split it in two requests",
                )

        total_length = registers[-1].register + registers[-1].length - registers[0].register

        response = await self._read_registers(
            registers[0].register,
            total_length,
            slave,
        )

        start_register = registers[0].register

        return [
            await self._decode_response(
                reg,
                response.registers[reg.register - start_register : reg.register - start_register + reg.length],
            )
            for reg in registers
        ]

    async def _read_registers(  # noqa: C901
        self,
        register: int,
        length: int,
        slave: int | None,
    ):
        """Async read register from device.

        The device needs a bit of time between the connection and the first request
        and between requests if there is a long time between them, else it will fail.

        This is solved by sleeping between the first connection and a request,
        and up to 5 retries between following requests.

        It seems to only support connections from one device at the same time.
        """

        def on_backoff(details):
            LOGGER.debug(
                "Received %s: backing off reading for %0.1f seconds after %d tries",
                sys.exc_info()[0],
                details["wait"],
                details["tries"],
            )

        def on_backoff_with_reconnect(details):
            if details["tries"] % 3 == 0:
                self._reconnect_task = asyncio.create_task(self._reconnect())
                LOGGER.debug(
                    "Received %s: reconnecting and backing off reading for %0.1f seconds after %d tries",
                    sys.exc_info()[0],
                    details["wait"],
                    details["tries"],
                )
            else:
                LOGGER.debug(
                    "Received %s: backing off reading for %0.1f seconds after %d tries",
                    sys.exc_info()[0],
                    details["wait"],
                    details["tries"],
                )

        def backoff_giveup(details):
            raise ReadException(
                f"Failed to read register {register} after {details['tries']} tries",
            )

        @backoff.on_exception(
            backoff.expo,
            (asyncio.TimeoutError, ConnectionInterruptedException),
            max_tries=6,
            jitter=None,
            on_backoff=on_backoff_with_reconnect,
            on_giveup=backoff_giveup,
        )
        @backoff.on_exception(
            backoff.expo,
            (SlaveBusyException, SlaveFailureException),
            max_tries=6,
            jitter=None,
            on_backoff=on_backoff,
            on_giveup=backoff_giveup,
        )
        async def _do_read():
            if not self._client.connected:
                message = "Modbus client is not connected to the inverter"
                LOGGER.exception(message)
                raise ConnectionInterruptedException(message)
            try:
                response = await self._client.read_holding_registers(
                    register,
                    count=length,
                    slave=slave or self.slave_id,
                )

                # trigger a backoff if we get a SlaveBusy-exception
                if isinstance(response, ExceptionResponse):
                    if response.exception_code == ExceptionResponse.SLAVE_BUSY:
                        LOGGER.debug(
                            "Got a SlaveBusy Modbus Exception while reading %d (length %d) from slave %d",
                            register,
                            length,
                            slave or self.slave_id,
                        )
                        raise SlaveBusyException

                    if response.exception_code == ExceptionResponse.SLAVE_FAILURE:
                        LOGGER.debug(
                            "Got a SlaveFailure Modbus Exception while reading %d (length %d) from slave %d",
                            register,
                            length,
                            slave or self.slave_id,
                        )
                        raise SlaveFailureException

                    # Not a SlaveBusy or SlaveFailure exception
                    raise ReadException(
                        f"Got error while reading from register {register} with length {length}: {response}",
                        modbus_exception_code=response.exception_code,
                    )

                if len(response.registers) != length:
                    raise SlaveBusyException(
                        f"Mismatch between number of requested registers ({length}) "
                        f"and number of received registers ({len(response.registers)})",
                    )

            except ModbusConnectionException as err:
                message = "Could not read register value, has another device interrupted the connection?"
                LOGGER.exception(message)
                raise ConnectionInterruptedException(message) from err
            else:
                return response

        async with self._communication_lock():
            LOGGER.debug(
                "Reading register %d with length %d from slave %s",
                register,
                length,
                slave or self.slave_id,
            )
            return await _do_read()

    async def _read_device_identifier_objects(self, read_dev_id_code: int, object_id: int):
        """Read all the objects of a certain ReadDevId code."""
        next_object_id: int | None = object_id

        objects = {}

        while next_object_id is not None:
            response = await self._client.execute(
                no_response_expected=False,
                request=ReadDeviceIdentifierRequest(
                    read_dev_id_code=read_dev_id_code,
                    object_id=next_object_id,
                ),
            )

            if isinstance(response, ExceptionResponse):
                if response.exception_code == PERMISSION_DENIED_EXCEPTION_CODE:
                    raise PermissionDenied("Permission denied")
                if response.exception_code == ExceptionResponse.SLAVE_BUSY:
                    raise SlaveBusyException
                if response.exception_code == ExceptionResponse.SLAVE_FAILURE:
                    raise SlaveFailureException
                raise ReadException(
                    f"Exception occurred while trying to read device infos "
                    f"{hex(response.exception_code) if response.exception_code else 'no exception code'}",
                    modbus_exception_code=response.exception_code,
                )

            assert isinstance(response, ReadDeviceIdentifierResponse)
            objects.update(response.objects)
            next_object_id = response.next_object_id if response.more else None

        return objects

    async def get_device_identifiers(self):
        """Read the device identifiers from the inverter."""
        objects = await self._read_device_identifier_objects(0x01, 0x00)

        return DeviceIdentifier(
            vendor=objects.pop(0x00).decode("ascii"),
            product_code=objects.pop(0x01).decode("ascii"),
            main_revision_version=objects.pop(0x02).decode("ascii"),
            other_data=objects,
        )

    async def get_device_infos(self):
        """Read the device infos from the inverter."""
        objects = await self._read_device_identifier_objects(0x03, DEVICE_INFOS_START_OBJECT_ID)

        def _parse_device_entry(device_info_str: str) -> DeviceInfo:
            raw_device_info: dict[int, str] = {}
            for entry in device_info_str.split(";"):
                key, value = entry.split("=")
                raw_device_info[int(key)] = value

            return DeviceInfo(
                model=raw_device_info.get(1),
                software_version=raw_device_info.get(2),
                interface_protocol_version=raw_device_info.get(3),
                esn=raw_device_info.get(4),
                device_id=int(raw_device_info[5]) if 5 in raw_device_info else None,  # noqa: PLR2004
                feature_version=raw_device_info.get(6),
                unknown_field=raw_device_info.get(7),
                product_type=raw_device_info.get(8),
            )

        if DEVICE_INFOS_START_OBJECT_ID in objects:
            (number_of_devices,) = struct.unpack(">B", objects.pop(DEVICE_INFOS_START_OBJECT_ID))
        else:
            LOGGER.warning("No 0x87 entry with number of devices found in objects. Ignoring")
            number_of_devices = -1

        device_infos = [
            _parse_device_entry(device_info_bytes.decode("ascii")) for device_info_bytes in objects.values()
        ]

        if number_of_devices >= 0 and len(device_infos) != number_of_devices:
            LOGGER.warning(
                "Number of device infos does not match the number of devices: %d != %d",
                len(device_infos),
                number_of_devices,
            )

        return device_infos

    async def get_file(
        self,
        file_type,
        customized_data=None,
        slave: int | None = None,
    ) -> bytes:
        """Read a 'file' via Modbus.

        As defined by the 'Uploading Files' process described in 6.3.7.1 of
        the Solar Inverter Modbus Interface Definitions PDF.
        """

        def backoff_giveup(details):
            raise ReadException(
                f"Failed to read file {file_type} after {details['tries']} tries",
            )

        @backoff.on_exception(
            backoff.constant,
            (asyncio.TimeoutError, SlaveBusyException, SlaveFailureException),
            interval=FILE_UPLOAD_RETRY_TIMEOUT,
            max_tries=FILE_UPLOAD_MAX_RETRIES,
            jitter=None,
            on_backoff=lambda details: LOGGER.debug(
                "Received %s: backing off file upload for %0.1f seconds after %d tries",
                sys.exc_info()[0],
                details.get("wait"),
                details["tries"],
            ),
            on_giveup=backoff_giveup,
        )
        async def _perform_request(request: ModbusPDU, response_type):
            response = cast(
                PrivateHuaweiModbusResponse,
                await self._client.execute(no_response_expected=False, request=request),
            )

            if isinstance(response, ExceptionResponse):
                if response.exception_code == PERMISSION_DENIED_EXCEPTION_CODE:
                    raise PermissionDenied("Permission denied")
                if response.exception_code == ExceptionResponse.SLAVE_BUSY:
                    raise SlaveBusyException
                if response.exception_code == ExceptionResponse.SLAVE_FAILURE:
                    raise SlaveFailureException
                raise ReadException(
                    f"Exception occurred while trying to read file {hex(file_type)}: "
                    f"{hex(response.exception_code) if response.exception_code else 'no exception code'}",
                    modbus_exception_code=response.exception_code,
                )

            return response_type(response.content)

        async def _do_read_file():
            # Start the upload
            start_upload_response = await _perform_request(
                StartUploadModbusRequest(
                    file_type,
                    customized_data,
                    dev_id=slave or self.slave_id,
                ),
                StartUploadModbusResponse,
            )

            data_frame_length = start_upload_response.data_frame_length
            file_length = start_upload_response.file_length

            # Request the data in 'frames'

            file_data = b""
            next_frame_no = 0

            while (next_frame_no * data_frame_length) < file_length:
                data_upload_response = await _perform_request(
                    UploadModbusRequest(
                        file_type,
                        next_frame_no,
                        dev_id=slave or self.slave_id,
                    ),
                    UploadModbusResponse,
                )

                file_data += data_upload_response.frame_data
                next_frame_no += 1

            # Complete the upload and check the CRC
            complete_upload_response = await _perform_request(
                CompleteUploadModbusRequest(file_type, dev_id=slave or self.slave_id),
                CompleteUploadModbusResponse,
            )

            file_crc = complete_upload_response.file_crc
            # swap upper and lower two bytes to match how computeCRC works
            swapped_crc = ((file_crc << 8) & 0xFF00) | ((file_crc >> 8) & 0x00FF)

            if not FramerRTU.check_CRC(file_data, swapped_crc):
                raise ReadException(
                    f"Computed CRC {FramerRTU.compute_CRC(file_data):x} for file {file_type} "
                    f"does not match expected value {swapped_crc}",
                )

            return file_data

        async with self._communication_lock():
            LOGGER.debug(
                "Reading file %#x from slave %d",
                file_type,
                slave or self.slave_id,
            )
            return await _do_read_file()

    async def set(self, name, value, slave=None):
        """Set named register on device."""
        try:
            reg = REGISTERS[name]
        except KeyError as err:
            raise ValueError("Invalid Register Name") from err

        if not reg.writeable:
            raise WriteException("Register is not writable")

        registers = reg.encode(value)

        if len(registers) != reg.length:
            raise WriteException("Wrong number of registers to write")

        def backoff_giveup(details):
            raise ReadException(
                f"Failed to write to register after {details['tries']} tries",
            )

        @backoff.on_exception(
            backoff.expo,
            (asyncio.TimeoutError, SlaveBusyException, ConnectionInterruptedException),
            max_tries=3,
            jitter=None,
            on_backoff=lambda details: LOGGER.debug(
                "Received %s: backing off writing for %0.1f seconds after %d tries",
                sys.exc_info()[0],
                details.get("wait"),
                details["tries"],
            ),
            on_giveup=backoff_giveup,
        )
        async def _do_set():
            return await self._write_registers(
                reg.register,
                registers,
                slave,
            )

        async with self._communication_lock():
            LOGGER.debug(
                "Writing to register %s value %s on slave %s",
                name,
                registers,
                slave or self.slave_id,
            )
            return await _do_set()

    async def _write_registers(
        self,
        register: int,
        value: list[int],
        slave=None,
    ) -> bool:
        """Async write register to device."""
        if not self._client.connected:
            message = "Modbus client is not connected to the inverter."
            LOGGER.exception(message)
            raise ConnectionInterruptedException(message)
        try:
            LOGGER.debug(
                "Writing to %d: %s on slave %d",
                register,
                value,
                slave or self.slave_id,
            )

            single_register = len(value) == 1
            if single_register:
                response = await self._client.write_register(
                    register,
                    value[0],
                    slave=slave or self.slave_id,
                )

            else:
                response = await self._client.write_registers(
                    register,
                    value,
                    slave=slave or self.slave_id,
                )

            if isinstance(response, ExceptionResponse):
                if response.exception_code == PERMISSION_DENIED_EXCEPTION_CODE:
                    raise PermissionDenied("Permission denied")
                if response.exception_code == ExceptionResponse.ILLEGAL_ADDRESS:
                    # cfr. https://github.com/wlcrs/huawei_solar/issues/587
                    raise PermissionDenied(
                        f"Failed to write value {value} to register {register} due to IllegalAddress. "
                        "Assuming permission problem.",
                    )
                raise WriteException(
                    f"Failed to write value {value} to register {register}: {response.exception_code:02x}",
                    modbus_exception_code=response.exception_code,
                )

            if single_register:
                assert isinstance(response, WriteSingleRegisterResponse)
                return response.address == register and response.registers == [value[0]]
            assert isinstance(response, WriteMultipleRegistersResponse)
            return response.address == register and response.count == len(value)
        except ModbusConnectionException as err:
            LOGGER.exception("Failed to connect to device, is the host correct?")
            raise ConnectionInterruptedException(err) from err

    async def login(self, username: str, password: str, slave: int | None = None) -> bool:
        """Login into the inverter."""

        def backoff_giveup(details):
            raise ReadException(f"Failed to login after {details['tries']} tries")

        @backoff.on_exception(
            backoff.expo,
            (
                asyncio.TimeoutError,
                SlaveBusyException,
                SlaveFailureException,
                SlaveFailureException,
            ),
            max_tries=4,
            jitter=None,
            on_backoff=lambda details: LOGGER.debug(
                "Received %s: backing off login for %0.1f seconds after %d tries",
                sys.exc_info()[0],
                details.get("wait"),
                details["tries"],
            ),
            on_giveup=backoff_giveup,
        )
        async def _do_login() -> bool:
            # Get challenge
            challenge_request = PrivateHuaweiModbusRequest(
                36,
                bytes([1, 0]),
                dev_id=slave or self.slave_id,
            )

            challenge_response = cast(
                PrivateHuaweiModbusResponse,
                await self._client.execute(no_response_expected=False, request=challenge_request),
            )

            assert challenge_response.content[0] == LOGIN_CHALLENGE_SUBCOMMAND
            inverter_challenge = challenge_response.content[1:17]

            client_challenge = secrets.token_bytes(16)

            encoded_username = username.encode("utf-8")
            hashed_password = _compute_digest(
                password.encode("utf-8"),
                inverter_challenge,
            )

            login_bytes = bytes(
                [
                    len(client_challenge) + 1 + len(encoded_username) + 1 + len(hashed_password),
                    *client_challenge,
                    len(encoded_username),
                    *encoded_username,
                    len(hashed_password),
                    *hashed_password,
                ],
            )
            await asyncio.sleep(0.05)
            login_request = PrivateHuaweiModbusRequest(
                37,
                login_bytes,
                dev_id=slave or self.slave_id,
            )
            login_response = cast(
                PrivateHuaweiModbusResponse,
                await self._client.execute(no_response_expected=False, request=login_request),
            )

            if login_response.content[1] == 0:
                # check if inverter returned the right hash of the password as well
                inverter_mac_response_lengths = login_response.content[2]

                inverter_mac_response = login_response.content[3 : 3 + inverter_mac_response_lengths]

                if _compute_digest(password.encode("utf-8"), client_challenge) != inverter_mac_response:
                    LOGGER.error(
                        "Inverter response contains an invalid challenge answer. This could indicate a MitM-attack!",
                    )

                return True
            return False

        async with self._communication_lock():
            LOGGER.debug("Logging in")
            return await _do_login()

    async def heartbeat(self, slave_id):
        """Perform the heartbeat command. Only useful when maintaining a session."""
        if not self._client.connected:
            return False
        try:
            # 49999 is the magic register used to keep the connection alive
            response = await self._client.write_register(
                HEARTBEAT_REGISTER,
                0x1,
                slave=slave_id or self.slave_id,
            )
            if isinstance(response, ExceptionResponse):
                LOGGER.warning("Received an error after sending the heartbeat command: %02x", response.exception_code)
                return False
            LOGGER.debug("Heartbeat succeeded")
        except HuaweiSolarException:
            LOGGER.exception("Exception during heartbeat")
            return False
        else:
            return True
