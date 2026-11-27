"""Review probes for the alarm-file branch: each test pins down one behaviour found in review.

Tests named `test_probe_*` document current behaviour that differs from FusionSolar or is risky; they pass on the
current code and would need to be flipped when the corresponding finding is fixed. Fixed findings have been turned
into normal tests that assert the fixed behaviour.
"""

import asyncio
import struct
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from huawei_solar.exceptions import FileNotReadyError, ReadException
from huawei_solar.files import _decode_reason
from huawei_solar.modbus_client import AsyncHuaweiSolarClient
from huawei_solar.modbus_pdu import CompleteUploadPDU, StartFileUploadPDU, UploadFileFramePDU
from tmodbus.exceptions import IllegalDataAddressError, ServerDeviceFailureError
from tmodbus.pdu.base import RT, BaseClientPDU
from tmodbus.pdu.holding_registers import RawReadHoldingRegistersPDU
from tmodbus.transport.async_base import AsyncBaseTransport
from tmodbus.utils.crc import calculate_crc16

from huawei_solar import register_names as rn
from huawei_solar.device import EMMADevice, SUN2000Device
from huawei_solar.register_definitions import Result

FILE_TYPE = 0xA1


def _start(file_length: int, frame_length: int, custom: bytes = b"") -> bytes:
    return struct.pack(">BBBBLB", 0x41, 0x05, 6 + len(custom), FILE_TYPE, file_length, frame_length) + custom


def _device_crc(data: bytes) -> int:
    crc = int.from_bytes(calculate_crc16(data))
    return ((crc << 8) & 0xFF00) | ((crc >> 8) & 0x00FF)


class _Transport(AsyncBaseTransport):
    def __init__(
        self,
        starts: list[bytes],
        data: bytes = b"",
        served_frame: int = 0,
        end_crc: int | None = None,
        end_error: Exception | None = None,
    ) -> None:
        self.starts = list(starts)
        self.data = data
        self.served_frame = served_frame
        self.end_crc = end_crc
        self.end_error = end_error
        self.frames: list[int] = []

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def is_open(self) -> bool:
        return True

    async def send_and_receive(self, unit_id: int, pdu: BaseClientPDU[RT]) -> RT:  # noqa: ARG002
        if isinstance(pdu, RawReadHoldingRegistersPDU):
            raise IllegalDataAddressError(0x03)  # no register reads here (e.g. the EMMA's time registers)
        if isinstance(pdu, StartFileUploadPDU):
            return pdu.decode_response(self.starts.pop(0))  # type: ignore[return-value]
        if isinstance(pdu, UploadFileFramePDU):
            self.frames.append(pdu.frame_no)
            chunk = self.data[pdu.frame_no * self.served_frame : (pdu.frame_no + 1) * self.served_frame]
            return pdu.decode_response(  # type: ignore[return-value]
                struct.pack(">BBBBH", 0x41, 0x06, 3 + len(chunk), FILE_TYPE, pdu.frame_no) + chunk
            )
        if isinstance(pdu, CompleteUploadPDU):
            if self.end_error is not None:
                raise self.end_error
            crc = _device_crc(self.data) if self.end_crc is None else self.end_crc
            return pdu.decode_response(struct.pack(">BBBBH", 0x41, 0x0C, 3, FILE_TYPE, crc))  # type: ignore[return-value]
        raise AssertionError(pdu)


async def test_prepare_sleeps_do_not_hold_the_shared_update_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 3 s "preparing" waits happen without the EMMA tree's update_lock, so other polling goes on."""
    lock_held_during_sleep: list[bool] = []
    preparing = b"\x00\x00\x00\x00" + bytes((0x62, 0x01, 10))
    retries = 3
    transport = _Transport([_start(0, 0, preparing)] * (retries + 1))
    emma = EMMADevice(client=AsyncHuaweiSolarClient(transport=transport, unit_id=0), model_name="SmartHEMS")
    child = SUN2000Device(
        client=AsyncHuaweiSolarClient(transport=transport, unit_id=3), model_name="SUN2000", primary_device=emma
    )

    async def fake_sleep(_delay: float) -> None:
        lock_held_during_sleep.append(child.update_lock.locked())

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(FileNotReadyError):
        await child.get_active_alarms(retries=retries)

    assert lock_held_during_sleep == [False] * retries
    assert transport.starts == []


async def test_frame_length_tlv_bigger_than_served_frames_reads_the_whole_file() -> None:
    """Like FusionSolar, data frames are requested until file_length bytes have been received."""
    data = bytes(range(60))
    custom = b"\x00\x00\x00\x00" + bytes((0x60, 0x02, 0x00, 0x40))  # announces 64-byte frames
    transport = _Transport([_start(len(data), 20, custom)], data=data, served_frame=20)

    assert await AsyncHuaweiSolarClient(transport=transport, unit_id=0).get_file(FILE_TYPE) == data

    assert transport.frames == [0, 1, 2]


async def test_empty_file_crc_is_not_checked() -> None:
    """FusionSolar skips the CRC check of an empty file (uploadFinishResp: mTotalFileLen != 0 && ...)."""
    transport = _Transport([_start(0, 200)], end_crc=0x0000)

    assert await AsyncHuaweiSolarClient(transport=transport, unit_id=0).get_file(FILE_TYPE) == b""


async def test_empty_file_with_error_on_end_frame_is_empty() -> None:
    """FusionSolar treats exception 4/6 on the end frame of an empty file as success with no data."""
    transport = _Transport([_start(0, 200)], end_error=ServerDeviceFailureError(0x41))

    assert await AsyncHuaweiSolarClient(transport=transport, unit_id=0).get_file(FILE_TYPE) == b""


def _java_reason(alarm_id: int, ctrl: int, b18: int, b19: int, *, hems: bool) -> tuple[object, ...]:
    """Port of TopnUtils.analysisControl + AlarmDatabaseHelper.changeToBatteryAlarm with Java integer semantics."""

    def s16(x: int) -> int:
        x &= 0xFFFF
        return x - 0x10000 if x & 0x8000 else x

    def s8(x: int) -> int:
        x &= 0xFF
        return x - 0x100 if x & 0x80 else x

    hi, lo = ((ctrl >> 11), (ctrl >> 10)) if hems else ((ctrl >> 12), (ctrl >> 11))
    topn = location = False
    little, big = s16(b18 | (b19 << 8)), s16((b18 << 8) | b19)
    if hi & 1 == 1 and lo & 1 == 0:
        topn, reason = True, little & 255
    elif hi & 1 != 1 or lo & 1 != 1:
        reason = big & 255
    else:
        location, reason = True, little & 255
    slot = cabinet = None
    if (3000 <= alarm_id <= 3999 and not topn) or location:
        data = s16(b18 | (b19 << 8))
        if location:
            reason, slot, cabinet = data & 63, (data >> 6) & 63, (data >> 12) & 15
        else:
            high, low = s8((data >> 8) & 255), s8(data & 255)
            reason, slot, cabinet = high & 63, ((high & 255) >> 6) | ((low & 15) << 2), (low & 240) >> 4
    return reason, topn, location, slot, cabinet


@pytest.mark.parametrize("alarm_id", [2001, 3021, 3999, 4000])
@pytest.mark.parametrize("hems", [False, True])
def test_reason_decoding_matches_app_exhaustively(alarm_id: int, *, hems: bool) -> None:
    for flags in range(8):
        ctrl = flags << 10 | 0b01
        for b18 in range(0, 256, 7):
            for b19 in range(0, 256, 5):
                got = _decode_reason(alarm_id, ctrl, bytes((b18, b19)), hems_layout=hems)
                assert tuple(got) == _java_reason(alarm_id, ctrl, b18, b19, hems=hems)


def _emma_with_clock(local_time: datetime, system_time: datetime, file_data: bytes) -> EMMADevice:
    """Return an EMMA whose time registers read `local_time` / `system_time` and whose files hold `file_data`."""
    client = AsyncMock(spec=AsyncHuaweiSolarClient)
    client.unit_id = 0
    client.get_file.return_value = file_data

    async def get(name: rn.RegisterName) -> Result[Any]:
        if name == rn.EMMA_LOCAL_TIME:
            return Result(local_time, None)
        if name == rn.EMMA_SYSTEM_TIME:
            return Result(system_time, None)
        raise ReadException(name)

    client.get.side_effect = get
    return EMMADevice(client=client, model_name="SmartHEMS")


async def test_emma_offset_follows_dst_before_alarm_reads() -> None:
    """The EMMA's offset is read again before alarm times are converted, so a DST change since start-up is followed.

    Populated in summer (UTC+3, Europe/Bucharest); a winter record (UTC+2) must not be decoded one hour early.
    """
    winter_wall_clock = datetime(2026, 11, 15, 3, 10, tzinfo=UTC)
    true_utc = datetime(2026, 11, 15, 1, 10, tzinfo=UTC)
    record = struct.pack("<IHHIiH2s", 3, 0, 4006, int(winter_wall_clock.timestamp()), 0, 0x0001, b"\x00\x02")
    emma = _emma_with_clock(winter_wall_clock, true_utc, record)
    emma._utc_offset = timedelta(hours=3)  # found at start-up, in summer

    (alarm,) = await emma.get_active_alarms()

    assert emma._utc_offset == timedelta(hours=2)
    assert alarm.occur_time == true_utc


async def test_device_behind_emma_without_offset_uses_its_own_time_zone() -> None:
    """If the EMMA does not know its UTC offset, an inverter behind it falls back to its own time zone."""
    emma = EMMADevice(client=AsyncMock(spec=AsyncHuaweiSolarClient), model_name="SmartHEMS")
    cast("AsyncMock", emma.client.get).side_effect = ReadException("not supported")
    record = struct.pack("<IHHIiH2s", 3, 3, 2032, 1794712200, 0, 0x0001, b"\x00\x01")
    cast("AsyncMock", emma.client.get_file).return_value = record
    inverter_client = AsyncMock(spec=AsyncHuaweiSolarClient)
    inverter_client.unit_id = 3
    inverter = SUN2000Device(client=inverter_client, model_name="SUN2000", primary_device=emma)
    inverter._time_zone = 120

    (alarm,) = await inverter.get_active_alarms()

    cast("AsyncMock", emma.client.get_file).assert_awaited_once_with(0xA1, bytes.fromhex("e0 02 03 00"))
    assert emma._utc_offset is None
    assert alarm.occur_time == datetime(2026, 11, 15, 1, 10, tzinfo=UTC)


async def test_direct_read_of_emma_uses_emma_flag_layout() -> None:
    """emma.get_active_alarms(direct=True) decodes the EMMA's file with bits 11/10, as the routed read does.

    FusionSolar decodes every file read in an EMMA session with bits 11/10 (AlarmPlatformInfo.isHems, set at
    login: LoginActivity.java:678), so an EMMA TopN record (ctrl 0x0801, reason in the first byte) is TopN.
    """
    record = struct.pack("<IHHIiH2s", 3, 0, 4021, 1794712200, 0, 0x0801, b"\x03\x00")
    data = record
    transport = _Transport([_start(len(data), 200)], data=data, served_frame=200)
    emma = EMMADevice(client=AsyncHuaweiSolarClient(transport=transport, unit_id=0), model_name="SmartHEMS")

    (alarm,) = await emma.get_active_alarms(direct=True)

    assert alarm.topn is True
    assert alarm.reason_id == 3
