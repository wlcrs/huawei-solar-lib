"""Low-level Modbus logic."""

import asyncio
import logging
import struct
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Self, TypeVar, cast

import backoff
from tmodbus.client import AsyncModbusClient
from tmodbus.exceptions import (
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusResponseError,
    ServerDeviceBusyError,
    ServerDeviceFailureError,
    TModbusError,
)
from tmodbus.transport import AsyncRtuTransport, AsyncTcpTransport
from tmodbus.transport.async_rtu import PySerialOptions
from tmodbus.utils.crc import calculate_crc16

from .const import DEVICE_INFOS_START_OBJECT_ID, MAX_BATCHED_REGISTERS_COUNT
from .exceptions import (
    ConnectionException,
    ConnectionInterruptedException,
    ReadException,
    UnexpectedResponseContent,
    WriteException,
)
from .modbus import (
    CompleteUploadPDU,
    LoginPDU,
    LoginRequestChallengePDU,
    PermissionDeniedError,
    StartFileUploadPDU,
    UploadFileFramePDU,
)
from .registers import REGISTERS, RegisterDefinition

if TYPE_CHECKING:
    from backoff.types import Details

LOGGER = logging.getLogger(__name__)

RT = TypeVar("RT")


class Result(NamedTuple):
    """Modbus register value."""

    value: Any
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

    def __init__(
        self,
        client: AsyncModbusClient,
        slave_id: int = DEFAULT_SLAVE_ID,
        timeout: int = DEFAULT_TIMEOUT,
        cooldown_time: float = DEFAULT_COOLDOWN_TIME,
    ) -> None:
        """DO NOT USE THIS CONSTRUCTOR DIRECTLY. Use AsyncHuaweiSolar.create() instead."""
        self._client = client
        self._timeout = timeout
        self._cooldown_time = cooldown_time
        self.slave_id = slave_id

        # use this lock to prevent concurrent requests, as the
        # Huawei inverters can't cope with those
        self.__communication_lock = asyncio.Lock()

    @asynccontextmanager
    async def _communication_lock(self) -> AsyncGenerator[None]:
        async with self.__communication_lock:
            if not self._client.connected:
                LOGGER.warning("Client not connected, trying to (re)connect")
                try:
                    await self._client.connect()
                except TimeoutError:
                    LOGGER.exception("Failed to reconnect with %.2fs", self._timeout)
                    raise

            yield

    @classmethod
    async def create(
        cls,
        host: str,
        port: int = DEFAULT_TCP_PORT,
        slave_id: int = DEFAULT_SLAVE_ID,
        timeout: int = DEFAULT_TIMEOUT,  # noqa: ASYNC109
        cooldown_time: float = DEFAULT_COOLDOWN_TIME,
    ) -> Self:
        """Create an AsyncHuaweiSolar instance."""
        transport = AsyncTcpTransport(host, port, timeout=timeout, wait_between_requests=cooldown_time)
        client = AsyncModbusClient(transport)

        try:
            await client.connect()
        except Exception as err:
            # if an error occurs, we need to make sure that the Modbus-client is stopped,
            # otherwise it can stay active and cause even more problems ...
            LOGGER.exception("Aborting client creation due to error")

            try:
                await client.close()
            except Exception:
                LOGGER.exception("Error occurred while closing client. Ignoring")

            raise ConnectionException from err
        else:
            return cls(client, slave_id, timeout, cooldown_time)

    @classmethod
    async def create_rtu(
        cls,
        port: str,
        slave_id: int = DEFAULT_SLAVE_ID,
        *,
        timeout: int = DEFAULT_TIMEOUT,  # noqa: ASYNC109
        cooldown_time: float = DEFAULT_COOLDOWN_TIME,
        **serial_kwargs: PySerialOptions,
    ) -> Self:
        """Create a serial client."""
        if "baudrate" not in serial_kwargs:
            serial_kwargs["baudrate"] = DEFAULT_BAUDRATE

        transport = AsyncRtuTransport(port, wait_between_requests=cooldown_time, **serial_kwargs)
        client = AsyncModbusClient(transport)
        try:
            await client.connect()
        except Exception as err:
            # if an error occurs, we need to make sure that the Modbus-client is stopped,
            # otherwise it can stay active and cause even more problems ...
            LOGGER.exception("Aborting client creation due to error")

            try:
                await client.close()
            except Exception:
                LOGGER.exception("Error occurred while closing client. Ignoring")

            raise ConnectionException from err
        else:
            return cls(client, slave_id, timeout, cooldown_time)

    async def stop(self) -> None:
        """Stop the modbus client."""
        async with self.__communication_lock:
            await self._client.close()

    async def _reconnect(self) -> None:
        """Reconnect to the inverter."""
        async with self.__communication_lock:
            await self._client.close()
            await self._client.connect()

    async def _decode_response(
        self,
        reg: RegisterDefinition,
        registers: list[int],
    ) -> Result:
        """Decode a modbus register and puts it into a Result object."""
        result = reg.decode(registers)

        if not hasattr(reg, "unit") or callable(reg.unit) or isinstance(reg.unit, dict):
            return Result(result, None)
        return Result(result, reg.unit)

    async def get(self, name: str, slave_id: int | None = None) -> Result:
        """Get named register from device."""
        return (await self.get_multiple([name], slave_id))[0]

    async def get_multiple(self, names: list[str], slave_id: int | None = None) -> list[Result]:
        """Read multiple registers at the same time.

        This is only possible if the registers are consecutively available in the
        inverters' memory.
        """
        if len(names) == 0:
            msg = "Expected at least one register name"
            raise ValueError(msg)

        registers = list(map(REGISTERS.get, names))

        if None in registers:
            missing_registers = set(names) - set(REGISTERS.keys())
            if missing_registers:
                msg = f"Did not recognize register names: {', '.join(missing_registers)}"
                raise ValueError(msg)
            msg = "Did not recognize all register names"
            raise ValueError(msg)
        registers = cast("list[RegisterDefinition]", registers)

        for register, register_name in zip(registers, names, strict=False):
            if not register.readable:
                msg = f"Trying to read unreadable register {register_name}"
                raise ValueError(msg)

        for idx in range(1, len(names)):
            if registers[idx - 1].register + registers[idx - 1].length > registers[idx].register:
                msg = (
                    f"Requested registers must be in monotonically increasing order, "
                    f"but {registers[idx - 1].register} + {registers[idx - 1].length} > {registers[idx].register}!"
                )
                raise ValueError(msg)

            register_distance = registers[idx - 1].register + registers[idx - 1].length - registers[idx].register

            if register_distance > MAX_BATCHED_REGISTERS_COUNT:
                msg = "Gap between requested registers is too large. Split it in two requests"
                raise ValueError(msg)

        total_length = registers[-1].register + registers[-1].length - registers[0].register

        response_registers = await self._read_registers(
            registers[0].register,
            total_length,
            slave_id,
        )

        start_register = registers[0].register

        return [
            await self._decode_response(
                reg,
                response_registers[reg.register - start_register : reg.register - start_register + reg.length],
            )
            for reg in registers
        ]

    async def _read_registers(
        self,
        register: int,
        length: int,
        slave_id: int | None,
    ) -> list[int]:
        """Async read register from device.

        The device needs a bit of time between the connection and the first request
        and between requests if there is a long time between them, else it will fail.

        This is solved by sleeping between the first connection and a request,
        and up to 5 retries between following requests.

        It seems to only support connections from one device at the same time.
        """

        def on_backoff(details: "Details") -> None:
            LOGGER.debug(
                "Received %s: backing off reading for %0.1f seconds after %d tries",
                sys.exc_info()[0],
                details.get("wait"),
                details["tries"],
            )

        def on_backoff_with_reconnect(details: "Details") -> None:
            if details["tries"] % 3 == 0:
                self._reconnect_task = asyncio.create_task(self._reconnect())
                LOGGER.debug(
                    "Received %s: reconnecting and backing off reading for %0.1f seconds after %d tries",
                    sys.exc_info()[0],
                    details.get("wait"),
                    details["tries"],
                )
            else:
                LOGGER.debug(
                    "Received %s: backing off reading for %0.1f seconds after %d tries",
                    sys.exc_info()[0],
                    details.get("wait"),
                    details["tries"],
                )

        def backoff_giveup(details: "Details") -> None:
            msg = f"Failed to read register {register} after {details['tries']} tries"
            raise ReadException(msg)

        @backoff.on_exception(
            backoff.expo,
            (asyncio.TimeoutError, ConnectionInterruptedException, UnexpectedResponseContent),
            max_tries=6,
            jitter=None,
            on_backoff=on_backoff_with_reconnect,
            on_giveup=backoff_giveup,
        )
        @backoff.on_exception(
            backoff.expo,
            (ServerDeviceFailureError, ServerDeviceBusyError),
            max_tries=6,
            jitter=None,
            on_backoff=on_backoff,
            on_giveup=backoff_giveup,
        )
        async def _do_read() -> list[int]:
            try:
                response_registers = await self._client.read_holding_registers(
                    register,
                    quantity=length,
                    unit_id=slave_id or self.slave_id,
                )
            # trigger a backoff if we get a SlaveBusy-exception
            except (ServerDeviceBusyError, ServerDeviceFailureError) as e:
                LOGGER.debug(
                    "Got a %s while reading %d (length %d) from server %d",
                    type(e).__name__,
                    register,
                    length,
                    slave_id or self.slave_id,
                )
                raise
            except ModbusResponseError as e:
                LOGGER.exception(
                    "Got a ModbusResponseError while reading %d (length %d) from server %d",
                    register,
                    length,
                    slave_id or self.slave_id,
                )
                msg = f"Got error while reading from register {register} with length {length}: {e}"
                raise ReadException(msg, modbus_exception_code=e.error_code) from e

            except ModbusConnectionError as err:
                message = "Could not read register value, has another device interrupted the connection?"
                LOGGER.exception(message)
                raise ConnectionInterruptedException(message) from err
            else:
                if len(response_registers) != length:
                    msg = (
                        f"Mismatch between number of requested registers ({length}) "
                        f"and number of received registers ({len(response_registers)})"
                    )
                    raise UnexpectedResponseContent(msg)

                return response_registers

        async with self._communication_lock():
            LOGGER.debug(
                "Reading register %d with length %d from server %s",
                register,
                length,
                slave_id or self.slave_id,
            )
            return await _do_read()

    async def _read_device_identifier_objects(
        self,
        read_dev_id_code: Literal[0x01, 0x03],
        object_id: int,
    ) -> dict[int, bytes]:
        """Read all the objects of a certain ReadDevId code."""
        try:
            return await self._client.read_device_identification(
                device_code=read_dev_id_code,
                object_id=object_id,
                unit_id=self.slave_id,
            )
        except (ServerDeviceBusyError, ServerDeviceFailureError, PermissionDeniedError) as e:
            LOGGER.debug(
                "Got a %s while reading device identification from server %d",
                type(e).__name__,
                self.slave_id,
            )
            raise
        except ModbusResponseError as e:
            msg = (
                f"Exception occurred while trying to read device infos "
                f"{hex(e.error_code) if e.error_code else 'no exception code'}"
            )
            raise ReadException(msg, modbus_exception_code=e.error_code) from e

    async def get_device_identifiers(self) -> DeviceIdentifier:
        """Read the device identifiers from the inverter."""
        objects = await self._read_device_identifier_objects(0x01, 0x00)

        return DeviceIdentifier(
            vendor=objects.pop(0x00).decode("ascii"),
            product_code=objects.pop(0x01).decode("ascii"),
            main_revision_version=objects.pop(0x02).decode("ascii"),
            other_data=objects,
        )

    async def get_device_infos(self) -> list[DeviceInfo]:
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
        file_type: int,
        customized_data: bytes | None = None,
        slave_id: int | None = None,
    ) -> bytes:
        """Read a 'file' via Modbus.

        As defined by the 'Uploading Files' process described in 6.3.7.1 of
        the Solar Inverter Modbus Interface Definitions PDF.
        """

        # TODO: add backoff and retry
        async def _do_read_file() -> bytes:
            # Start the upload
            start_upload_response = await self._client.execute(
                StartFileUploadPDU(
                    file_type=file_type,
                    customised_data=customized_data or b"",
                ),
                unit_id=slave_id or self.slave_id,
            )

            file_length = start_upload_response.file_length
            data_frame_length = start_upload_response.data_frame_length

            # Request the data in 'frames'

            file_data: bytes = b""
            next_frame_no = 0

            while (next_frame_no * data_frame_length) < file_length:
                data_upload_response = await self._client.execute(
                    UploadFileFramePDU(file_type=file_type, frame_no=next_frame_no),
                    unit_id=slave_id or self.slave_id,
                )

                file_data += data_upload_response.frame_data
                next_frame_no += 1

            # Complete the upload and check the CRC
            file_crc = await self._client.execute(
                CompleteUploadPDU(file_type=file_type),
                unit_id=slave_id or self.slave_id,
            )

            # swap upper and lower two bytes to match how computeCRC works
            swapped_crc = ((file_crc << 8) & 0xFF00) | ((file_crc >> 8) & 0x00FF)

            if calculate_crc16(file_data) != swapped_crc:
                msg = (
                    f"Computed CRC {calculate_crc16(file_data):x} for file {file_type} "
                    f"does not match expected value {swapped_crc}"
                )
                raise ReadException(msg)

            return file_data

        async with self._communication_lock():
            LOGGER.debug(
                "Reading file %#x from server %d",
                file_type,
                slave_id or self.slave_id,
            )
            return await _do_read_file()

    async def set(
        self,
        name: str,
        value: Any,  # noqa: ANN401
        slave_id: int | None = None,
    ) -> bool:
        """Set named register on device."""
        try:
            reg = REGISTERS[name]
        except KeyError as err:
            msg = "Invalid Register Name"
            raise ValueError(msg) from err

        if not reg.writeable:
            msg = "Register is not writable"
            raise WriteException(msg)

        registers = reg.encode(value)

        if len(registers) != reg.length:
            msg = "Wrong number of registers to write"
            raise WriteException(msg)

        def backoff_giveup(details: "Details") -> None:
            msg = f"Failed to write to register after {details['tries']} tries"
            raise ReadException(msg)

        @backoff.on_exception(
            backoff.expo,
            (asyncio.TimeoutError, ServerDeviceBusyError, ConnectionInterruptedException),
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
        async def _do_set() -> bool:
            return await self._write_registers(
                reg.register,
                registers,
                slave_id,
            )

        async with self._communication_lock():
            LOGGER.debug(
                "Writing to register %s value %s on server %s",
                name,
                registers,
                slave_id or self.slave_id,
            )
            return await _do_set()

    async def _write_registers(
        self,
        register: int,
        value: list[int],
        slave_id: int | None = None,
    ) -> bool:
        """Async write register to device."""
        if not self._client.connected:
            message = "Modbus client is not connected to the inverter."
            LOGGER.exception(message)
            raise ConnectionInterruptedException(message)
        try:
            LOGGER.debug(
                "Writing to %d: %s on server %d",
                register,
                value,
                slave_id or self.slave_id,
            )

            if len(value) == 1:
                response = await self._client.write_single_register(
                    register,
                    value[0],
                    unit_id=slave_id or self.slave_id,
                )
                return response == value[0]

            number_of_registers_written = await self._client.write_multiple_registers(
                register,
                value,
                unit_id=slave_id or self.slave_id,
            )
            return number_of_registers_written == len(value)

        except PermissionDeniedError:
            raise
        except IllegalDataAddressError as e:
            msg = (
                f"Failed to write value {value} to register {register} due to IllegalDataAddress. "
                "Assuming permission problem."
            )
            raise PermissionDeniedError(e.error_code, e.function_code) from e
        except ModbusResponseError as e:
            msg = f"Failed to write value {value} to register {register}: {e.error_code:02x}"
            raise WriteException(msg, modbus_exception_code=e.error_code) from e
        except ModbusConnectionError as err:
            LOGGER.exception("Failed to connect to device, is the host correct?")
            raise ConnectionInterruptedException(err) from err

    async def login(self, username: str, password: str, slave_id: int | None = None) -> bool:
        """Login into the inverter."""

        # TODO: add tenacity
        async def _do_login() -> bool:
            # Get challenge
            inverter_challenge = await self._client.execute(
                LoginRequestChallengePDU(),
                unit_id=slave_id or self.slave_id,
            )

            return await self._client.execute(
                LoginPDU(username, password, inverter_challenge),
                unit_id=slave_id or self.slave_id,
            )

        async with self._communication_lock():
            LOGGER.debug("Logging in")
            return await _do_login()

    async def heartbeat(self, slave_id: int | None = None) -> bool:
        """Perform the heartbeat command. Only useful when maintaining a session."""
        if not self._client.connected:
            return False
        try:
            # 49999 is the magic register used to keep the connection alive
            await self._client.write_single_register(
                HEARTBEAT_REGISTER,
                0x1,
                unit_id=slave_id or self.slave_id,
            )
        except ModbusResponseError as e:
            LOGGER.warning("Received an error response when writing to the heartbeat register: %02x", e.error_code)
            return False
        except TModbusError:
            LOGGER.exception("Exception during heartbeat")
            return False
        else:
            LOGGER.debug("Heartbeat succeeded")
            return True
