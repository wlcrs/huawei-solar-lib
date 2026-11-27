"""Tests for the Modbus 0x41 file upload (start / data frames / end) in AsyncHuaweiSolarClient.get_file."""

import struct
from collections.abc import Callable

import pytest
from huawei_solar.exceptions import DecodeError, FileNotReadyError, ReadException
from huawei_solar.modbus_client import AsyncHuaweiSolarClient
from huawei_solar.modbus_pdu import CompleteUploadPDU, StartFileUpload, StartFileUploadPDU, UploadFileFramePDU
from tmodbus.exceptions import IllegalFunctionError, ServerDeviceBusyError, ServerDeviceFailureError
from tmodbus.pdu.base import RT, BaseClientPDU
from tmodbus.transport.async_base import AsyncBaseTransport
from tmodbus.utils.crc import calculate_crc16

FILE_TYPE = 0xA1


def start_response(file_length: int, frame_length: int, custom: bytes = b"", file_type: int = FILE_TYPE) -> bytes:
    """Encode a start response PDU (without the unit id)."""
    return struct.pack(">BBBBLB", 0x41, 0x05, 6 + len(custom), file_type, file_length, frame_length) + custom


def frame_response(frame_no: int, data: bytes, file_type: int = FILE_TYPE) -> bytes:
    return struct.pack(">BBBBH", 0x41, 0x06, 3 + len(data), file_type, frame_no) + data


def end_response(file_data: bytes, file_type: int = FILE_TYPE) -> bytes:
    crc = int.from_bytes(calculate_crc16(file_data))
    device_crc = ((crc << 8) & 0xFF00) | ((crc >> 8) & 0x00FF)
    return struct.pack(">BBBBH", 0x41, 0x0C, 3, file_type, device_crc)


def preparing(progress: int) -> bytes:
    """Customised data of a "still preparing" start response: 4 reserved bytes, then TLV 0x62."""
    return b"\x00\x00\x00\x00" + bytes((0x62, 0x01, progress))


class ScriptedFileTransport(AsyncBaseTransport):
    """Answer the file upload PDUs from a script and record what was sent."""

    def __init__(
        self,
        starts: list[bytes | Exception],
        file_data: bytes = b"",
        frame_length: int = 0,
        *,
        frame_answer: Callable[[int], bytes | Exception] | None = None,
        end_answer: bytes | Exception | None = None,
    ) -> None:
        """Answer the start frames with `starts` in turn, and serve `file_data` in frames of `frame_length`.

        `frame_answer` and `end_answer` replace the generated data frame and end frame answers.
        """
        self.starts = list(starts)
        self.file_data = file_data
        self.frame_length = frame_length
        self.frame_answer = frame_answer
        self.end_answer = end_answer
        self.requests: list[tuple[int, BaseClientPDU[object]]] = []

    async def open(self) -> None:
        """Open nothing."""

    async def close(self) -> None:
        """Close nothing."""

    def is_open(self) -> bool:
        """Report the transport as open."""
        return True

    async def send_and_receive(self, unit_id: int, pdu: BaseClientPDU[RT]) -> RT:
        """Record the request and answer it from the script."""
        self.requests.append((unit_id, pdu))
        if isinstance(pdu, StartFileUploadPDU):
            answer = self.starts.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return pdu.decode_response(answer)  # type: ignore[return-value]
        if isinstance(pdu, UploadFileFramePDU):
            offset = pdu.frame_no * self.frame_length
            frame: bytes | Exception = frame_response(pdu.frame_no, self.file_data[offset : offset + self.frame_length])
            if self.frame_answer is not None:
                frame = self.frame_answer(pdu.frame_no)
            if isinstance(frame, Exception):
                raise frame
            return pdu.decode_response(frame)  # type: ignore[return-value]
        if isinstance(pdu, CompleteUploadPDU):
            end = end_response(self.file_data) if self.end_answer is None else self.end_answer
            if isinstance(end, Exception):
                raise end
            return pdu.decode_response(end)  # type: ignore[return-value]
        msg = f"Unexpected PDU {pdu!r}"
        raise AssertionError(msg)

    def sent(self, pdu_type: type) -> list[BaseClientPDU[object]]:
        """Return the requests of the given PDU type."""
        return [pdu for _, pdu in self.requests if isinstance(pdu, pdu_type)]


def _client(transport: AsyncBaseTransport, unit_id: int = 0) -> AsyncHuaweiSolarClient:
    return AsyncHuaweiSolarClient(transport=transport, unit_id=unit_id)


async def test_empty_file_is_returned_as_empty() -> None:
    """A start response with length 0 and no TLVs is a real empty file (e.g. no active alarms)."""
    transport = ScriptedFileTransport([start_response(0, 200)])

    assert await _client(transport).get_file(FILE_TYPE, b"\xe0\x02\xff\x00") == b""

    (start,) = transport.sent(StartFileUploadPDU)
    assert isinstance(start, StartFileUploadPDU)
    assert start.encode_request() == bytes.fromhex("41 05 05 a1 e0 02 ff 00")
    assert transport.sent(UploadFileFramePDU) == []
    assert len(transport.sent(CompleteUploadPDU)) == 1


async def test_empty_file_crc_is_not_checked() -> None:
    """FusionSolar does not check the CRC of an empty file (uploadFinishResp)."""
    transport = ScriptedFileTransport([start_response(0, 200)], end_answer=end_response(b"\x01"))

    assert await _client(transport).get_file(FILE_TYPE) == b""


@pytest.mark.parametrize("error", [ServerDeviceFailureError(0x41), ServerDeviceBusyError(0x41)])
async def test_empty_file_accepts_failure_or_busy_on_end_frame(error: Exception) -> None:
    """FusionSolar treats exception 0x04/0x06 on the end frame of an empty file as an empty file."""
    transport = ScriptedFileTransport([start_response(0, 200)], end_answer=error)

    assert await _client(transport).get_file(FILE_TYPE) == b""


async def test_error_on_end_frame_of_non_empty_file_raises() -> None:
    data = bytes(range(10))
    transport = ScriptedFileTransport(
        [start_response(len(data), 20)], file_data=data, frame_length=20, end_answer=ServerDeviceBusyError(0x41)
    )

    with pytest.raises(ReadException) as err:
        await _client(transport).get_file(FILE_TYPE)
    assert err.value.modbus_exception_code == ServerDeviceBusyError.error_code


async def test_other_error_on_end_frame_of_empty_file_raises() -> None:
    transport = ScriptedFileTransport([start_response(0, 200)], end_answer=IllegalFunctionError(0x41))

    with pytest.raises(ReadException):
        await _client(transport).get_file(FILE_TYPE)


async def test_file_read_in_frames() -> None:
    data = bytes(range(50))
    transport = ScriptedFileTransport([start_response(len(data), 20)], file_data=data, frame_length=20)

    assert await _client(transport).get_file(FILE_TYPE) == data
    assert [pdu.frame_no for pdu in transport.sent(UploadFileFramePDU)] == [0, 1, 2]  # type: ignore[attr-defined]


async def test_frames_are_requested_until_all_bytes_arrived() -> None:
    """The frame length announced in the start response does not decide how many frames are read."""
    data = bytes(range(50))
    transport = ScriptedFileTransport([start_response(len(data), 200)], file_data=data, frame_length=20)

    assert await _client(transport).get_file(FILE_TYPE) == data
    assert len(transport.sent(UploadFileFramePDU)) == 3


async def test_bytes_beyond_the_file_length_are_cut_off() -> None:
    data = bytes(range(25))
    padded = data + b"\xee" * 5

    def frame_answer(frame_no: int) -> bytes:
        return frame_response(frame_no, padded[frame_no * 15 : (frame_no + 1) * 15])

    transport = ScriptedFileTransport(
        [start_response(len(data), 15)], file_data=data, frame_length=15, frame_answer=frame_answer
    )

    assert await _client(transport).get_file(FILE_TYPE) == data


async def test_empty_frame_before_the_end_raises_and_closes_the_transfer() -> None:
    def frame_answer(frame_no: int) -> bytes:
        return frame_response(frame_no, b"" if frame_no else bytes(10))

    transport = ScriptedFileTransport([start_response(30, 10)], frame_answer=frame_answer)

    with pytest.raises(DecodeError, match="Empty frame 1"):
        await _client(transport).get_file(FILE_TYPE)
    assert len(transport.sent(CompleteUploadPDU)) == 1


async def test_wrong_frame_number_raises() -> None:
    transport = ScriptedFileTransport([start_response(30, 10)], frame_answer=lambda _: frame_response(5, bytes(10)))

    with pytest.raises(DecodeError, match="received frame 5"):
        await _client(transport).get_file(FILE_TYPE)
    assert len(transport.sent(CompleteUploadPDU)) == 1


async def test_exception_on_data_frame_closes_the_transfer() -> None:
    """Like FusionSolar, a failed data frame is followed by the end frame."""
    transport = ScriptedFileTransport([start_response(30, 10)], frame_answer=lambda _: ServerDeviceBusyError(0x41))

    with pytest.raises(ReadException) as err:
        await _client(transport).get_file(FILE_TYPE)
    assert err.value.modbus_exception_code == ServerDeviceBusyError.error_code
    assert len(transport.sent(CompleteUploadPDU)) == 1


async def test_malformed_frame_is_a_decode_error() -> None:
    transport = ScriptedFileTransport([start_response(30, 10)], frame_answer=lambda _: b"\x41\x06")

    with pytest.raises(DecodeError, match="Invalid response"):
        await _client(transport).get_file(FILE_TYPE)
    assert len(transport.sent(CompleteUploadPDU)) == 1


async def test_malformed_start_response_is_a_decode_error() -> None:
    transport = ScriptedFileTransport([start_response(0, 10)[:-2]])

    with pytest.raises(DecodeError):
        await _client(transport).get_file(FILE_TYPE)


async def test_preparing_reply_raises_at_once() -> None:
    """A "preparing" start response must not be read as an empty file, and get_file does not wait itself."""
    transport = ScriptedFileTransport([start_response(0, 0, preparing(40))])

    with pytest.raises(FileNotReadyError) as err:
        await _client(transport).get_file(FILE_TYPE)

    assert isinstance(err.value, ReadException)
    assert err.value.progress == 40
    assert len(transport.sent(StartFileUploadPDU)) == 1
    # like FusionSolar, no data or end frame follows a "preparing" answer
    assert transport.sent(UploadFileFramePDU) == []
    assert transport.sent(CompleteUploadPDU) == []


async def test_truncated_progress_tlv_is_still_read() -> None:
    """FusionSolar reads the progress byte of TLV 0x62 whatever its length says."""
    transport = ScriptedFileTransport([start_response(0, 0, b"\x00\x00\x00\x00" + bytes((0x62, 0x02, 0x05)))])

    with pytest.raises(FileNotReadyError):
        await _client(transport).get_file(FILE_TYPE)


async def test_progress_100_is_ready() -> None:
    transport = ScriptedFileTransport([start_response(0, 20, preparing(100))])

    assert await _client(transport).get_file(FILE_TYPE) == b""


async def test_frame_length_tlv_overrides_header() -> None:
    data = bytes(range(30))
    custom = b"\x00\x00\x00\x00" + bytes((0x60, 0x02, 0x00, 0x0A))
    transport = ScriptedFileTransport([start_response(len(data), 0, custom)], file_data=data, frame_length=10)

    assert await _client(transport).get_file(FILE_TYPE) == data
    assert len(transport.sent(UploadFileFramePDU)) == 3


async def test_zero_frame_length_with_data_is_rejected() -> None:
    transport = ScriptedFileTransport([start_response(20, 0)])

    with pytest.raises(DecodeError):
        await _client(transport).get_file(FILE_TYPE)


async def test_exception_on_start_is_wrapped() -> None:
    transport = ScriptedFileTransport([IllegalFunctionError(0x41)])

    with pytest.raises(ReadException) as err:
        await _client(transport).get_file(FILE_TYPE)

    assert not isinstance(err.value, FileNotReadyError)
    assert err.value.modbus_exception_code == IllegalFunctionError.error_code


@pytest.mark.parametrize(
    ("custom", "check"),
    [
        (b"", lambda r: r.tlvs == {} and r.prepare_progress is None and not r.is_preparing),
        (b"\x00\x00\x00\x00", lambda r: r.tlvs == {}),
        (preparing(99), lambda r: r.prepare_progress == 99 and r.is_preparing),
        (preparing(100), lambda r: r.prepare_progress == 100 and not r.is_preparing),
        # unknown TLVs are skipped, several TLVs are read
        (
            b"\x00\x00\x00\x00" + bytes((0x70, 0x02, 0xAA, 0xBB, 0x62, 0x01, 0x05, 0x60, 0x01, 0x80)),
            lambda r: (
                r.tlvs == {0x70: b"\xaa\xbb", 0x62: b"\x05", 0x60: b"\x80"}
                and r.is_preparing
                and r.frame_length_override == 0x80
            ),
        ),
        # a truncated TLV keeps the bytes that are there
        (b"\x00\x00\x00\x00" + bytes((0x62, 0x02, 0x05)), lambda r: r.tlvs == {0x62: b"\x05"} and r.is_preparing),
        (b"\x00\x00\x00\x00" + bytes((0x62, 0x01)), lambda r: r.tlvs == {0x62: b""} and not r.is_preparing),
    ],
)
def test_start_response_tlvs(custom: bytes, check: Callable[[StartFileUpload], bool]) -> None:
    response = StartFileUploadPDU(file_type=FILE_TYPE).decode_response(start_response(0, 0, custom))

    assert response.customised_data == custom
    assert check(response)
