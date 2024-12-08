"""Custom classes for pyModbus."""

import asyncio
import logging
import struct
from typing import TYPE_CHECKING, TypedDict

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient, ModbusBaseClient
from pymodbus.pdu import ExceptionResponse, ModbusPDU

RECONNECT_DELAY = 1000  # in milliseconds
WAIT_ON_CONNECT = 1500  # in milliseconds

LOGGER = logging.getLogger(__name__)
if TYPE_CHECKING:
    _Base = ModbusBaseClient
else:
    _Base = object


class ModbusConnectionMixin(_Base):
    """Mixin that adds support for custom Huawei modbus messages and delays upon reconnect."""

    connected_event = asyncio.Event()

    def __init__(self, *args, **kwargs) -> None:
        """Add support for the custom Huawei modbus messages."""
        super().__init__(*args, **kwargs, trace_connect=self._trace_connect)  # forward all unused arguments
        super().register(PrivateHuaweiModbusResponse)
        super().register(ReadDeviceIdentifierResponse)
        super().register(AbnormalDeviceDescriptionResponse)

    def _trace_connect(self, connected: bool):
        if connected:

            async def _made_connection_task():
                LOGGER.debug(
                    "Waiting for %d milliseconds after connection before performing operations",
                    WAIT_ON_CONNECT,
                )
                await asyncio.sleep(WAIT_ON_CONNECT / 1000)
                self.connected_event.set()

            asyncio.create_task(_made_connection_task())
        else:
            self.connected_event.clear()


class AsyncHuaweiSolarModbusSerialClient(
    ModbusConnectionMixin,
    AsyncModbusSerialClient,
):
    """Custom SerialClient with support for custom Huawei modbus messages."""

    def __init__(self, port, baudrate, timeout: int, **serial_kwargs):
        """Create AsyncHuaweiSolarModbusSerialClient."""
        super().__init__(self, port=port, baudrate=baudrate, timeout=timeout, **serial_kwargs)


class AsyncHuaweiSolarModbusTcpClient(ModbusConnectionMixin, AsyncModbusTcpClient):
    """Custom TcpClient that supports wait after connect and custom Huawei modbus messages."""

    def __init__(self, host, port, timeout):
        """Create AsyncHuaweiSolarModbusTcpClient."""
        super().__init__(host, port=port, timeout=timeout, reconnect_delay=RECONNECT_DELAY)


class PrivateHuaweiModbusResponse(ModbusPDU):
    """Response with the private Huawei Solar function code."""

    function_code = 0x41
    rtu_byte_count_pos = 3

    sub_command: int | None = None
    content: bytes = b""

    def __init__(self, **kwargs):
        """Create PrivateHuaweiModbusResponse."""
        ModbusPDU.__init__(self, **kwargs)

    def decode(self, data) -> None:
        """Decode PrivateHuaweiModbusResponse into subcommand and data."""
        self.sub_command = int(data[0])
        self.content = data[1:]

    def __str__(self):
        """Return string representation including subcommand."""
        return f"{self.__class__.__name__}({self.sub_command})"


class PrivateHuaweiModbusRequest(ModbusPDU):
    """Request with the private Huawei Solar function code."""

    function_code = 0x41
    rtu_byte_count_pos = 3

    def __init__(self, sub_command, content: bytes, **kwargs):
        """Create PrivateHuaweiModbusRequest."""
        ModbusPDU.__init__(self, **kwargs)
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


class StartUploadModbusRequest(ModbusPDU):
    """Modbus file upload request."""

    function_code = 0x41
    sub_function_code = 0x05

    def __init__(self, file_type, customized_data: bytes | None = None, **kwargs):
        """Create StartUploadModbusRequest."""
        ModbusPDU.__init__(self, **kwargs)
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


class StartUploadModbusResponse(ModbusPDU):
    """Modbus Response to a file upload request."""

    function_code = 0x41
    sub_function_code = 0x05

    def __init__(self, data):
        """Create StartUploadModbusResponse."""
        ModbusPDU.__init__(self)

        (
            data_length,
            self.file_type,
            self.file_length,
            self.data_frame_length,
        ) = struct.unpack_from(">BBLB", data, 0)
        self.customised_data = data[7:]

        assert len(self.customised_data) == data_length - 6


class UploadModbusRequest(ModbusPDU):
    """Modbus Request for (a part of) a file."""

    function_code = 0x41
    sub_function_code = 0x06

    def __init__(self, file_type, frame_no, **kwargs):
        """Create UploadModbusRequest."""
        ModbusPDU.__init__(self, **kwargs)
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


class UploadModbusResponse(ModbusPDU):
    """Modbus Response with (a part of) a file."""

    function_code = 0x41
    sub_function_code = 0x06

    def __init__(self, data):
        """Create UploadModbusResponse."""
        ModbusPDU.__init__(self)

        (
            data_length,
            self.file_type,
            self.frame_no,
        ) = struct.unpack_from(">BBH", data, 0)
        self.frame_data = data[4:]

        assert len(self.frame_data) == data_length - 3


class CompleteUploadModbusRequest(ModbusPDU):
    """Modbus Request to complete a file upload."""

    function_code = 0x41
    sub_function_code = 0x0C

    def __init__(self, file_type, **kwargs):
        """Create CompleteUploadModbusRequest."""
        ModbusPDU.__init__(self, **kwargs)
        self.file_type = file_type

    def encode(self):
        """Encode CompleteUploadModbusRequest."""
        data_length = 1
        return struct.pack(">BBB", self.sub_function_code, data_length, self.file_type)

    def decode(self, data):
        """Decode CompleteUploadModbusRequest."""
        sub_function_code, data_length, self.file_type = struct.unpack(">BBB", data)

        assert sub_function_code == self.sub_function_code


class CompleteUploadModbusResponse(ModbusPDU):
    """Modbus Response when a file upload has been completed."""

    function_code = 0x41
    sub_function_code = 0x0C

    def __init__(self, data):
        """Create CompleteUploadModbusResponse."""
        ModbusPDU.__init__(self)
        (
            data_length,
            self.file_type,
            self.file_crc,
        ) = struct.unpack_from(">BBH", data, 0)

        assert data_length == 3  # noqa: PLR2004


class DeviceIdentifiersRequestType(TypedDict):
    """Device identifiers request type."""

    read_dev_id_code: int
    object_id: int


DEVICE_IDENTIFIERS: DeviceIdentifiersRequestType = {
    "read_dev_id_code": 0x01,
    "object_id": 0x00,
}
DEVICE_INFO: DeviceIdentifiersRequestType = {
    "read_dev_id_code": 0x03,
    "object_id": 0x87,
}


class ReadDeviceIdentifierRequest(ModbusPDU):
    """Modbus Request to read a device identifier."""

    function_code = 0x2B

    MEI_type = 0x0E

    def __init__(self, read_dev_id_code, object_id, **kwargs) -> None:
        """Create ReadDeviceIdentifierRequest."""
        ModbusPDU.__init__(self, **kwargs)
        self.read_dev_id_code = read_dev_id_code
        self.object_id = object_id

    def encode(self):
        """Encode CompleteUploadModbusRequest."""
        return struct.pack(">BBB", self.MEI_type, self.read_dev_id_code, self.object_id)

    def decode(self, data):
        """Decode CompleteUploadModbusRequest."""
        MEI_type, self.read_dev_id_code, self.object_id = struct.unpack(">BBB", data)

        assert MEI_type == self.MEI_type


class ReadDeviceIdentifierResponse(ModbusPDU):
    """Modbus Response when a file upload has been completed."""

    function_code = 0x2B

    MEI_type = 0x0E

    device_id_code: int
    consistency_level: int
    more: bool
    next_object_id: int | None

    objects: dict[int, bytes]

    def decode(self, data) -> None:
        """Decode ReadDeviceIdentifierResponse."""
        (
            MEI_type,
            self.device_id_code,
            self.consistency_level,
            self.more,
            self.next_object_id,
            number_of_objects,
        ) = struct.unpack_from(">BBBBBB", data, 0)

        self.objects = {}
        offset = 6
        while offset < len(data):
            obj_id, obj_length = struct.unpack_from(">BB", data, offset)
            offset += 2
            self.objects[obj_id] = data[offset : offset + obj_length]
            offset += obj_length


class AbnormalDeviceDescriptionResponse(ExceptionResponse):
    """The device description definition call returned a response."""

    function_code = 0xAB
