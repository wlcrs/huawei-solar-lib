"""
Get production and status information from the Huawei Inverter using Modbus over TCP
"""
import asyncio
import logging
import typing as t
from collections import namedtuple
from hashlib import sha256
import hmac
import secrets

import backoff
from pymodbus.client.asynchronous.async_io import (
    ReconnectingAsyncioModbusTcpClient,
    init_tcp_client,
)
from pymodbus.constants import Endian
from pymodbus.exceptions import ConnectionException as ModbusConnectionException
from pymodbus.payload import BinaryPayloadDecoder, BinaryPayloadBuilder
from pymodbus.pdu import ModbusRequest, ModbusResponse, ModbusExceptions
from pymodbus.pdu import ExceptionResponse
from pymodbus.factory import ClientDecoder
from pymodbus.transaction import ModbusSocketFramer

import huawei_solar.register_names as rn

from .exceptions import (
    ConnectionException,
    HuaweiSolarException,
    PermissionDenied,
    ReadException,
    SlaveBusyException,
    WriteException,
)
from .registers import REGISTERS, RegisterDefinition

LOGGER = logging.getLogger(__name__)

Result = namedtuple("Result", "value unit")

DEFAULT_SLAVE = 0
DEFAULT_TIMEOUT = 5
DEFAULT_WAIT = 2
DEFAULT_COOLDOWN_TIME = 0.05

HEARTBEAT_REGISTER = 49999


def _compute_digest(password, seed):
    hashed_password = sha256(password).digest()

    return hmac.digest(key=hashed_password, msg=seed, digest=sha256)


class AsyncHuaweiSolar:
    """Async interface to the Huawei solar inverter"""

    def __init__(
        self,
        client: ReconnectingAsyncioModbusTcpClient,
        slave: int = DEFAULT_SLAVE,
        timeout: int = DEFAULT_TIMEOUT,
        cooldown_time: int = DEFAULT_COOLDOWN_TIME,
    ):
        """DO NOT USE THIS CONSTRUCTOR DIRECTLY. Use AsyncHuaweiSolar.create() instead"""
        self._client = client
        self._timeout = timeout
        self._cooldown_time = cooldown_time
        self.slave = slave

        # use this lock to prevent concurrent requests, as the
        # Huawei inverters can't cope with those
        self._communication_lock = asyncio.Lock()

        # These values are set by the `create()` method
        self.time_zone = None
        self.battery_type = None

    @classmethod
    async def create(
        cls,
        host,
        port="502",
        slave: int = DEFAULT_SLAVE,
        timeout: int = DEFAULT_TIMEOUT,
        cooldown_time: int = DEFAULT_COOLDOWN_TIME,
        loop=None,
    ):  # pylint: disable=too-many-arguments
        """Creates an AsyncHuaweiSolar instance."""

        client = None
        try:
            client = await cls.__get_client(host, port, loop)

            huawei_solar = cls(client, slave, timeout, cooldown_time)

            # get some registers which are needed to correctly decode all values

            huawei_solar.time_zone = (await huawei_solar.get(rn.TIME_ZONE)).value
            # we assume that when at least one battery is present, it will always be put in storage_unit_1 first
            huawei_solar.battery_type = (
                await huawei_solar.get(rn.STORAGE_UNIT_1_PRODUCT_MODEL)
            ).value

            return huawei_solar
        except Exception as err:
            # if an error occurs, we need to make sure that the Modbus-client is stopped,
            # otherwise it can stay active and cause even more problems ...
            if client is not None:
                client.stop()
            raise err

    @classmethod
    async def __get_client(cls, host, port, loop) -> ReconnectingAsyncioModbusTcpClient:

        decoder = ClientDecoder()
        decoder.register(PrivateHuaweiModbusResponse)
        client = await init_tcp_client(
            None,
            loop,
            host,
            port,
            reset_socket=False,
            framer=ModbusSocketFramer(decoder),
        )
        # wait a little bit to prevent a timeout on the first request
        await asyncio.sleep(1)

        return client

    async def stop(self):
        """Stop the modbus client."""
        self._client.stop()

    async def _decode_response(
        self, reg: RegisterDefinition, decoder: BinaryPayloadDecoder
    ):
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

        for idx in range(1, len(names)):
            if (
                registers[idx - 1].register + registers[idx - 1].length
                > registers[idx].register
            ):
                raise ValueError(
                    f"Requested registers must be in monotonically increasing order, "
                    f"but {registers[idx-1].register} + {registers[idx-1].length} > {registers[idx].register}!"
                )

            register_distance = (
                registers[idx - 1].register
                + registers[idx - 1].length
                - registers[idx].register
            )

            if register_distance > 64:
                raise ValueError(
                    "Gap between requested registers is too large. Split it in two requests"
                )

        total_length = (
            registers[-1].register + registers[-1].length - registers[0].register
        )

        response = await self._read_registers(
            registers[0].register, total_length, slave
        )

        decoder = BinaryPayloadDecoder.fromRegisters(
            response.registers, byteorder=Endian.Big, wordorder=Endian.Big
        )

        result = [await self._decode_response(registers[0], decoder)]
        for idx in range(1, len(registers)):
            skip_registers = registers[idx].register - (
                registers[idx - 1].register + registers[idx - 1].length
            )
            decoder.skip_bytes(
                skip_registers * 2
            )  # registers are 16-bit, so we need to multiply by two
            result.append(await self._decode_response(registers[idx], decoder))

        return result

    async def _read_registers(
        self, register: RegisterDefinition, length: int, slave: t.Optional[int]
    ):
        """
        Async read register from device.

        The device needs a bit of time between the connection and the first request
        and between requests if there is a long time between them, else it will fail.

        This is solved by sleeping between the first connection and a request,
        and up to 5 retries between following requests.

        It seems to only support connections from one device at the same time.
        """

        def backoff_giveup(details):
            raise ReadException(
                f"Failed to read register {register} after {details['tries']} tries"
            )

        @backoff.on_exception(
            backoff.constant,
            (asyncio.TimeoutError, SlaveBusyException),
            interval=DEFAULT_WAIT,
            max_tries=5,
            jitter=None,
            on_backoff=lambda details: LOGGER.debug(
                "Backing off reading for %0.1f seconds after %d tries",
                details["wait"],
                details["tries"],
            ),
            on_giveup=backoff_giveup,
        )
        async def _do_read():

            if not self._client.connected:
                message = "Modbus client is not connected to the inverter."
                LOGGER.exception(message)
                raise ConnectionException(message)
            try:
                response = await self._client.protocol.read_holding_registers(
                    register,
                    length,
                    unit=slave or self.slave,
                    timeout=self._timeout,
                )

                # trigger a backoff if we get a SlaveBusy-exception
                if isinstance(response, ExceptionResponse):
                    if response.exception_code == ModbusExceptions.SlaveBusy:
                        raise SlaveBusyException()

                    # Not a slavebusy-exception
                    raise ReadException(
                        f"Got error while reading from register {register} with length {length}: {response}"
                    )

                return response

            except ModbusConnectionException as err:
                message = "Could not read register value, has another device interrupted the connection?"
                LOGGER.error(message)
                raise ReadException(message) from err
            # errors are different with async pymodbus,
            # we should not be able to reach this code. Keep it for debugging
            message = "could not read register value for unknown reason"
            LOGGER.error(message)
            raise ReadException(message)

        async with self._communication_lock:
            LOGGER.debug("Reading register %s", register)
            result = await _do_read()
            await asyncio.sleep(
                self._cooldown_time
            )  # throttle requests to prevent errors
            return result

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

        async with self._communication_lock:
            response = await self.write_registers(
                reg.register, builder.to_registers(), slave
            )
            await asyncio.sleep(self._cooldown_time)

        if isinstance(response, ExceptionResponse):
            raise WriteException(
                f"Got error while writing from register {reg.register} : {response}"
            )

        return response.address == reg.register and response.count == reg.length

    async def write_registers(self, register, value, slave=None):
        """
        Async write register to device.
        """
        if not self._client.connected:
            message = "Modbus client is not connected to the inverter."
            LOGGER.exception(message)
            raise ConnectionException(message)
        try:
            LOGGER.debug("Writing to %s: %s", register, value)

            response = await self._client.protocol.write_registers(
                register,
                value,
                unit=slave or self.slave,
                timeout=self._timeout,
            )
            if isinstance(response, ExceptionResponse):
                if response.exception_code == 0x80:
                    raise PermissionDenied("Permission denied")
                raise WriteException(ModbusExceptions.decode(response.exception_code))
            return response
        except ModbusConnectionException as err:
            LOGGER.exception("Failed to connect to device, is the host correct?")
            raise ConnectionException(err) from err

    async def login(self, username: str, password: str):
        """Login into the inverter."""

        # Get challenge
        challenge_request = PrivateHuaweiModbusRequest(36, bytes([1, 0]))

        challenge_response = await self._client.protocol.execute(challenge_request)

        assert challenge_response.content[0] == 0x11
        inverter_challenge = challenge_response.content[1:17]

        client_challenge = secrets.token_bytes(16)

        encoded_username = username.encode("utf-8")
        hashed_password = _compute_digest(password.encode("utf-8"), inverter_challenge)

        login_bytes = bytes(
            [
                len(client_challenge)
                + 1
                + len(encoded_username)
                + 1
                + len(hashed_password),
                *client_challenge,
                len(encoded_username),
                *encoded_username,
                len(hashed_password),
                *hashed_password,
            ]
        )
        await asyncio.sleep(0.05)
        login_request = PrivateHuaweiModbusRequest(37, login_bytes)
        login_response = await self._client.protocol.execute(login_request)

        if login_response.content[1] == 0:

            # check if inverter returned the right hash of the password as well
            inverter_mac_response_lengths = login_response.content[2]

            inverter_mac_response = login_response.content[
                3 : 3 + inverter_mac_response_lengths
            ]

            if (
                not _compute_digest(password.encode("utf-8"), client_challenge)
                == inverter_mac_response
            ):
                LOGGER.error(
                    "Inverter response contains an invalid challenge answer. This could indicate a MitM-attack!"
                )

            return True
        return False

    async def heartbeat(self, slave_id):
        """Performs the heartbeat command. Only useful when maintaining a session."""
        if not self._client.connected:
            return False
        try:
            # 49999 is the magic register used to keep the connection alive
            response = await self._client.protocol.write_register(
                HEARTBEAT_REGISTER, 0x1, slave=slave_id or self.slave
            )
            if isinstance(response, ExceptionResponse):
                LOGGER.warning(
                    "Received an error after sending the heartbeat command: %s",
                    response,
                )
                return False
            LOGGER.debug("Heartbeat succeeded")
            return True
        except HuaweiSolarException as err:
            LOGGER.exception("Exception during heartbeat: %s", err)
            return False


class PrivateHuaweiModbusResponse(ModbusResponse):
    """Response with the private Huawei Solar function code"""

    function_code = 65

    def __init__(self, **kwargs):
        ModbusResponse.__init__(self, **kwargs)

        self.sub_command = None
        self.content = bytes()

    def decode(self, data):
        self.sub_command = int(data[0])
        self.content = data[1:]

    def __str__(self):
        return f"{self.__class__.__name__}({self.sub_command})"


class PrivateHuaweiModbusRequest(ModbusRequest):
    """Request with the private Huawei Solar function code"""

    function_code = 65

    def __init__(self, sub_command, content: bytes):
        ModbusRequest.__init__(self)
        self.sub_command = sub_command
        self.content = content

    def encode(self):
        return bytes([self.sub_command, *self.content])

    def decode(self, data):
        self.sub_command = int(data[0])
        self.content = data[1:]

    def __str__(self):
        return f"{self.__class__.__name__}({self.sub_command})"
