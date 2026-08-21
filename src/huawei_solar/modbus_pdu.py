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


from enum import IntEnum


class UserPasswordStatus(IntEnum):
    """Status of user password returned upon login."""

    NORMAL = 0
    INITIAL_PASSWORD_REQUIRED = 1
    PASSWORD_CHANGE_REQUIRED = 2


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Result of inverter login."""

    success: bool
    password_status: UserPasswordStatus = UserPasswordStatus.NORMAL


@dataclass(frozen=True)
class LoginPDU(BaseSubFunctionClientPDU[LoginResult]):
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

    def decode_response(self, response: bytes) -> LoginResult:
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
            return LoginResult(success=False, password_status=UserPasswordStatus.NORMAL)

        inverter_mac_response = response[
            response_header_struct.size : response_header_struct.size + inverter_mac_response_length
        ]

        if _compute_digest(self.password.encode("utf-8"), self.client_challenge) != inverter_mac_response:
            msg = "Inverter response contains an invalid challenge answer. This could indicate a MitM-attack!"
            raise ValueError(msg)

        password_status_offset = response_header_struct.size + inverter_mac_response_length
        if len(response) >= password_status_offset + 2:
            (raw_status,) = struct.unpack_from(">H", response, password_status_offset)
            password_status = (
                UserPasswordStatus(raw_status) if raw_status in (0, 1, 2) else UserPasswordStatus.NORMAL
            )
        else:
            password_status = UserPasswordStatus.NORMAL

        return LoginResult(success=True, password_status=password_status)


register_pdu_class(LoginPDU)


@dataclass(frozen=True)
class SetPasswordPDU(BaseSubFunctionClientPDU[bool]):
    """Set or modify password PDU (Sub-function 0x26)."""

    function_code = 0x41
    sub_function_code = 0x26
    rtu_byte_count_pos = 3

    username: str
    new_password: str
    old_password: str = ""

    def encode_request(self) -> bytes:
        """Encode set/modify password request."""
        encoded_username = self.username.encode("utf-8")
        encoded_old_password = self.old_password.encode("utf-8")
        encoded_new_password = self.new_password.encode("utf-8")

        # Mode 2 is direct password initialization/modification
        mode = 2
        total_length = (
            len(encoded_old_password)
            + 2
            + len(encoded_new_password)
            + 1
            + len(encoded_new_password)
            + 2
            + len(encoded_username)
            + 1
        )

        return bytes(
            [
                self.function_code,
                self.sub_function_code,
                total_length,
                len(encoded_old_password),
                *encoded_old_password,
                len(encoded_new_password),
                *encoded_new_password,
                len(encoded_new_password),
                *encoded_new_password,
                mode,
                len(encoded_username),
                *encoded_username,
                0,
            ],
        )

    def decode_response(self, response: bytes) -> bool:
        """Decode SetPassword response."""
        response_header_struct = struct.Struct(">BBB")
        (function_code, sub_function_code, _content_length) = response_header_struct.unpack_from(response, 0)

        if function_code != self.function_code:
            msg = f"Invalid function code: expected {self.function_code:02x}, received {function_code:02x}"
            raise ValueError(msg)

        if sub_function_code != self.sub_function_code:
            msg = (
                f"Unexpected sub function code: expected {self.sub_function_code:02x}, received {sub_function_code:02x}"
            )
            raise ValueError(msg)

        result_offset = response_header_struct.size
        if len(response) > result_offset + 1:
            result_code = response[result_offset + 1]
        elif len(response) > result_offset:
            result_code = response[result_offset]
        else:
            return False

        return result_code == 0


register_pdu_class(SetPasswordPDU)


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


class PermissionDeniedError(ModbusResponseError):
    """Permission Denied exception.

    Raised when the device returns a permission denied error.
    """

    error_code = 0x80


register_custom_exception(PermissionDeniedError)
