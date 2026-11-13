"""Tests for EMMA and SmartLogger timestamp register and file datetime handling."""

import struct
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from huawei_solar import AsyncHuaweiSolarClient
from huawei_solar import register_names as rn
from huawei_solar.device import EMMADevice, SmartLoggerDevice
from huawei_solar.register_definitions import Result


@pytest.fixture
def emma_device() -> EMMADevice:
    """Create an EMMADevice instance with a mocked client."""
    client = AsyncMock(spec=AsyncHuaweiSolarClient)
    return EMMADevice(client=client, model_name="SmartHEMS")


@pytest.fixture
def smartlogger_device() -> SmartLoggerDevice:
    """Create a SmartLoggerDevice instance with a mocked client."""
    client = AsyncMock(spec=AsyncHuaweiSolarClient)
    return SmartLoggerDevice(client=client, model_name="SmartLogger")


async def test_emma_populates_offset_and_transforms_only_local_time(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EMMA_LOCAL_TIME is shifted to UTC while EMMA_SYSTEM_TIME is already UTC."""
    utc_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)
    local_time = datetime(2026, 8, 21, 12, 0, 2, tzinfo=UTC)  # +2h with 2s read skew

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[Any]]:
        if names == [rn.SERIAL_NUMBER, rn.SOFTWARE_VERSION]:
            return [Result("EMMA123", None), Result("V100", None)]
        if names == [rn.EMMA_LOCAL_TIME, rn.EMMA_SYSTEM_TIME]:
            return [Result(local_time, None), Result(utc_time, None)]
        msg = f"Unexpected get_multiple: {names}"
        raise AssertionError(msg)

    async def mock_client_get(name: rn.RegisterName) -> Result[Any]:
        if name == rn.EMMA_MODEL:
            return Result("EMMA-A02", None)
        if name == rn.EMMA_LOCAL_TIME:
            return Result(datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC), None)
        if name == rn.EMMA_SYSTEM_TIME:
            return Result(utc_time, None)
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(emma_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(emma_device.client, "get", mock_client_get)

    await emma_device._populate_additional_fields()
    assert emma_device._utc_offset == timedelta(hours=2)

    assert (await emma_device.get(rn.EMMA_LOCAL_TIME)).value == utc_time
    assert (await emma_device.get(rn.EMMA_SYSTEM_TIME)).value == utc_time


async def test_emma_active_alarms_adjusted_to_utc(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active alarm timestamps on EMMADevice are adjusted from local wall-clock time to UTC."""
    emma_device._utc_offset = timedelta(hours=2)
    local_epoch = int(datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC).timestamp())
    file_data = struct.pack("<IHHIIHH", 1, 0, 2001, local_epoch, 0, 0, 1)

    monkeypatch.setattr(emma_device.client, "get_file", AsyncMock(return_value=file_data))

    alarms = await emma_device.get_active_alarms()
    assert len(alarms) == 1
    assert alarms[0].occur_time == datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)


async def test_smartlogger_populates_tz_and_transforms_only_local_time(
    smartlogger_device: SmartLoggerDevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SMARTLOGGER_LOCAL_TIME is shifted to UTC while SMARTLOGGER_DATE_TIME is already UTC."""
    utc_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)
    local_time = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)

    async def mock_client_get(name: rn.RegisterName) -> Result[Any]:
        responses: dict[rn.RegisterName, Result[Any]] = {
            rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN: Result("SL123", None),
            rn.SMARTLOGGER_TIME_ZONE: Result(3600, "s"),
            rn.SMARTLOGGER_DST_STATE: Result(1, None),
            rn.SMARTLOGGER_DST_OFFSET: Result(60, "mins"),
            rn.SMARTLOGGER_LOCAL_TIME: Result(local_time, None),
            rn.SMARTLOGGER_DATE_TIME: Result(utc_time, None),
        }
        return responses[name]

    monkeypatch.setattr(smartlogger_device.client, "get", mock_client_get)

    await smartlogger_device._populate_additional_fields()
    assert (await smartlogger_device.get(rn.SMARTLOGGER_LOCAL_TIME)).value == utc_time
    assert (await smartlogger_device.get(rn.SMARTLOGGER_DATE_TIME)).value == utc_time


async def test_smartlogger_detect_state_changes_updates_tz(
    smartlogger_device: SmartLoggerDevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling SmartLogger timezone/DST registers updates cached values."""
    smartlogger_device._time_zone = 0
    smartlogger_device._dst_state = 0
    smartlogger_device._dst_offset = 0

    async def mock_get_multiple_as_dict(names: list[rn.RegisterName]) -> dict[rn.RegisterName, Result[Any]]:
        responses: dict[rn.RegisterName, Result[Any]] = {
            rn.SMARTLOGGER_TIME_ZONE: Result(-18000, "s"),
            rn.SMARTLOGGER_DST_STATE: Result(1, None),
            rn.SMARTLOGGER_DST_OFFSET: Result(60, "mins"),
            rn.SMARTLOGGER_LOCAL_TIME: Result(datetime(2026, 8, 21, 7, 0, 0, tzinfo=UTC), None),
        }
        return {name: responses[name] for name in names}

    monkeypatch.setattr(smartlogger_device.client, "get_multiple_as_dict", mock_get_multiple_as_dict)

    await smartlogger_device.batch_update(
        [rn.SMARTLOGGER_TIME_ZONE, rn.SMARTLOGGER_DST_STATE, rn.SMARTLOGGER_DST_OFFSET],
    )
    result = await smartlogger_device.batch_update([rn.SMARTLOGGER_LOCAL_TIME])
    assert result[rn.SMARTLOGGER_LOCAL_TIME].value == datetime(2026, 8, 21, 11, 0, 0, tzinfo=UTC)


async def test_emma_adopts_matching_host_timezone_across_dst(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When host timezone matches EMMA's current offset, historical/cross-DST timestamps use its DST rules."""
    brussels = ZoneInfo("Europe/Brussels")
    current_offset = datetime.now(tz=UTC).astimezone(brussels).utcoffset()
    assert current_offset is not None

    monkeypatch.setenv("TZ", "Europe/Brussels")
    time.tzset()
    try:
        utc_now = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)
        local_now = utc_now + current_offset

        async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[Any]]:
            if names == [rn.SERIAL_NUMBER, rn.SOFTWARE_VERSION]:
                return [Result("EMMA123", None), Result("V100", None)]
            if names == [rn.EMMA_LOCAL_TIME, rn.EMMA_SYSTEM_TIME]:
                return [Result(local_now, None), Result(utc_now, None)]
            msg = f"Unexpected get_multiple: {names}"
            raise AssertionError(msg)

        monkeypatch.setattr(emma_device.client, "get_multiple", mock_get_multiple)
        monkeypatch.setattr(emma_device.client, "get", AsyncMock(return_value=Result("EMMA-A02", None)))

        await emma_device._populate_additional_fields()
        assert emma_device._use_host_timezone is True

        # Summer (+2h) and winter (+1h) timestamps are both converted accurately
        assert emma_device._transform_datetime(datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)) == datetime(
            2026, 8, 21, 10, 0, 0, tzinfo=UTC
        )
        assert emma_device._transform_datetime(datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)) == datetime(
            2026, 1, 15, 11, 0, 0, tzinfo=UTC
        )
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()


async def test_emma_falls_back_to_fixed_offset_when_host_timezone_mismatches(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When host timezone does not match EMMA's offset, EMMA keeps the fixed device offset."""
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        utc_now = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)
        local_now = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)  # +2h, never matches New York (-4h/-5h)

        async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[Any]]:
            if names == [rn.SERIAL_NUMBER, rn.SOFTWARE_VERSION]:
                return [Result("EMMA123", None), Result("V100", None)]
            if names == [rn.EMMA_LOCAL_TIME, rn.EMMA_SYSTEM_TIME]:
                return [Result(local_now, None), Result(utc_now, None)]
            msg = f"Unexpected get_multiple: {names}"
            raise AssertionError(msg)

        monkeypatch.setattr(emma_device.client, "get_multiple", mock_get_multiple)
        monkeypatch.setattr(emma_device.client, "get", AsyncMock(return_value=Result("EMMA-A02", None)))

        await emma_device._populate_additional_fields()
        assert emma_device._use_host_timezone is False
        assert emma_device._transform_datetime(datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)) == datetime(
            2026, 1, 15, 10, 0, 0, tzinfo=UTC
        )
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()
