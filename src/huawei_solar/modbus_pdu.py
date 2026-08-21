"""Custom PDU classes for tmodbus."""

import hmac
import logging
import secrets
import struct
from dataclasses import dataclass, field
from hashlib import sha256

from tmodbus.exceptions import ModbusResponseError, register_custom_exception
from tmodbus.pdu import BaseSubFunctionClientPDU, register_pdu_class

RECONNECT_DELAY = 1000  # in milliseconds
WAIT_ON_CONNECT = 1500  # in milliseconds

_LOGGER = logging.getLogger(__name__)


# Register custom Huawei Modbus PDUs
@dataclass(frozen=True)
class LoginRequestChallengePDU(BaseSubFunctionClientPDU[bytes]):
    """Modbus PDU to request a login challenge."""

    function_code = 0x41
    sub_function_code = 0x24
    rtu_byte_count_pos = 3

    def encode_request(self) -> bytes:
        """Encode LoginRequestChallengePDU."""
        data_length = 1
        value = 0
        return struct.pack(">BBBB", self.function_code, self.sub_function_code, data_length, value)

    def decode_response(self, response: bytes) -> bytes:
        """Decode LoginRequestChallengePDU response."""
        response_header_struct = struct.Struct(">BBB")
        (function_code, sub_function_code, response_content_length) = response_header_struct.unpack_from(response, 0)

        if function_code != self.function_code:
            msg = f"Invalid function code: expected {self.function_code:02x}, received {function_code:02x}"
            raise ValueError(msg)

        if sub_function_code != self.sub_function_code:
            msg = (
                f"Unexpected sub function code: expected {self.sub_function_code:02x}, received {sub_function_code:02x}"
            )
            raise ValueError(msg)

        expected_response_content_length = 17
        if expected_response_content_length != response_content_length:
            msg = (
                f"Invalid response content length length: expected {expected_response_content_length}, "
                f"received {response_content_length}"
            )
            raise ValueError(msg)

        inverter_challenge_length = 16
        return response[response_header_struct.size : response_header_struct.size + inverter_challenge_length]


register_pdu_class(LoginRequestChallengePDU)


def _compute_digest(password: bytes, seed: bytes) -> bytes:
    hashed_password = sha256(password).digest()

    return hmac.digest(key=hashed_password, msg=seed, digest=sha256)


@dataclass(frozen=True)
class LoginPDU(BaseSubFunctionClientPDU[bool]):
    """Login PDU."""

    function_code = 0x41
    sub_function_code = 0x25
    rtu_byte_count_pos = 3

    username: str
    password: str
    inverter_challenge: bytes

    client_challenge: bytes = field(default_factory=lambda: secrets.token_bytes(16))

    def encode_request(self) -> bytes:
        """Encode the login request."""
        encoded_username = self.username.encode("utf-8")
        hashed_password = _compute_digest(
            self.password.encode("utf-8"),
            self.inverter_challenge,
        )

        total_length = len(self.client_challenge) + 1 + len(encoded_username) + 1 + len(hashed_password)

        return bytes(
            [
                self.function_code,
                self.sub_function_code,
                total_length,
                *self.client_challenge,
                len(encoded_username),
                *encoded_username,
                len(hashed_password),
                *hashed_password,
            ],
        )

    def decode_response(self, response: bytes) -> bool:
        """Decode LoginPDU response and check the returned MAC."""
        response_header_struct = struct.Struct(">BBB?B")
        (
            function_code,
            sub_function_code,
            _response_content_length,
            failure,
            inverter_mac_response_length,
        ) = response_header_struct.unpack_from(response, 0)

        if function_code != self.function_code:
            msg = f"Invalid function code: expected {self.function_code:02x}, received {function_code:02x}"
            raise ValueError(msg)

        if sub_function_code != self.sub_function_code:
            msg = f"Invalid sub function code: expected {self.sub_function_code:02x}, received {sub_function_code:02x}"
            raise ValueError(msg)

        if failure:
            return False

        inverter_mac_response = response[
            response_header_struct.size : response_header_struct.size + inverter_mac_response_length
        ]

        if _compute_digest(self.password.encode("utf-8"), self.client_challenge) != inverter_mac_response:
            msg = "Inverter response contains an invalid challenge answer. This could indicate a MitM-attack!"
            raise ValueError(msg)

        return True


register_pdu_class(LoginPDU)


@dataclass(frozen=True, slots=True)
class StartFileUpload:
    """Contents of StartFileUpload response."""

    file_length: int
    data_frame_length: int
    customised_data: bytes


@dataclass(frozen=True)
class StartFileUploadPDU(BaseSubFunctionClientPDU[StartFileUpload]):
    """Modbus file upload request."""

    function_code = 0x41
    sub_function_code = 0x05

    file_type: int
    customised_data: bytes = field(default_factory=bytes)

    def encode_request(self) -> bytes:
        """Encode request."""
        data_length = 1 + len(self.customised_data)
        return (
            struct.pack(">BBBB", self.function_code, self.sub_function_code, data_length, self.file_type)
            + self.customised_data
        )

    def decode_response(self, response: bytes) -> StartFileUpload:
        """Decode response."""
        response_header_struct = struct.Struct(">BBBBLB")
        (
            function_code,
            sub_function_code,
            data_length,
            file_type,
            file_length,
            data_frame_length,
        ) = response_header_struct.unpack_from(response, 0)

        if function_code != self.function_code:
            msg = f"Invalid function code: expected {self.function_code:02x}, received {function_code:02x}"
            raise ValueError(msg)

        if sub_function_code != self.sub_function_code:
            msg = f"Invalid sub function code: expected {self.sub_function_code:02x}, received {sub_function_code:02x}"
            raise ValueError(msg)

        customised_data = response[response_header_struct.size :]
        expected_data_length = struct.calcsize(">BLB") + len(customised_data)

        if data_length != expected_data_length:
            msg = f"Invalid data length: expected {expected_data_length}, received {data_length}"
            raise ValueError(msg)

        if file_type != self.file_type:
            msg = f"Invalid file type: expected {self.file_type:02x}, received {file_type:02x}"
            raise ValueError(msg)

        return StartFileUpload(
            file_length=file_length,
            data_frame_length=data_frame_length,
            customised_data=customised_data,
        )


register_pdu_class(StartFileUploadPDU)


@dataclass(frozen=True, slots=True)
class UploadFileFrame:
    """Represents a frame of file data."""

    frame_no: int
    frame_data: bytes


@dataclass(frozen=True)
class UploadFileFramePDU(BaseSubFunctionClientPDU[UploadFileFrame]):
    """Modbus Request for (a part of) a file."""

    function_code = 0x41
    rtu_byte_count_pos = 3

    sub_function_code = 0x06

    file_type: int
    frame_no: int

    def encode_request(self) -> bytes:
        """Encode UploadFileFramePDU."""
        data_length = 3
        return struct.pack(
            ">BBBBH",
            self.function_code,
            self.sub_function_code,
            data_length,
            self.file_type,
            self.frame_no,
        )

    def decode_response(self, response: bytes) -> UploadFileFrame:
        """Decode UploadPDU response."""
        response_header_struct = struct.Struct(">BBBBH")
        (
            function_code,
            sub_function_code,
            data_length,
            file_type,
            frame_no,
        ) = response_header_struct.unpack_from(response, 0)

        frame_data = response[response_header_struct.size :]

        if function_code != self.function_code:
            msg = f"Invalid function code: expected {self.function_code:02x}, received {function_code:02x}"
            raise ValueError(msg)

        if sub_function_code != self.sub_function_code:
            msg = f"Invalid sub function code: expected {self.sub_function_code:02x}, received {sub_function_code:02x}"
            raise ValueError(msg)

        expected_data_length = struct.calcsize(">BH") + len(frame_data)
        if data_length != expected_data_length:
            msg = f"Invalid data length: expected {expected_data_length}, received {data_length}"
            raise ValueError(msg)

        if file_type != self.file_type:
            msg = f"Invalid file type: expected {self.file_type:02x}, received {file_type:02x}"
            raise ValueError(msg)

        return UploadFileFrame(frame_no=frame_no, frame_data=frame_data)


register_pdu_class(UploadFileFramePDU)


@dataclass(frozen=True)
class CompleteUploadPDU(BaseSubFunctionClientPDU[int]):
    """Modbus Request to complete a file upload.

    Returns the file CRC value.
    """

    function_code = 0x41
    rtu_byte_count_pos = 3

    sub_function_code = 0x0C

    file_type: int

    def encode_request(self) -> bytes:
        """Encode CompleteUploadModbusRequest."""
        data_length = 1
        return struct.pack(">BBBB", self.function_code, self.sub_function_code, data_length, self.file_type)

    def decode_response(self, response: bytes) -> int:
        """Decode CompleteUploadModbusResponse."""
        file_crc: int
        function_code, sub_function_code, data_length, file_type, file_crc = struct.unpack(">BBBBH", response)

        if function_code != self.function_code:
            msg = f"Invalid function code: expected {self.function_code:02x}, received {function_code:02x}"
            raise ValueError(msg)

        if sub_function_code != self.sub_function_code:
            msg = f"Invalid sub function code: expected {self.sub_function_code:02x}, received {sub_function_code:02x}"
            raise ValueError(msg)

        expected_data_length = 3
        if data_length != expected_data_length:
            msg = f"Invalid data length: expected {expected_data_length}, received {data_length}"
            raise ValueError(msg)

        if file_type != self.file_type:
            msg = f"Invalid file type: expected {self.file_type:02x}, received {file_type:02x}"
            raise ValueError(msg)

        return file_crc


register_pdu_class(CompleteUploadPDU)


@dataclass(frozen=True)
class MultiRegisterReadPDU(BaseSubFunctionClientPDU[dict[int, bytes]]):
    """Modbus PDU to read multiple scattered registers (0x41 0x33).

    Standard Modbus Function Code 0x03 (Read Holding Registers) requires querying
    a single contiguous span of memory addresses. In contrast, Huawei's proprietary
    Function Code 0x41 (Sub-function 0x33) allows querying arbitrary, non-contiguous
    registers across disjoint memory spaces (e.g. 30000, 32000, 37000, 40000) in a
    single request-response roundtrip.

    Args:
        registers: A list of ``(register_address, register_length_in_words)`` tuples
            to read, where each register word corresponds to 16 bits (2 bytes).
        frame_no: Optional sequence frame number byte (0-255, default 0).

    Returns:
        A dictionary mapping each ``register_address`` (int) to its raw payload
        bytes (``bytes``, with length ``register_length_in_words * 2``).

    Limitations & Device Quirks:
        - **PDU Payload Capacity**: The request takes ``3 * N + 2`` bytes and the
          response takes ``sum(3 + 2 * len_i) + 2`` bytes. To stay within the Modbus
          PDU limit (~253 bytes), large batches must be segmented (typically <= 35-40
          registers depending on word lengths).
        - **64-byte Hardware Boundary Quirk**: On serial / USB OTG / Bluetooth SPP
          links, certain older Huawei inverter firmware revisions have a USB bulk
          endpoint bug where responses with a total length that is an exact multiple
          of 64 bytes may cause the hardware receive buffer to stall waiting for a
          short packet.
        - **Gateway & Firmware Compatibility**: Some third-party Modbus proxies or
          legacy firmware revisions do not implement function code 0x41 and will
          return Modbus Exception 0x01 (Illegal Function) or 0x83 / 0x80. Standard
          Modbus FC 0x03 reading should be used as fallback in such environments.

    """

    function_code = 0x41
    sub_function_code = 0x33
    rtu_byte_count_pos = 3

    registers: list[tuple[int, int]]  # (register_address, register_length_in_words)
    frame_no: int = 0

    def encode_request(self) -> bytes:
        """Encode MultiRegisterReadPDU request."""
        data_length = len(self.registers) * 3 + 2
        payload = [
            self.function_code,
            self.sub_function_code,
            data_length,
            self.frame_no & 0xFF,
            len(self.registers) & 0xFF,
        ]
        for reg_addr, reg_len in self.registers:
            payload.extend(struct.pack(">HB", reg_addr, reg_len))
        return bytes(payload)

    def decode_response(self, response: bytes) -> dict[int, bytes]:
        """Decode MultiRegisterReadPDU response."""
        response_header_struct = struct.Struct(">BBBBB")
        (
            function_code,
            sub_function_code,
            data_length,
            _frame_no,
            register_count,
        ) = response_header_struct.unpack_from(response, 0)

        if function_code != self.function_code:
            msg = f"Invalid function code: expected {self.function_code:02x}, received {function_code:02x}"
            raise ValueError(msg)

        if sub_function_code != self.sub_function_code:
            msg = (
                f"Invalid sub function code: expected {self.sub_function_code:02x}, received {sub_function_code:02x}"
            )
            raise ValueError(msg)

        expected_data_len = len(response) - 3
        if data_length != expected_data_len:
            msg = f"Invalid data length: expected {expected_data_len}, received {data_length}"
            raise ValueError(msg)

        offset = response_header_struct.size
        results: dict[int, bytes] = {}
        for _ in range(register_count):
            if offset + 3 > len(response):
                msg = "Malformed response: unexpected end of data while reading register header"
                raise ValueError(msg)
            reg_addr, reg_len = struct.unpack_from(">HB", response, offset)
            offset += 3
            data_bytes_len = reg_len * 2
            if offset + data_bytes_len > len(response):
                msg = "Malformed response: unexpected end of data while reading register value"
                raise ValueError(msg)
            reg_data = response[offset : offset + data_bytes_len]
            offset += data_bytes_len
            results[reg_addr] = reg_data

        return results


register_pdu_class(MultiRegisterReadPDU)


@dataclass(frozen=True)
class MultiDeviceRegisterReadPDU(BaseSubFunctionClientPDU[dict[tuple[int, int], bytes]]):
    """Modbus PDU to read registers across multiple devices (0x41 0x37).

    Standard Modbus directs every request to a single Slave/Unit ID. Huawei's
    proprietary Function Code 0x41 (Sub-function 0x37) allows querying registers
    across multiple cascaded slave devices (inverters, meters, batteries, sensors)
    in a single frame.

    Args:
        items: A list of ``(unit_id, register_address, register_length_in_words)``
            tuples specifying which device and register address to query.
        frame_no: Optional sequence frame number byte (0-255, default 0).

    Returns:
        A dictionary mapping ``(unit_id, register_address)`` tuples to raw data
        bytes (``bytes``, with length ``register_length_in_words * 2``).

    Limitations & Device Quirks:
        - **PDU Payload Capacity**: The request takes ``4 * N + 2`` bytes and the
          response takes ``sum(4 + 2 * len_i) + 2`` bytes. Keep batch sizes within
          ~25-30 items per frame to prevent exceeding the 253-byte Modbus PDU limit.
        - **Gateway Routing**: Only applicable when connected to a master device
          (such as a SmartLogger or SDongle) capable of aggregating and routing
          downstream Modbus RTU requests across RS485 loops.

    """

    function_code = 0x41
    sub_function_code = 0x37
    rtu_byte_count_pos = 3

    items: list[tuple[int, int, int]]  # (unit_id, register_address, register_length_in_words)
    frame_no: int = 0

    def encode_request(self) -> bytes:
        """Encode MultiDeviceRegisterReadPDU request."""
        data_length = len(self.items) * 4 + 2
        payload = [
            self.function_code,
            self.sub_function_code,
            data_length,
            self.frame_no & 0xFF,
            len(self.items) & 0xFF,
        ]
        for unit_id, reg_addr, reg_len in self.items:
            payload.extend(struct.pack(">BHB", unit_id, reg_addr, reg_len))
        return bytes(payload)

    def decode_response(self, response: bytes) -> dict[tuple[int, int], bytes]:
        """Decode MultiDeviceRegisterReadPDU response."""
        response_header_struct = struct.Struct(">BBBBB")
        (
            function_code,
            sub_function_code,
            data_length,
            _frame_no,
            item_count,
        ) = response_header_struct.unpack_from(response, 0)

        if function_code != self.function_code:
            msg = f"Invalid function code: expected {self.function_code:02x}, received {function_code:02x}"
            raise ValueError(msg)

        if sub_function_code != self.sub_function_code:
            msg = (
                f"Invalid sub function code: expected {self.sub_function_code:02x}, received {sub_function_code:02x}"
            )
            raise ValueError(msg)

        expected_data_len = len(response) - 3
        if data_length != expected_data_len:
            msg = f"Invalid data length: expected {expected_data_len}, received {data_length}"
            raise ValueError(msg)

        offset = response_header_struct.size
        results: dict[tuple[int, int], bytes] = {}
        for _ in range(item_count):
            if offset + 4 > len(response):
                msg = "Malformed response: unexpected end of data while reading multi-device header"
                raise ValueError(msg)
            unit_id, reg_addr, reg_len = struct.unpack_from(">BHB", response, offset)
            offset += 4
            data_bytes_len = reg_len * 2
            if offset + data_bytes_len > len(response):
                msg = "Malformed response: unexpected end of data while reading register value"
                raise ValueError(msg)
            reg_data = response[offset : offset + data_bytes_len]
            offset += data_bytes_len
            results[(unit_id, reg_addr)] = reg_data

        return results


register_pdu_class(MultiDeviceRegisterReadPDU)


@dataclass(frozen=True)
class QueryDeviceLogicAddressListPDU(BaseSubFunctionClientPDU[list[int]]):
    """Modbus PDU to query connected device logic address list (0x41 0x38).

    Used during commissioning scans to query all active slave logic addresses
    (Unit IDs) detected on the Modbus communication bus.

    Args:
        value: Parameter byte sent with query (default 0).

    Returns:
        A list of integer unit IDs (slave logic addresses) discovered on the bus.

    Limitations:
        - Commonly sent to broadcast address (Unit ID 0) or the SmartLogger/Dongle
          address (Unit ID 0 / 1 / 16) to discover downstream connected devices.

    """

    function_code = 0x41
    sub_function_code = 0x38
    rtu_byte_count_pos = 3

    value: int = 0

    def encode_request(self) -> bytes:
        """Encode QueryDeviceLogicAddressListPDU request."""
        data_length = 1
        return struct.pack(">BBBB", self.function_code, self.sub_function_code, data_length, self.value)

    def decode_response(self, response: bytes) -> list[int]:
        """Decode QueryDeviceLogicAddressListPDU response."""
        response_header_struct = struct.Struct(">BBBBB")
        (
            function_code,
            sub_function_code,
            data_length,
            _frame_no,
            device_count,
        ) = response_header_struct.unpack_from(response, 0)

        if function_code != self.function_code:
            msg = f"Invalid function code: expected {self.function_code:02x}, received {function_code:02x}"
            raise ValueError(msg)

        if sub_function_code != self.sub_function_code:
            msg = (
                f"Invalid sub function code: expected {self.sub_function_code:02x}, received {sub_function_code:02x}"
            )
            raise ValueError(msg)

        expected_data_len = len(response) - 3
        if data_length != expected_data_len:
            msg = f"Invalid data length: expected {expected_data_len}, received {data_length}"
            raise ValueError(msg)

        device_addresses_bytes = response[response_header_struct.size :]
        if len(device_addresses_bytes) < device_count:
            msg = f"Malformed response: expected {device_count} device addresses, got {len(device_addresses_bytes)}"
            raise ValueError(msg)

        return list(device_addresses_bytes[:device_count])


register_pdu_class(QueryDeviceLogicAddressListPDU)


class PermissionDeniedError(ModbusResponseError):
    """Permission Denied exception.

    Raised when the device returns a permission denied error.
    """

    error_code = 0x80


register_custom_exception(PermissionDeniedError)
