"""Tests for which unit and query the alarm files are read with, and for their time base.

FusionSolar reads the active alarms of an EMMA and of the devices behind it through the EMMA (unit 0) with custom
data E0 02 <address> 00, and those of a directly connected inverter on its own unit with 11 04 00000000. History
alarms are always read on the device's own unit: tag 0x24 (little-endian) behind an EMMA or SmartLogger, tag 0x20
(big-endian) otherwise. All file times are device-local wall-clock epochs.
"""

import asyncio
import os
import struct
import time
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock

import pytest
from huawei_solar.exceptions import FileNotReadyError, ReadException
from huawei_solar.files import ActiveAlarmsDataFile, AlarmLevel, HistoryAlarmsDataFile

from huawei_solar import AsyncHuaweiSolarClient
from huawei_solar.device import (
    EMMADevice,
    HuaweiSolarDevice,
    SChargerDevice,
    SmartGuardDevice,
    SmartLoggerDevice,
    SUN2000Device,
)

LOCAL = datetime(2026, 11, 15, 3, 10, tzinfo=UTC)  # device-local wall clock, encoded as if UTC
LOCAL_EPOCH = int(LOCAL.timestamp())

# EMMA 4021, ctrl 0x0801: TopN with reason byte 3 in the EMMA layout, a normal alarm with reason 0 otherwise
TOPN_RECORD = struct.pack(ActiveAlarmsDataFile.RECORD_STRUCT, 3, 6, 4021, LOCAL_EPOCH, -4, 0x0801, b"\x03\x00")
HISTORY_RECORD = struct.pack(
    HistoryAlarmsDataFile.RECORD_STRUCT, 7, 3, 2032, LOCAL_EPOCH, LOCAL_EPOCH + 3600, 0, 0x0001, b"\x00\x01"
)


def _client(unit_id: int, file_data: bytes = b"") -> AsyncMock:
    client = AsyncMock(spec=AsyncHuaweiSolarClient)
    client.unit_id = unit_id
    client.get_file.return_value = file_data
    # register reads (the EMMA's time registers) are not supported unless a test says otherwise
    client.get.side_effect = ReadException("not supported", modbus_exception_code=0x02)
    return client


def _get_file(device: HuaweiSolarDevice) -> AsyncMock:
    return cast("AsyncMock", device.client.get_file)


@pytest.fixture
def emma() -> EMMADevice:
    """Return an EMMA on unit 0 whose local time is UTC+2."""
    device = EMMADevice(client=_client(0, TOPN_RECORD), model_name="SmartHEMS")
    device._utc_offset = timedelta(hours=2)
    return device


@pytest.mark.parametrize(
    ("logical_address", "expected"),
    [(None, "e0 02 ff 00"), (0, "e0 02 ff 00"), (2, "e0 02 02 00"), (3, "e0 02 03 00"), (6, "e0 02 06 00")],
)
def test_query_mounted_active_alarms(logical_address: int | None, expected: str) -> None:
    assert ActiveAlarmsDataFile.query_mounted_active_alarms(logical_address) == bytes.fromhex(expected)


def test_query_active_alarms_is_always_zero() -> None:
    assert ActiveAlarmsDataFile.query_active_alarms() == bytes.fromhex("11 04 00 00 00 00")

    with pytest.warns(FutureWarning, match="equip_id"):
        assert ActiveAlarmsDataFile.query_active_alarms(5) == bytes.fromhex("11 04 00 00 00 00")


def test_history_query_layouts() -> None:
    start, end = 0x01020304, 0x0A0B0C0D
    assert HistoryAlarmsDataFile.query_within_timespan(start, end) == bytes.fromhex(
        "24 0a 04 03 02 01 0d 0c 0b 0a ff 00"
    )
    assert HistoryAlarmsDataFile.query_within_timespan(
        start, end, tag=HistoryAlarmsDataFile.TAG_OCCUR_TIME
    ) == bytes.fromhex("20 09 01 02 03 04 0a 0b 0c 0d ff")
    # SmartLogger V5: big-endian times with tag 0x24
    assert HistoryAlarmsDataFile.query_within_timespan(start, end, big_endian_times=True) == bytes.fromhex(
        "24 0a 01 02 03 04 0a 0b 0c 0d ff 00"
    )


async def test_emma_reads_its_own_active_alarms_with_e0_ff(emma: EMMADevice) -> None:
    alarms = await emma.get_active_alarms()

    _get_file(emma).assert_awaited_once_with(0xA1, bytes.fromhex("e0 02 ff 00"))
    (alarm,) = alarms
    # read through the EMMA: EMMA flag layout, so this record is a TopN alarm with reason 3
    assert alarm.topn is True
    assert alarm.reason_id == 3
    assert alarm.equip_id == 6
    assert alarm.alarm_param == -4
    assert alarm.level is AlarmLevel.MAJOR
    assert alarm.occur_time == datetime(2026, 11, 15, 1, 10, tzinfo=UTC)
    assert not emma.update_lock.locked()


@pytest.mark.parametrize(
    ("device_class", "unit_id"),
    [(SUN2000Device, 3), (SmartGuardDevice, 2), (SChargerDevice, 6)],
)
async def test_device_behind_emma_is_read_through_unit_0(
    emma: EMMADevice,
    device_class: type[HuaweiSolarDevice],
    unit_id: int,
) -> None:
    """The child's alarms come from the EMMA's unit with its address, under the shared lock taken once."""
    child = device_class(client=_client(unit_id), model_name="child", primary_device=emma)

    async def get_file(file_type: int, customized_data: bytes | None = None) -> bytes:
        assert emma.update_lock.locked()
        return TOPN_RECORD

    _get_file(emma).side_effect = get_file

    alarms = await asyncio.wait_for(child.get_active_alarms(), timeout=2)

    _get_file(emma).assert_awaited_once_with(0xA1, bytes([0xE0, 0x02, unit_id, 0x00]))
    _get_file(child).assert_not_awaited()
    (alarm,) = alarms
    assert alarm.topn is True
    assert alarm.reason_id == 3
    # the EMMA's UTC offset, also for devices without time zone information of their own
    assert alarm.occur_time == datetime(2026, 11, 15, 1, 10, tzinfo=UTC)
    assert not emma.update_lock.locked()


async def test_direct_read_of_device_behind_emma(emma: EMMADevice) -> None:
    """direct=True reads the child's own unit with the inverter query and the inverter flag layout."""
    inverter = SUN2000Device(client=_client(3, TOPN_RECORD), model_name="SUN2000-12K-MAP0", primary_device=emma)

    (alarm,) = await inverter.get_active_alarms(direct=True)

    _get_file(inverter).assert_awaited_once_with(0xA1, bytes.fromhex("11 04 00 00 00 00"))
    _get_file(emma).assert_not_awaited()
    assert alarm.topn is False
    assert alarm.reason_id == 0
    assert alarm.occur_time == datetime(2026, 11, 15, 1, 10, tzinfo=UTC)


async def test_direct_read_of_emma_itself(emma: EMMADevice) -> None:
    await emma.get_active_alarms(direct=True)

    _get_file(emma).assert_awaited_once_with(0xA1, bytes.fromhex("11 04 00 00 00 00"))


async def test_standalone_inverter_reads_its_own_unit(sun2000_device: SUN2000Device) -> None:
    read_file = AsyncMock(return_value=TOPN_RECORD)
    sun2000_device.read_file = read_file  # type: ignore[method-assign]
    sun2000_device._time_zone = 120
    sun2000_device._dst = False

    (alarm,) = await sun2000_device.get_active_alarms()

    read_file.assert_awaited_once_with(0xA1, bytes.fromhex("11 04 00 00 00 00"))
    assert alarm.topn is False
    assert alarm.occur_time == datetime(2026, 11, 15, 1, 10, tzinfo=UTC)


async def test_equip_id_is_deprecated_and_ignored(sun2000_device: SUN2000Device) -> None:
    read_file = AsyncMock(return_value=b"")
    sun2000_device.read_file = read_file  # type: ignore[method-assign]

    with pytest.warns(FutureWarning, match="equip_id"):
        assert await sun2000_device.get_active_alarms(3) == []

    read_file.assert_awaited_once_with(0xA1, bytes.fromhex("11 04 00 00 00 00"))


async def test_smartlogger_active_alarms_still_read_on_own_unit() -> None:
    smartlogger = SmartLoggerDevice(client=_client(0), model_name="SmartLogger")

    assert await smartlogger.get_active_alarms() == []

    _get_file(smartlogger).assert_awaited_once_with(0xA1, bytes.fromhex("11 04 00 00 00 00"))


async def test_empty_file_means_no_alarms(emma: EMMADevice) -> None:
    _get_file(emma).return_value = b""

    assert await emma.get_active_alarms() == []


async def test_file_not_ready_is_not_no_alarms(emma: EMMADevice) -> None:
    _get_file(emma).side_effect = FileNotReadyError("still preparing", progress=30)

    with pytest.raises(FileNotReadyError):
        await emma.get_active_alarms(retries=0)
    assert not emma.update_lock.locked()
    _get_file(emma).assert_awaited_once()


async def test_standalone_inverter_history_uses_tag_0x20_and_local_epochs(sun2000_device: SUN2000Device) -> None:
    """A directly connected inverter gets tag 0x20, big-endian, with the window in its local wall-clock time."""
    sun2000_device._time_zone = 120
    sun2000_device._dst = True  # UTC+3
    read_file = AsyncMock(return_value=HISTORY_RECORD)
    sun2000_device.read_file = read_file  # type: ignore[method-assign]

    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 7, 2, 0, 0, tzinfo=UTC)
    (alarm,) = await sun2000_device.get_history_alarms(start, end)

    expected_start = int((start + timedelta(hours=3)).timestamp())
    expected_end = int((end + timedelta(hours=3)).timestamp())
    read_file.assert_awaited_once_with(0xA2, struct.pack(">BBIIb", 0x20, 9, expected_start, expected_end, -1))
    assert alarm.occur_time == LOCAL - timedelta(hours=3)
    assert alarm.recover_time == LOCAL - timedelta(hours=2)


async def test_emma_history_uses_tag_0x24_and_local_epochs(emma: EMMADevice) -> None:
    _get_file(emma).return_value = HISTORY_RECORD
    start = datetime(2026, 11, 15, 0, 0, tzinfo=UTC)
    end = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

    (alarm,) = await emma.get_history_alarms(start, end)

    expected_start = int((start + timedelta(hours=2)).timestamp())
    expected_end = int((end + timedelta(hours=2)).timestamp())
    _get_file(emma).assert_awaited_once_with(
        0xA2, struct.pack("<BBIIbb", 0x24, 10, expected_start, expected_end, -1, 0)
    )
    assert alarm.occur_time == datetime(2026, 11, 15, 1, 10, tzinfo=UTC)
    assert alarm.recover_time == datetime(2026, 11, 15, 2, 10, tzinfo=UTC)


async def test_history_of_device_behind_emma_is_read_on_its_own_unit(emma: EMMADevice) -> None:
    smartguard = SmartGuardDevice(client=_client(2, HISTORY_RECORD), model_name="SmartGuard", primary_device=emma)
    start = datetime(2026, 11, 15, 0, 0, tzinfo=UTC)
    end = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

    (alarm,) = await asyncio.wait_for(smartguard.get_history_alarms(start, end), timeout=2)

    expected_start = int((start + timedelta(hours=2)).timestamp())
    expected_end = int((end + timedelta(hours=2)).timestamp())
    _get_file(smartguard).assert_awaited_once_with(
        0xA2, struct.pack("<BBIIbb", 0x24, 10, expected_start, expected_end, -1, 0)
    )
    _get_file(emma).assert_not_awaited()
    assert alarm.occur_time == datetime(2026, 11, 15, 1, 10, tzinfo=UTC)


async def test_smartlogger_history_keeps_tag_0x24() -> None:
    smartlogger = SmartLoggerDevice(client=_client(0), model_name="SmartLogger")
    smartlogger._time_zone = 3600

    await smartlogger.get_history_alarms(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))

    start = int(datetime(2026, 1, 1, 1, 0, tzinfo=UTC).timestamp())
    end = int(datetime(2026, 1, 2, 1, 0, tzinfo=UTC).timestamp())
    _get_file(smartlogger).assert_awaited_once_with(0xA2, struct.pack("<BBIIbb", 0x24, 10, start, end, -1, 0))


async def test_history_int_window_is_passed_through(emma: EMMADevice) -> None:
    """Ints are device epochs already, as before."""
    await emma.get_history_alarms(1000, 2000)

    _get_file(emma).assert_awaited_once_with(0xA2, struct.pack("<BBIIbb", 0x24, 10, 1000, 2000, -1, 0))


def test_to_device_epoch_is_inverse_of_transform(emma: EMMADevice, sun2000_device: SUN2000Device) -> None:
    sun2000_device._time_zone = -300
    sun2000_device._dst = True
    instant = datetime(2026, 3, 29, 0, 30, tzinfo=UTC)

    for device in (emma, sun2000_device):
        local = datetime.fromtimestamp(device._to_device_epoch(instant), tz=UTC)
        assert device._transform_datetime(local) == instant

    assert emma._to_device_epoch(instant) == int((instant + timedelta(hours=2)).timestamp())
    assert sun2000_device._to_device_epoch(instant) == int((instant - timedelta(hours=4)).timestamp())


def test_to_device_epoch_naive_datetime_is_host_local(emma: EMMADevice) -> None:
    naive = datetime(2026, 11, 15, 1, 0)  # noqa: DTZ001
    assert emma._to_device_epoch(naive) == int(naive.timestamp()) + 7200


def test_to_device_epoch_with_host_timezone_across_dst(emma: EMMADevice) -> None:
    """With the host's time zone adopted, summer and winter windows use the right offset."""
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Bucharest"
    time.tzset()
    try:
        emma._use_host_timezone = True
        summer = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        winter = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)

        assert emma._to_device_epoch(summer) == int((summer + timedelta(hours=3)).timestamp())
        assert emma._to_device_epoch(winter) == int((winter + timedelta(hours=2)).timestamp())
        for instant in (summer, winter):
            local = datetime.fromtimestamp(emma._to_device_epoch(instant), tz=UTC)
            assert emma._transform_datetime(local) == instant
    finally:
        if original_tz is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = original_tz
        time.tzset()
