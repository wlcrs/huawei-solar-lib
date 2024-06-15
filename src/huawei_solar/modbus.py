"""Custom classes for pyModbus."""

# pyright: reportIncompatibleMethodOverride=false

import asyncio
import logging
import struct
from typing import TYPE_CHECKING

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.pdu import ModbusRequest, ModbusResponse

RECONNECT_DELAY = 1000  # in milliseconds
WAIT_ON_CONNECT = 1500  # in milliseconds

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    _Base = AsyncModbusSerialClient | AsyncModbusTcpClient
else:
    _Base = object


class ModbusConnectionMixin(_Base):  # type: ignore
    """Mixin that adds support for custom Huawei modbus messages and delays upon reconnect."""

    connected_event = asyncio.Event()

    def __init__(self, *args, **kwargs) -> None:
        """Add support for the custom Huawei modbus messages."""
        super().__init__(*args, **kwargs)
        super().register(PrivateHuaweiModbusResponse)

    def connection_made(self, transport):
        """Register that a connection has been made in an asyncio Event."""
        super().connection_made(transport)

        async def _made_connection_task():
            LOGGER.debug(
                "Waiting for %d milliseconds after connection before performing operations",
                WAIT_ON_CONNECT,
            )
            await asyncio.sleep(WAIT_ON_CONNECT / 1000)
            self.connected_event.set()

        asyncio.create_task(_made_connection_task())

    def connection_lost(self, reason):
        """Register that a connection has been lost in an asyncio Event."""
        super().connection_lost(reason)
        self.connected_event.clear()


class AsyncHuaweiSolarModbusSerialClient(
    ModbusConnectionMixin,
    AsyncModbusSerialClient,
):
    """Custom SerialClient with support for custom Huawei modbus messages."""

    def __init__(self, port, baudrate, timeout: int, **serial_kwargs):
        """Create AsyncHuaweiSolarModbusSerialClient."""
        super().__init__(
            port,
            **serial_kwargs,
            baudrate=baudrate,
            reconnect_delay=RECONNECT_DELAY,
            timeout=timeout,
        )


class AsyncHuaweiSolarModbusTcpClient(ModbusConnectionMixin, AsyncModbusTcpClient):
    """Custom TcpClient that supports wait after connect and custom Huawei modbus messages."""

    def __init__(self, host, port, timeout):
        """Create AsyncHuaweiSolarModbusTcpClient."""
        super().__init__(host, port, timeout=timeout, reconnect_delay=RECONNECT_DELAY)


class PrivateHuaweiModbusResponse(ModbusResponse):
    """Response with the private Huawei Solar function code."""

    function_code = 0x41
    _rtu_byte_count_pos = 3

    sub_command: int | None = None
    content: bytes = b""

    def __init__(self, **kwargs):
        """Create PrivateHuaweiModbusResponse."""
        ModbusResponse.__init__(self, **kwargs)

    def decode(self, data) -> None:
        """Decode PrivateHuaweiModbusResponse into subcommand and data."""
        self.sub_command = int(data[0])
        self.content = data[1:]

    def __str__(self):
        """Return string representation including subcommand."""
        return f"{self.__class__.__name__}({self.sub_command})"


class PrivateHuaweiModbusRequest(ModbusRequest):
    """Request with the private Huawei Solar function code."""

    function_code = 0x41
    _rtu_byte_count_pos = 3

    def __init__(self, sub_command, content: bytes, **kwargs):
        """Create PrivateHuaweiModbusRequest."""
        ModbusRequest.__init__(self, **kwargs)
        self.sub_command = sub_command
        self.content = content

    def encode(self):
        """Encode PrivateHuaweiModbusRequest to bytes."""
        return bytes([self.sub_command, *self.content])

    def decode(self, data) -> None:
        """Decode PrivateHuaweiModbusRequest into subcommand and data."""
        self.sub_command = int(data[0])
        self.content = data[1:]

    def __str__(self):
        """Return string representation including subcommand."""
        return f"{self.__class__.__name__}({self.sub_command})"


class StartUploadModbusRequest(ModbusRequest):
    """Modbus file upload request."""

    function_code = 0x41
    sub_function_code = 0x05

    def __init__(self, file_type, customized_data: bytes | None = None, **kwargs):
        """Create StartUploadModbusRequest."""
        ModbusRequest.__init__(self, **kwargs)
        self.file_type = file_type

        if customized_data is None:
            self.customised_data = b""
        else:
            self.customised_data = customized_data

    def encode(self):
        """Encode request."""
        data_length = 1 + len(self.customised_data)
        return struct.pack(">BBB", self.sub_function_code, data_length, self.file_type) + self.customised_data

    def decode(self, data):
        """Decode request."""
        sub_function_code, data_length, self.file_type = struct.unpack(">BBB", data)
        self.customised_data = data[3:]

        assert sub_function_code == self.sub_function_code
        assert len(self.customised_data) == data_length - 1


class StartUploadModbusResponse(ModbusResponse):
    """Modbus Response to a file upload request."""

    function_code = 0x41
    sub_function_code = 0x05

    def __init__(self, data):
        """Create StartUploadModbusResponse."""
        ModbusResponse.__init__(self)

        (
            data_length,
            self.file_type,
            self.file_length,
            self.data_frame_length,
        ) = struct.unpack_from(">BBLB", data, 0)
        self.customised_data = data[7:]

        assert len(self.customised_data) == data_length - 6


class UploadModbusRequest(ModbusRequest):
    """Modbus Request for (a part of) a file."""

    function_code = 0x41
    sub_function_code = 0x06

    def __init__(self, file_type, frame_no, **kwargs):
        """Create UploadModbusRequest."""
        ModbusRequest.__init__(self, **kwargs)
        self.file_type = file_type
        self.frame_no = frame_no

    def encode(self):
        """Encode UploadModbusRequest."""
        data_length = 3
        return struct.pack(
            ">BBBH",
            self.sub_function_code,
            data_length,
            self.file_type,
            self.frame_no,
        )

    def decode(self, data):
        """Decode UploadModbusRequest."""
        sub_function_code, data_length, self.file_type, self.frame_no = struct.unpack(
            ">BBBH",
            data,
        )

        assert sub_function_code == self.sub_function_code
        assert data_length == 3  # noqa: PLR2004


class UploadModbusResponse(ModbusResponse):
    """Modbus Response with (a part of) a file."""

    function_code = 0x41
    sub_function_code = 0x06

    def __init__(self, data):
        """Create UploadModbusResponse."""
        ModbusResponse.__init__(self)

        (
            data_length,
            self.file_type,
            self.frame_no,
        ) = struct.unpack_from(">BBH", data, 0)
        self.frame_data = data[4:]

        assert len(self.frame_data) == data_length - 3


class CompleteUploadModbusRequest(ModbusRequest):
    """Modbus Request to complete a file upload."""

    function_code = 0x41
    sub_function_code = 0x0C

    def __init__(self, file_type, **kwargs):
        """Create CompleteUploadModbusRequest."""
        ModbusRequest.__init__(self, **kwargs)
        self.file_type = file_type

    def encode(self):
        """Encode CompleteUploadModbusRequest."""
        data_length = 1
        return struct.pack(">BBB", self.sub_function_code, data_length, self.file_type)

    def decode(self, data):
        """Decode CompleteUploadModbusRequest."""
        sub_function_code, data_length, self.file_type = struct.unpack(">BBB", data)

        assert sub_function_code == self.sub_function_code


class CompleteUploadModbusResponse(ModbusResponse):
    """Modbus Response when a file upload has been completed."""

    function_code = 0x41
    sub_function_code = 0x0C

    def __init__(self, data):
        """Create CompleteUploadModbusResponse."""
        ModbusResponse.__init__(self)
        (
            data_length,
            self.file_type,
            self.file_crc,
        ) = struct.unpack_from(">BBH", data, 0)

        assert data_length == 3  # noqa: PLR2004
