import asyncio
import logging
import struct
import typing as t

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.pdu import ModbusRequest, ModbusResponse

RECONNECT_DELAY = 1000  # in milliseconds
WAIT_ON_CONNECT = 1500  # in milliseconds

LOGGER = logging.getLogger(__name__)


class AsyncHuaweiSolarModbusSerialClient(AsyncModbusSerialClient):
    def __init__(self, port, baudrate, timeout: int, **serial_kwargs):
        super().__init__(port, **serial_kwargs, baudrate=baudrate, reconnect_delay=RECONNECT_DELAY, timeout=timeout)
        self.register(PrivateHuaweiModbusResponse)


class AsyncHuaweiSolarModbusTcpClient(AsyncModbusTcpClient):
    connected_event = asyncio.Event()

    def __init__(self, host, port, timeout) -> AsyncModbusTcpClient:
        super().__init__(host, port, timeout=timeout, reconnect_delay=RECONNECT_DELAY)
        self.register(PrivateHuaweiModbusResponse)

    def client_made_connection(self, protocol):
        super().client_made_connection(protocol)

        async def _made_connection_task():
            LOGGER.debug("Waiting for %d milliseconds after connection before performing operations", WAIT_ON_CONNECT)
            await asyncio.sleep(WAIT_ON_CONNECT / 1000)
            self.connected_event.set()

        asyncio.create_task(_made_connection_task())

    def client_lost_connection(self, protocol):
        super().client_lost_connection(protocol)
        self.connected_event.clear()


class PrivateHuaweiModbusResponse(ModbusResponse):
    """Response with the private Huawei Solar function code"""

    function_code = 0x41
    _rtu_byte_count_pos = 3

    def __init__(self, **kwargs):
        ModbusResponse.__init__(self, **kwargs)

        self.sub_command = None
        self.content = b""

    def decode(self, data):
        self.sub_command = int(data[0])
        self.content = data[1:]

    def __str__(self):
        return f"{self.__class__.__name__}({self.sub_command})"


class PrivateHuaweiModbusRequest(ModbusRequest):
    """Request with the private Huawei Solar function code"""

    function_code = 0x41
    _rtu_byte_count_pos = 3

    def __init__(self, sub_command, content: bytes, **kwargs):
        ModbusRequest.__init__(self, **kwargs)
        self.sub_command = sub_command
        self.content = content

    def encode(self):
        return bytes([self.sub_command, *self.content])

    def decode(self, data):
        self.sub_command = int(data[0])
        self.content = data[1:]

    def __str__(self):
        return f"{self.__class__.__name__}({self.sub_command})"


class StartUploadModbusRequest(ModbusRequest):
    """
    Modbus file upload request
    """

    function_code = 0x41
    sub_function_code = 0x05

    def __init__(self, file_type, customized_data: t.Optional[bytes] = None, **kwargs):
        ModbusRequest.__init__(self, **kwargs)
        self.file_type = file_type

        if customized_data is None:
            self.customised_data = b""
        else:
            self.customised_data = customized_data

    def encode(self):
        data_length = 1 + len(self.customised_data)
        return struct.pack(">BBB", self.sub_function_code, data_length, self.file_type) + self.customised_data

    def decode(self, data):
        sub_function_code, data_length, self.file_type = struct.unpack(">BBB", data)
        self.customised_data = data[3:]

        assert sub_function_code == self.sub_function_code
        assert len(self.customised_data) == data_length - 1


class StartUploadModbusResponse(ModbusResponse):  # pylint: disable=too-few-public-methods
    """
    Modbus Response to a file upload request
    """

    function_code = 0x41
    sub_function_code = 0x05

    def __init__(self, data):
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
    """
    Modbus Request for (a part of) a file
    """

    function_code = 0x41
    sub_function_code = 0x06

    def __init__(self, file_type, frame_no, **kwargs):
        ModbusRequest.__init__(self, **kwargs)
        self.file_type = file_type
        self.frame_no = frame_no

    def encode(self):
        data_length = 3
        return struct.pack(">BBBH", self.sub_function_code, data_length, self.file_type, self.frame_no)

    def decode(self, data):
        sub_function_code, data_length, self.file_type, self.frame_no = struct.unpack(">BBBH", data)

        assert sub_function_code == self.sub_function_code
        assert data_length == 3


class UploadModbusResponse(ModbusResponse):  # pylint: disable=too-few-public-methods
    """
    Modbus Response with (a part of) a file
    """

    function_code = 0x41
    sub_function_code = 0x06

    def __init__(self, data):
        ModbusResponse.__init__(self)

        (
            data_length,
            self.file_type,
            self.frame_no,
        ) = struct.unpack_from(">BBH", data, 0)
        self.frame_data = data[4:]

        assert len(self.frame_data) == data_length - 3


class CompleteUploadModbusRequest(ModbusRequest):
    """
    Modbus Request to complete a file upload
    """

    function_code = 0x41
    sub_function_code = 0x0C

    def __init__(self, file_type, **kwargs):
        ModbusRequest.__init__(self, **kwargs)
        self.file_type = file_type

    def encode(self):
        data_length = 1
        return struct.pack(">BBB", self.sub_function_code, data_length, self.file_type)

    def decode(self, data):
        sub_function_code, data_length, self.file_type = struct.unpack(">BBB", data)

        assert sub_function_code == self.sub_function_code
        assert data_length == 1


class CompleteUploadModbusResponse(ModbusResponse):  # pylint: disable=too-few-public-methods
    """
    Modbus Response when a file upload has been completed
    """

    function_code = 0x41
    sub_function_code = 0x0C

    def __init__(self, data):
        ModbusResponse.__init__(self)
        (
            data_length,
            self.file_type,
            self.file_crc,
        ) = struct.unpack_from(">BBH", data, 0)

        assert data_length == 3
