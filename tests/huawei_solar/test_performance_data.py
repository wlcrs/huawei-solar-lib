"""Tests for Huawei's paged 0x41/0x36 performance data protocol."""

from asyncio import WriteTransport
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from huawei_solar.exceptions import ConnectionInterruptedException, DecodeError, ReadException
from huawei_solar.files import InverterPerformanceDataFile, PerformanceDataPoint, PerformanceRequestType
from huawei_solar.modbus_client import AsyncHuaweiSolarClient
from huawei_solar.modbus_pdu import PerformanceDataFrame, PerformanceDataPDU, PermissionDeniedError
from tmodbus.exceptions import IllegalDataValueError, ModbusConnectionError, TModbusError
from tmodbus.transport.async_rtu import ModbusRtuProtocol
from tmodbus.utils.crc import calculate_crc16


def _response(frame_index: int, request_type: int, flags: int, payload: bytes = b"") -> bytes:
    return bytes([0x41, 0x36, 3 + len(payload), frame_index, request_type, flags]) + payload


def _segment(start: int, *values: int) -> bytes:
    samples = b"".join(value.to_bytes(4, "big", signed=True) for value in values)
    return start.to_bytes(4, "big") + bytes([len(samples)]) + samples


def test_encode_request() -> None:
    pdu = PerformanceDataPDU(frame_index=3, request_type=6, start_time=0x01020304, end_time=0x90ABCDEF)

    assert pdu.encode_request() == bytes.fromhex("41 36 0A 03 06 01 02 03 04 90 AB CD EF")


@pytest.mark.parametrize(("flags", "more"), [(0xC2, True), (0x42, False)])
def test_decode_response_flags(flags: int, *, more: bool) -> None:
    pdu = PerformanceDataPDU(frame_index=3, request_type=6, start_time=0, end_time=10)
    payload = _segment(0, 1000) + _segment(5, -1000)

    assert pdu.decode_response(_response(3, 6, flags, payload)) == PerformanceDataFrame(3, 6, more, 2, payload)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ("41 36 03 00 06", "header"),
        ("42 36 03 00 06 00", "function code"),
        ("41 37 03 00 06 00", "sub function code"),
        ("41 36 04 00 06 00", "data length"),
        ("41 36 02 00 06 00", "data length"),
        ("41 36 03 01 06 00", "frame index"),
        ("41 36 03 00 07 00", "request type"),
    ],
)
def test_decode_rejects_invalid_response(response: str, message: str) -> None:
    pdu = PerformanceDataPDU(frame_index=0, request_type=6, start_time=0, end_time=1)

    with pytest.raises(ValueError, match=message):
        pdu.decode_response(bytes.fromhex(response))


async def test_rtu_frames_response_with_unit_id_and_crc() -> None:
    pdu = PerformanceDataPDU(frame_index=0, request_type=6, start_time=0, end_time=10)
    protocol = ModbusRtuProtocol(on_connection_lost=MagicMock(), timeout=0.1, interframe_delay=0)
    transport = MagicMock(spec=WriteTransport)
    transport.is_closing.return_value = False
    protocol.connection_made(transport)
    payload = _segment(0, -2500)
    response = b"\x01" + _response(0, 6, 1, payload)
    adu = response + calculate_crc16(response)

    def send_response(_request: bytes) -> None:
        protocol.data_received(adu[:3])
        protocol.data_received(adu[3:7])
        protocol.data_received(adu[7:])

    transport.write.side_effect = send_response

    assert await protocol.send_and_receive(1, pdu) == PerformanceDataFrame(
        0, 6, more=False, segment_count=1, payload=payload
    )


async def test_client_pages_until_final_frame(
    huawei_solar: AsyncHuaweiSolarClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = [_segment(i * 300, i * 1000) for i in range(3)]
    responses = iter(_response(i, 4, 0x81 if i < 2 else 1, payload) for i, payload in enumerate(payloads))

    async def execute(pdu: PerformanceDataPDU) -> PerformanceDataFrame:
        return pdu.decode_response(next(responses))

    mock_execute = AsyncMock(side_effect=execute)
    monkeypatch.setattr(huawei_solar, "execute", mock_execute)

    frames = await huawei_solar.get_performance_data_frames(4, 0, 600)

    assert [frame.payload for frame in frames] == payloads
    assert [args.args[0] for args in mock_execute.await_args_list] == [
        PerformanceDataPDU(i, 4, 0, 600) for i in range(3)
    ]


@pytest.mark.parametrize(("frame_index", "request_type", "message"), [(1, 6, "frame index"), (0, 7, "request type")])
async def test_client_rejects_invalid_echo(
    huawei_solar: AsyncHuaweiSolarClient,
    monkeypatch: pytest.MonkeyPatch,
    frame_index: int,
    request_type: int,
    message: str,
) -> None:
    async def execute(pdu: PerformanceDataPDU) -> PerformanceDataFrame:
        return pdu.decode_response(_response(frame_index, request_type, 0))

    monkeypatch.setattr(huawei_solar, "execute", execute)

    with pytest.raises(DecodeError, match=message):
        await huawei_solar.get_performance_data_frames(6, 0, 1)


async def test_client_rejects_more_after_last_index(
    huawei_solar: AsyncHuaweiSolarClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def execute(pdu: PerformanceDataPDU) -> PerformanceDataFrame:
        return pdu.decode_response(_response(pdu.frame_index, 6, 0x80))

    mock_execute = AsyncMock(side_effect=execute)
    monkeypatch.setattr(huawei_solar, "execute", mock_execute)

    with pytest.raises(DecodeError, match="after frame 255"):
        await huawei_solar.get_performance_data_frames(6, 0, 1)

    assert [args.args[0].frame_index for args in mock_execute.await_args_list] == list(range(256))


@pytest.mark.parametrize(
    ("error", "expected", "exception_code"),
    [
        (IllegalDataValueError(0x41), ReadException, 3),
        (ModbusConnectionError(), ConnectionInterruptedException, None),
        (TModbusError(), ReadException, None),
        (PermissionDeniedError(0x41), PermissionDeniedError, None),
    ],
)
async def test_client_maps_modbus_errors(
    huawei_solar: AsyncHuaweiSolarClient,
    monkeypatch: pytest.MonkeyPatch,
    error: TModbusError,
    expected: type[Exception],
    exception_code: int | None,
) -> None:
    monkeypatch.setattr(huawei_solar, "execute", AsyncMock(side_effect=error))

    with pytest.raises(expected) as exc_info:
        await huawei_solar.get_performance_data_frames(6, 0, 1)

    assert getattr(exc_info.value, "modbus_exception_code", None) == exception_code


def test_parse_multiple_segments_and_signed_battery_power() -> None:
    request_type = PerformanceRequestType.BATTERY_CHARGE_AND_DISCHARGE_POWER
    first = PerformanceDataPDU(0, request_type, 0, 900).decode_response(
        _response(0, request_type, 0x82, _segment(0, -1250, 2000) + _segment(600, -100))
    )
    last = PerformanceDataPDU(1, request_type, 0, 900).decode_response(
        _response(1, request_type, 0x01, _segment(900, 1500))
    )

    points = InverterPerformanceDataFile([first, last], request_type).data_points

    assert points == [
        PerformanceDataPoint(datetime.fromtimestamp(timestamp, tz=UTC), request_type, value)
        for timestamp, value in [(0, -1.25), (300, 2.0), (600, -0.1), (900, 1.5)]
    ]


@pytest.mark.parametrize(
    ("request_type", "cycle", "expected_interval", "expected_value"),
    [
        (PerformanceRequestType.HOUR_POWER, None, 3600, 10.0),
        (PerformanceRequestType.OUTPUT_POWER, None, 300, 1.0),
        (PerformanceRequestType.HOUR_POWER, 900, 900, 10.0),
    ],
)
def test_parse_fixed_interval(
    request_type: PerformanceRequestType,
    cycle: int | None,
    expected_interval: int,
    expected_value: float,
) -> None:
    points = InverterPerformanceDataFile(_segment(0, 0, 1000), request_type, cycle).data_points

    assert points[1] == PerformanceDataPoint(
        datetime.fromtimestamp(expected_interval, tz=UTC), request_type, expected_value
    )


@pytest.mark.parametrize(
    "request_type", [PerformanceRequestType.MONTH_POWER, PerformanceRequestType.ABSORB_MONTH_POWER]
)
def test_parse_months_across_year_boundary(request_type: PerformanceRequestType) -> None:
    start = datetime(2023, 12, 31, 1, tzinfo=UTC)
    points = InverterPerformanceDataFile(_segment(int(start.timestamp()), 0, 0, 0, 0), request_type).data_points

    assert [point.time for point in points] == [
        start,
        datetime(2024, 1, 31, 1, tzinfo=UTC),
        datetime(2024, 2, 29, 1, tzinfo=UTC),
        datetime(2024, 3, 31, 1, tzinfo=UTC),
    ]


@pytest.mark.parametrize("request_type", [PerformanceRequestType.YEAR_POWER, PerformanceRequestType.ABSORB_YEAR_POWER])
def test_parse_years_from_leap_day(request_type: PerformanceRequestType) -> None:
    start = datetime(2024, 2, 29, 1, tzinfo=UTC)
    points = InverterPerformanceDataFile(_segment(int(start.timestamp()), 0, 0, 0, 0, 0), request_type).data_points

    assert [point.time for point in points] == [
        start,
        datetime(2025, 2, 28, 1, tzinfo=UTC),
        datetime(2026, 2, 28, 1, tzinfo=UTC),
        datetime(2027, 2, 28, 1, tzinfo=UTC),
        datetime(2028, 2, 29, 1, tzinfo=UTC),
    ]


@pytest.mark.parametrize(
    ("payload", "segment_count", "message"),
    [
        (b"\x00" * 4, 1, "segment header"),
        (_segment(0, 1, 2)[:-4], 1, "segment length"),
        (b"\x00\x00\x00\x00\x01\x00", 1, "segment length"),
        (_segment(0, 1), 2, "declares 2 segments, found 1"),
        (_segment(0, 1) + b"\x00", 1, "segment header"),
        (_segment(0, 1) + _segment(3600, 2), 1, "declares 1 segments, found 2"),
    ],
)
def test_parse_rejects_malformed_segments(payload: bytes, segment_count: int, message: str) -> None:
    frame = PerformanceDataPDU(0, 0, 0, 1).decode_response(_response(0, 0, segment_count, payload))

    with pytest.raises(DecodeError, match=message):
        InverterPerformanceDataFile([frame])


def test_parse_rejects_frame_of_another_request_type() -> None:
    frame = PerformanceDataFrame(
        0,
        PerformanceRequestType.BATTERY_CHARGE_AND_DISCHARGE_POWER,
        more=False,
        segment_count=1,
        payload=_segment(0, -1250),
    )

    with pytest.raises(DecodeError, match="request type 6, expected 0"):
        InverterPerformanceDataFile([frame], request_type=PerformanceRequestType.HOUR_POWER)


@pytest.mark.parametrize(("request_type", "start", "end"), [(256, 0, 1), (-1, 0, 1), (0, -1, 1), (0, 0, 1 << 32)])
async def test_client_rejects_out_of_range_request(request_type: int, start: int, end: int) -> None:
    client = AsyncHuaweiSolarClient(Mock(), unit_id=3)

    with pytest.raises(ValueError, match="Performance data"):
        await client.get_performance_data_frames(request_type, start, end)
