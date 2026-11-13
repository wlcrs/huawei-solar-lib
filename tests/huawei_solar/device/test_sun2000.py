"""Tests for the SUN2000Device class."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import huawei_solar.register_values as rv
import pytest
from huawei_solar.exceptions import ReadException, WriteException
from huawei_solar.register_values import StorageProductModel
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar.device import EMMADevice, SUN2000Device
from huawei_solar.register_definitions import Result, TimestampRegister


async def test_get_model_name(sun2000_device: SUN2000Device) -> None:
    result = await sun2000_device.batch_update([rn.MODEL_NAME])
    assert len(result) == 1
    assert result[rn.MODEL_NAME].value == "SUN2000-3KTL-L1"
    assert result[rn.MODEL_NAME].unit is None


async def test_get_multiple(sun2000_device: SUN2000Device) -> None:
    result = await sun2000_device.batch_update(
        [rn.INPUT_POWER, rn.LINE_VOLTAGE_A_B, rn.LINE_VOLTAGE_B_C, rn.LINE_VOLTAGE_C_A],
    )
    assert len(result) == 4
    assert result[rn.INPUT_POWER].value == 0
    assert result[rn.INPUT_POWER].unit == "W"
    assert result[rn.LINE_VOLTAGE_A_B].value == 0
    assert result[rn.LINE_VOLTAGE_A_B].unit == "V"
    assert result[rn.LINE_VOLTAGE_B_C].value == 0
    assert result[rn.LINE_VOLTAGE_B_C].unit == "V"
    assert result[rn.LINE_VOLTAGE_C_A].value == 0
    assert result[rn.LINE_VOLTAGE_C_A].unit == "V"


async def test_has_write_permission_with_valid_login(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When login credentials are provided and valid, has_write_permission returns True."""
    sun2000_device._HuaweiSolarDeviceWithLogin__username = "installer"  # type: ignore[attr-defined]
    sun2000_device._HuaweiSolarDeviceWithLogin__password = "test_password"  # type: ignore[attr-defined]  # noqa: S105

    async def mock_login(user: str, pwd: str) -> bool:
        return True

    monkeypatch.setattr(sun2000_device.client, "login", mock_login)

    assert await sun2000_device.has_write_permission() is True


async def test_has_write_permission_with_invalid_login(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When login credentials are provided and invalid, has_write_permission returns False."""
    sun2000_device._HuaweiSolarDeviceWithLogin__username = "installer"  # type: ignore[attr-defined]
    sun2000_device._HuaweiSolarDeviceWithLogin__password = "wrong_password"  # type: ignore[attr-defined]  # noqa: S105

    async def mock_login(user: str, pwd: str) -> bool:
        return False

    monkeypatch.setattr(sun2000_device.client, "login", mock_login)

    assert await sun2000_device.has_write_permission() is False


async def test_has_write_permission_unauthenticated_success(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When unauthenticated and register probe succeeds, has_write_permission returns True."""

    async def mock_raw_get(name: rn.RegisterName) -> Result[int]:
        return Result(60, "min")

    async def mock_raw_set(name: rn.RegisterName, value: int) -> bool:
        return True

    monkeypatch.setattr(sun2000_device, "_raw_get", mock_raw_get)
    monkeypatch.setattr(sun2000_device, "_raw_set", mock_raw_set)

    assert await sun2000_device.has_write_permission() is True


async def test_has_write_permission_unauthenticated_write_exception(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When unauthenticated and probe raises WriteException, has_write_permission returns False."""

    async def mock_raw_get(name: rn.RegisterName) -> Result[int]:
        return Result(60, "min")

    async def mock_raw_set(name: rn.RegisterName, value: int) -> bool:
        raise WriteException

    monkeypatch.setattr(sun2000_device, "_raw_get", mock_raw_get)
    monkeypatch.setattr(sun2000_device, "_raw_set", mock_raw_set)

    assert await sun2000_device.has_write_permission() is False


_READ_FAILED_MSG = "Failed to read register"


async def test_supports_ess_low_power_when_bit_set(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When FEATURE_MASK_30342 has bit 4 set, supports_ess_low_power is True."""

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    responses: dict[rn.RegisterName, Result[Any] | Exception] = {
        rn.NB_PV_STRINGS: Result(2, None),
        rn.NB_OPTIMIZERS: ReadException(_READ_FAILED_MSG),
        rn.STORAGE_UNIT_1_PRODUCT_MODEL: Result(StorageProductModel.HUAWEI_LUNA2000, None),
        rn.STORAGE_UNIT_2_PRODUCT_MODEL: Result(StorageProductModel.NONE, None),
        rn.FEATURE_MASK_2: Result(rv.FeatureMask2.BATTERY_CHARGE_DISCHARGE_LIMITS, None),
        rn.FEATURE_MASK_3: Result(
            rv.FeatureMask3.CAPACITY_CONTROL
            | rv.FeatureMask3.SECONDARY_GRID_TIED_CHARGE_POWER_LIMIT
            | rv.FeatureMask3.COMMUNICATION_FAIL_ACTIVE_POWER_DERATING,
            None,
        ),
        rn.FEATURE_MASK_30308: Result(rv.FeatureMask30308.BACKUP_OFF_GRID_SWITCHING, None),
        rn.FEATURE_MASK_30320: Result(rv.FeatureMask30320.VOLTAGE_IN_INDEPENDENT_OPERATION, None),
        rn.FEATURE_MASK_30342: Result(rv.FeatureMask30342.ESS_LOW_POWER, None),
        rn.METER_STATUS: ReadException(_READ_FAILED_MSG),
        rn.DAYLIGHT_SAVING_TIME: ReadException(_READ_FAILED_MSG),
        rn.TIME_ZONE: ReadException(_READ_FAILED_MSG),
    }

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        if name in responses:
            val = responses[name]
            if isinstance(val, Exception):
                raise val
            return val
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(sun2000_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(sun2000_device.client, "get", mock_get)
    await sun2000_device._populate_additional_fields()

    assert sun2000_device.supports_capacity_control is True
    assert sun2000_device.supports_ess_low_power is True
    assert sun2000_device.supports_off_grid_switch is True
    assert sun2000_device.supports_backup_voltage is True
    assert sun2000_device.supports_active_power_fail_safe is True
    assert sun2000_device.supports_active_power_limitation_mode is True
    assert sun2000_device.supports_dongle_charge_power_limit is True
    assert sun2000_device.supports_discharge_power_adjustment is True
    assert sun2000_device.supports_recharge is True


async def test_supports_ess_low_power_when_bit_cleared(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When FEATURE_MASK_30342 has bit 4 cleared, supports_ess_low_power is False."""

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    responses: dict[rn.RegisterName, Result[Any] | Exception] = {
        rn.NB_PV_STRINGS: Result(2, None),
        rn.NB_OPTIMIZERS: ReadException(_READ_FAILED_MSG),
        rn.STORAGE_UNIT_1_PRODUCT_MODEL: Result(StorageProductModel.HUAWEI_LUNA2000, None),
        rn.STORAGE_UNIT_2_PRODUCT_MODEL: Result(StorageProductModel.NONE, None),
        rn.FEATURE_MASK_2: Result(rv.FeatureMask2(0), None),
        rn.FEATURE_MASK_3: Result(rv.FeatureMask3(0), None),
        rn.FEATURE_MASK_30308: Result(rv.FeatureMask30308(0), None),
        rn.FEATURE_MASK_30320: Result(rv.FeatureMask30320(0), None),
        rn.FEATURE_MASK_30342: Result(rv.FeatureMask30342(0), None),
        rn.METER_STATUS: ReadException(_READ_FAILED_MSG),
        rn.DAYLIGHT_SAVING_TIME: ReadException(_READ_FAILED_MSG),
        rn.TIME_ZONE: ReadException(_READ_FAILED_MSG),
    }

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        if name in responses:
            val = responses[name]
            if isinstance(val, Exception):
                raise val
            return val
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(sun2000_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(sun2000_device.client, "get", mock_get)
    await sun2000_device._populate_additional_fields()

    assert sun2000_device.supports_capacity_control is False
    assert sun2000_device.supports_ess_low_power is False
    assert sun2000_device.supports_off_grid_switch is False
    assert sun2000_device.supports_backup_voltage is False
    assert sun2000_device.supports_active_power_fail_safe is False
    assert sun2000_device.supports_active_power_limitation_mode is False
    assert sun2000_device.supports_dongle_charge_power_limit is False
    assert sun2000_device.supports_discharge_power_adjustment is False
    assert sun2000_device.supports_recharge is False


async def test_supports_ess_low_power_when_connected_through_emma(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When SUN2000 has an EMMADevice as primary device, supports_ess_low_power is still detected."""
    sun2000_device.primary_device = MagicMock(spec=EMMADevice)

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    responses: dict[rn.RegisterName, Result[Any] | Exception] = {
        rn.NB_PV_STRINGS: Result(2, None),
        rn.NB_OPTIMIZERS: ReadException(_READ_FAILED_MSG),
        rn.STORAGE_UNIT_1_PRODUCT_MODEL: Result(StorageProductModel.HUAWEI_LUNA2000, None),
        rn.STORAGE_UNIT_2_PRODUCT_MODEL: Result(StorageProductModel.NONE, None),
        rn.FEATURE_MASK_3: Result(
            rv.FeatureMask3.CAPACITY_CONTROL | rv.FeatureMask3.SECONDARY_GRID_TIED_CHARGE_POWER_LIMIT,
            None,
        ),
        rn.FEATURE_MASK_30308: ReadException(_READ_FAILED_MSG),
        rn.FEATURE_MASK_30320: ReadException(_READ_FAILED_MSG),
        rn.FEATURE_MASK_30342: Result(rv.FeatureMask30342.ESS_LOW_POWER, None),
        rn.METER_STATUS: ReadException(_READ_FAILED_MSG),
        rn.DAYLIGHT_SAVING_TIME: ReadException(_READ_FAILED_MSG),
        rn.TIME_ZONE: ReadException(_READ_FAILED_MSG),
    }

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        if name in responses:
            val = responses[name]
            if isinstance(val, Exception):
                raise val
            return val
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(sun2000_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(sun2000_device.client, "get", mock_get)
    await sun2000_device._populate_additional_fields()

    assert sun2000_device.supports_capacity_control is False
    assert sun2000_device.supports_dongle_charge_power_limit is False
    assert sun2000_device.supports_discharge_power_adjustment is False
    assert sun2000_device.supports_ess_low_power is True


async def test_supports_ess_low_power_when_read_exception(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When reading FEATURE_MASK_30342 raises ReadException, supports_ess_low_power is False."""

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    responses: dict[rn.RegisterName, Result[Any] | Exception] = {
        rn.NB_PV_STRINGS: Result(2, None),
        rn.NB_OPTIMIZERS: ReadException(_READ_FAILED_MSG),
        rn.STORAGE_UNIT_1_PRODUCT_MODEL: Result(StorageProductModel.HUAWEI_LUNA2000, None),
        rn.STORAGE_UNIT_2_PRODUCT_MODEL: Result(StorageProductModel.NONE, None),
        rn.FEATURE_MASK_2: ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02),
        rn.FEATURE_MASK_3: ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02),
        rn.FEATURE_MASK_30308: ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02),
        rn.FEATURE_MASK_30320: ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02),
        rn.FEATURE_MASK_30342: ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02),
        rn.METER_STATUS: ReadException(_READ_FAILED_MSG),
        rn.DAYLIGHT_SAVING_TIME: ReadException(_READ_FAILED_MSG),
        rn.TIME_ZONE: ReadException(_READ_FAILED_MSG),
    }

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        if name in responses:
            val = responses[name]
            if isinstance(val, Exception):
                raise val
            return val
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(sun2000_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(sun2000_device.client, "get", mock_get)
    await sun2000_device._populate_additional_fields()

    assert sun2000_device.supports_capacity_control is False
    assert sun2000_device.supports_ess_low_power is False
    assert sun2000_device.supports_off_grid_switch is False
    assert sun2000_device.supports_backup_voltage is False
    assert sun2000_device.supports_active_power_fail_safe is False
    assert sun2000_device.supports_active_power_limitation_mode is False
    assert sun2000_device.supports_dongle_charge_power_limit is False
    assert sun2000_device.supports_discharge_power_adjustment is False
    assert sun2000_device.supports_recharge is False


async def test_filter_registers_power_meter_offline_no_deadlock(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When power_meter_online is False, batch_update does not deadlock on update_lock."""
    sun2000_device.power_meter_online = False

    async def mock_get_multiple_as_dict(names: list[rn.RegisterName]) -> dict[rn.RegisterName, Result[Any]]:
        return {name: Result(0, None) for name in names}

    async def mock_raw_get(name: rn.RegisterName) -> Result[Any]:
        if name == rn.METER_STATUS:
            return Result(rv.MeterStatus.NORMAL, None)
        return Result(0, None)

    monkeypatch.setattr(sun2000_device.client, "get_multiple_as_dict", mock_get_multiple_as_dict)
    monkeypatch.setattr(sun2000_device, "_raw_get", mock_raw_get)

    result = await sun2000_device.batch_update([rn.METER_STATUS, rn.ACTIVE_GRID_A_POWER])
    assert sun2000_device.power_meter_online is True
    assert rn.METER_STATUS in result
    assert rn.ACTIVE_GRID_A_POWER in result


async def test_populate_additional_fields_meter_queried_only_once(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rn.METER_STATUS and rn.METER_TYPE should only be queried once during _populate_additional_fields."""
    queried_registers: list[rn.RegisterName] = []

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    async def mock_client_get(name: rn.RegisterName) -> Result[Any]:
        queried_registers.append(name)
        if name == rn.NB_PV_STRINGS:
            return Result(2, None)
        if name == rn.METER_STATUS:
            return Result(rv.MeterStatus.NORMAL, None)
        if name == rn.METER_TYPE:
            return Result(rv.MeterType.THREE_PHASE, None)
        if name in (rn.NB_OPTIMIZERS, rn.STORAGE_UNIT_1_PRODUCT_MODEL, rn.STORAGE_UNIT_2_PRODUCT_MODEL):
            raise ReadException(_READ_FAILED_MSG)
        if name in (
            rn.FEATURE_MASK_3,
            rn.FEATURE_MASK_30308,
            rn.FEATURE_MASK_30320,
            rn.FEATURE_MASK_2,
            rn.FEATURE_MASK_30342,
            rn.DAYLIGHT_SAVING_TIME,
            rn.TIME_ZONE,
        ):
            raise ReadException(_READ_FAILED_MSG)
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(sun2000_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(sun2000_device.client, "get", mock_client_get)

    await sun2000_device._populate_additional_fields()

    assert sun2000_device.power_meter_online is True
    assert sun2000_device.power_meter_type == rv.MeterType.THREE_PHASE
    assert queried_registers.count(rn.METER_STATUS) == 1
    assert queried_registers.count(rn.METER_TYPE) == 1


# The inverter stores its local wall-clock time in its timestamp registers. A local time of
# 2026-03-10 12:00:00 is therefore stored as the epoch value of 2026-03-10 12:00:00 UTC.
_LOCAL_STARTUP_RAW = int(datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC).timestamp())


@pytest.mark.parametrize(
    ("time_zone", "dst", "expected_utc"),
    [
        (-300, False, datetime(2026, 3, 10, 17, 0, 0, tzinfo=UTC)),  # UTC-5
        (0, False, datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)),  # UTC
        (60, True, datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)),  # UTC+1 with DST
        (None, None, datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)),  # firmware without TIME_ZONE/DST
    ],
)
async def test_batch_update_converts_timestamps_to_utc(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
    time_zone: int | None,
    dst: bool | None,  # noqa: FBT001
    expected_utc: datetime,
) -> None:
    """Timestamp registers are shifted from the inverter's local time to UTC."""
    sun2000_device._time_zone = time_zone
    sun2000_device._dst = dst

    async def mock_get_multiple_as_dict(names: list[rn.RegisterName]) -> dict[rn.RegisterName, Result[Any]]:
        return {
            name: REGISTERS[name].decode((_LOCAL_STARTUP_RAW,)) if name == rn.STARTUP_TIME else Result(0, "W")
            for name in names
        }

    monkeypatch.setattr(sun2000_device.client, "get_multiple_as_dict", mock_get_multiple_as_dict)

    result = await sun2000_device.batch_update([rn.STARTUP_TIME, rn.ACTIVE_POWER])

    assert result[rn.STARTUP_TIME].value == expected_utc
    assert result[rn.STARTUP_TIME].value.tzinfo == UTC
    assert result[rn.ACTIVE_POWER] == Result(0, "W")


async def test_get_converts_timestamps_to_utc(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single get() of a timestamp register applies the same conversion."""
    sun2000_device._time_zone = -300

    async def mock_client_get(name: rn.RegisterName) -> Result[Any]:
        assert name == rn.SHUTDOWN_TIME
        return REGISTERS[name].decode((_LOCAL_STARTUP_RAW,))

    monkeypatch.setattr(sun2000_device.client, "get", mock_client_get)

    result = await sun2000_device.get(rn.SHUTDOWN_TIME)
    assert result.value == datetime(2026, 3, 10, 17, 0, 0, tzinfo=UTC)


async def test_invalid_timestamp_stays_none(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid (unset) timestamp is not shifted."""
    sun2000_device._time_zone = -300

    async def mock_get_multiple_as_dict(names: list[rn.RegisterName]) -> dict[rn.RegisterName, Result[Any]]:
        reg = REGISTERS[rn.STARTUP_TIME]
        assert isinstance(reg, TimestampRegister)
        return {rn.STARTUP_TIME: reg.decode((reg.invalid_value,))}

    monkeypatch.setattr(sun2000_device.client, "get_multiple_as_dict", mock_get_multiple_as_dict)

    result = await sun2000_device.batch_update([rn.STARTUP_TIME])
    assert result[rn.STARTUP_TIME].value is None


async def test_populate_additional_fields_reads_time_zone_and_dst(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TIME_ZONE and DAYLIGHT_SAVING_TIME are read during setup."""

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    async def mock_client_get(name: rn.RegisterName) -> Result[Any]:
        if name == rn.NB_PV_STRINGS:
            return Result(2, None)
        if name == rn.TIME_ZONE:
            return Result(-300, "min")
        if name == rn.DAYLIGHT_SAVING_TIME:
            return Result(value=False, unit=None)
        raise ReadException(_READ_FAILED_MSG)

    monkeypatch.setattr(sun2000_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(sun2000_device.client, "get", mock_client_get)

    await sun2000_device._populate_additional_fields()

    assert sun2000_device._time_zone == -300
    assert sun2000_device._dst is False
