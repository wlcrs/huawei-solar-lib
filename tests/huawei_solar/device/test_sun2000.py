"""Tests for the SUN2000Device class."""

import struct
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import huawei_solar.register_values as rv
import pytest
from huawei_solar.exceptions import ConnectionInterruptedException, ReadException, WriteException
from huawei_solar.files import ActiveAlarmsDataFile, HistoryAlarmsDataFile, PerformanceRequestType
from huawei_solar.register_values import StorageProductModel
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar.device import EMMADevice, SUN2000Device
from huawei_solar.register_definitions import Result


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
        rn.FEATURE_MASK_30283: Result(rv.FeatureMask30283.THIRD_PARTY_CONTROL, None),
        rn.FEATURE_MASK_30306: Result(
            rv.FeatureMask30306.BATTERY_RECHARGE | rv.FeatureMask30306.DISCHARGE_POWER_ADJUSTMENT,
            None,
        ),
        rn.FEATURE_MASK_30308: Result(rv.FeatureMask30308.BACKUP_OFF_GRID_SWITCHING, None),
        rn.FEATURE_MASK_30316: Result(rv.FeatureMask30316.GRID_TIED_OFF_GRID_SWITCHING, None),
        rn.FEATURE_MASK_30320: Result(rv.FeatureMask30320.VOLTAGE_IN_INDEPENDENT_OPERATION, None),
        rn.FEATURE_MASK_30342: Result(rv.FeatureMask30342.ESS_LOW_POWER, None),
        rn.STORAGE_ESS_LOW_POWER: Result(value=False, unit=None),
        rn.METER_STATUS: ReadException(_READ_FAILED_MSG),
        rn.DAYLIGHT_SAVING_TIME: Result(value=False, unit=None),
        rn.TIME_ZONE: Result(60, "min"),
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
    assert sun2000_device.supports_charge_from_grid_power is True
    assert sun2000_device.supports_discharge_power_adjustment is True
    assert sun2000_device.supports_recharge is True
    assert sun2000_device.supports_third_party_control is True


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
        rn.FEATURE_MASK_30283: Result(rv.FeatureMask30283(0), None),
        rn.FEATURE_MASK_30306: Result(rv.FeatureMask30306(0), None),
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
    assert sun2000_device.supports_charge_from_grid_power is False
    assert sun2000_device.supports_discharge_power_adjustment is False
    assert sun2000_device.supports_recharge is False
    assert sun2000_device.supports_third_party_control is False


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
        rn.FEATURE_MASK_30283: Result(rv.FeatureMask30283.THIRD_PARTY_CONTROL, None),
        rn.FEATURE_MASK_30308: ReadException(_READ_FAILED_MSG),
        rn.FEATURE_MASK_30320: ReadException(_READ_FAILED_MSG),
        rn.FEATURE_MASK_30342: Result(rv.FeatureMask30342.ESS_LOW_POWER, None),
        rn.STORAGE_ESS_LOW_POWER: Result(value=False, unit=None),
        rn.METER_STATUS: ReadException(_READ_FAILED_MSG),
        rn.DAYLIGHT_SAVING_TIME: Result(value=False, unit=None),
        rn.TIME_ZONE: Result(60, "min"),
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
    assert sun2000_device.supports_charge_from_grid_power is False
    assert sun2000_device.supports_discharge_power_adjustment is False
    assert sun2000_device.supports_recharge is False
    assert sun2000_device.supports_third_party_control is True
    assert sun2000_device.supports_ess_low_power is True


@pytest.mark.parametrize(
    ("feature_mask_30316", "expected_off_grid_switch"),
    [
        (Result(rv.FeatureMask30316.GRID_TIED_OFF_GRID_SWITCHING, None), True),
        # SUN2000-12K-MAP0 behind an EMMA-A02 with a SmartGuard: bit 1 is clear and the FusionSolar app hides
        # "Switch to off-grid"; writing 47604 there has no effect.
        (Result(rv.FeatureMask30316(0x161C), None), False),
        (ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02), False),
        # A mask with every bit set is a mask, not the U16 invalid value.
        (Result(rv.FeatureMask30316(0xFFFF), None), True),
    ],
)
async def test_off_grid_switch_needs_feature_mask_30316(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
    feature_mask_30316: Result[Any] | Exception,
    expected_off_grid_switch: bool,  # noqa: FBT001
) -> None:
    """The off-grid switch (47604) also needs bit 1 of 30316; the backup voltage (47605) does not."""

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    responses: dict[rn.RegisterName, Result[Any] | Exception] = {
        rn.NB_PV_STRINGS: Result(2, None),
        rn.NB_OPTIMIZERS: ReadException(_READ_FAILED_MSG),
        rn.STORAGE_UNIT_1_PRODUCT_MODEL: Result(StorageProductModel.HUAWEI_LUNA2000, None),
        rn.STORAGE_UNIT_2_PRODUCT_MODEL: Result(StorageProductModel.NONE, None),
        rn.FEATURE_MASK_2: Result(rv.FeatureMask2(0), None),
        rn.FEATURE_MASK_3: Result(rv.FeatureMask3(0), None),
        rn.FEATURE_MASK_30308: Result(rv.FeatureMask30308.BACKUP_OFF_GRID_SWITCHING, None),
        rn.FEATURE_MASK_30283: Result(rv.FeatureMask30283(0), None),
        rn.FEATURE_MASK_30306: Result(rv.FeatureMask30306(0), None),
        rn.FEATURE_MASK_30316: feature_mask_30316,
        rn.FEATURE_MASK_30320: Result(rv.FeatureMask30320.VOLTAGE_IN_INDEPENDENT_OPERATION, None),
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

    assert sun2000_device.supports_off_grid_switch is expected_off_grid_switch
    assert sun2000_device.supports_backup_voltage is True


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
        rn.FEATURE_MASK_30283: ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02),
        rn.FEATURE_MASK_30306: ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02),
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
    assert sun2000_device.supports_charge_from_grid_power is False
    assert sun2000_device.supports_discharge_power_adjustment is False
    assert sun2000_device.supports_recharge is False
    assert sun2000_device.supports_third_party_control is False


async def _populate_with_mocked_responses(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[rn.RegisterName, Result[Any] | Exception],
) -> None:
    """Populate a SUN2000Device using default battery feature-mask stubs merged with overrides."""

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    responses: dict[rn.RegisterName, Result[Any] | Exception] = {
        rn.NB_PV_STRINGS: Result(2, None),
        rn.NB_OPTIMIZERS: ReadException(_READ_FAILED_MSG),
        rn.STORAGE_UNIT_1_PRODUCT_MODEL: Result(StorageProductModel.HUAWEI_LUNA2000, None),
        rn.STORAGE_UNIT_2_PRODUCT_MODEL: Result(StorageProductModel.NONE, None),
        rn.FEATURE_MASK_2: Result(rv.FeatureMask2(0), None),
        rn.FEATURE_MASK_3: Result(rv.FeatureMask3(0), None),
        rn.FEATURE_MASK_30283: Result(rv.FeatureMask30283(0), None),
        rn.FEATURE_MASK_30306: Result(rv.FeatureMask30306(0), None),
        rn.FEATURE_MASK_30308: Result(rv.FeatureMask30308(0), None),
        rn.FEATURE_MASK_30320: Result(rv.FeatureMask30320(0), None),
        rn.FEATURE_MASK_30342: Result(rv.FeatureMask30342(0), None),
        rn.METER_STATUS: ReadException(_READ_FAILED_MSG),
        rn.DAYLIGHT_SAVING_TIME: ReadException(_READ_FAILED_MSG),
        rn.TIME_ZONE: ReadException(_READ_FAILED_MSG),
        **overrides,
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


async def test_battery_feature_support_lg_resu(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LG RESU disables recharge even if bit 9 of FEATURE_MASK_30306 is set."""
    await _populate_with_mocked_responses(
        sun2000_device,
        monkeypatch,
        {
            rn.STORAGE_UNIT_1_PRODUCT_MODEL: Result(StorageProductModel.LG_RESU, None),
            rn.FEATURE_MASK_2: Result(rv.FeatureMask2.BATTERY_CHARGE_DISCHARGE_LIMITS, None),
            rn.FEATURE_MASK_30283: Result(rv.FeatureMask30283.THIRD_PARTY_CONTROL, None),
            rn.FEATURE_MASK_30306: Result(
                rv.FeatureMask30306.BATTERY_RECHARGE | rv.FeatureMask30306.DISCHARGE_POWER_ADJUSTMENT,
                None,
            ),
        },
    )

    assert sun2000_device.supports_recharge is False
    assert sun2000_device.supports_charge_from_grid_power is True
    assert sun2000_device.supports_discharge_power_adjustment is True
    assert sun2000_device.supports_third_party_control is True


async def test_discharge_power_adjustment_requires_both_masks(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discharge power adjustment requires both FEATURE_MASK_2 bit 28 and FEATURE_MASK_30306 bit 15."""
    await _populate_with_mocked_responses(
        sun2000_device,
        monkeypatch,
        {
            rn.FEATURE_MASK_2: Result(rv.FeatureMask2.BATTERY_CHARGE_DISCHARGE_LIMITS, None),
            rn.FEATURE_MASK_30306: Result(rv.FeatureMask30306(0), None),
        },
    )
    assert sun2000_device.supports_charge_from_grid_power is True
    assert sun2000_device.supports_discharge_power_adjustment is False
    assert sun2000_device.supports_recharge is False

    await _populate_with_mocked_responses(
        sun2000_device,
        monkeypatch,
        {
            rn.FEATURE_MASK_2: Result(rv.FeatureMask2(0), None),
            rn.FEATURE_MASK_30306: Result(
                rv.FeatureMask30306.BATTERY_RECHARGE | rv.FeatureMask30306.DISCHARGE_POWER_ADJUSTMENT,
                None,
            ),
        },
    )
    assert sun2000_device.supports_charge_from_grid_power is False
    assert sun2000_device.supports_discharge_power_adjustment is False
    assert sun2000_device.supports_recharge is True


async def test_recharge_supported_on_battery_2_luna2000(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LUNA2000 on storage unit 2 only also satisfies the recharge battery-type check."""
    await _populate_with_mocked_responses(
        sun2000_device,
        monkeypatch,
        {
            rn.STORAGE_UNIT_1_PRODUCT_MODEL: Result(StorageProductModel.NONE, None),
            rn.STORAGE_UNIT_2_PRODUCT_MODEL: Result(StorageProductModel.HUAWEI_LUNA2000, None),
            rn.FEATURE_MASK_30306: Result(rv.FeatureMask30306.BATTERY_RECHARGE, None),
        },
    )
    assert sun2000_device.supports_recharge is True


async def test_invalid_none_feature_masks_resolve_to_false(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When feature masks decode as None (invalid value), gated flags stay False."""
    await _populate_with_mocked_responses(
        sun2000_device,
        monkeypatch,
        {
            rn.FEATURE_MASK_2: Result(None, None),
            rn.FEATURE_MASK_30283: Result(None, None),
            rn.FEATURE_MASK_30306: Result(None, None),
            rn.FEATURE_MASK_30342: Result(None, None),
        },
    )
    assert sun2000_device.supports_charge_from_grid_power is False
    assert sun2000_device.supports_discharge_power_adjustment is False
    assert sun2000_device.supports_recharge is False
    assert sun2000_device.supports_third_party_control is False
    assert sun2000_device.supports_ess_low_power is False


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
            rn.FEATURE_MASK_30283,
            rn.FEATURE_MASK_30306,
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


@pytest.mark.parametrize(
    ("time_zone", "dst", "expected_utc"),
    [
        (-300, False, datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)),
        (60, True, datetime(2026, 8, 21, 5, 0, 0, tzinfo=UTC)),
        (0, False, datetime(2026, 8, 21, 7, 0, 0, tzinfo=UTC)),
        (None, None, datetime(2026, 8, 21, 7, 0, 0, tzinfo=UTC)),
    ],
)
async def test_timestamp_registers_adjusted_for_inverter_timezone(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
    *,
    time_zone: int | None,
    dst: bool | None,
    expected_utc: datetime,
) -> None:
    """Timestamp registers are converted from inverter wall-clock time to UTC."""
    sun2000_device._time_zone = time_zone
    sun2000_device._dst = dst
    raw_local = datetime(2026, 8, 21, 7, 0, 0, tzinfo=UTC)

    async def mock_get_multiple_as_dict(names: list[rn.RegisterName]) -> dict[rn.RegisterName, Result[Any]]:
        return {name: Result(raw_local, None) for name in names}

    async def mock_client_get(name: rn.RegisterName) -> Result[Any]:
        return Result(raw_local, None)

    monkeypatch.setattr(sun2000_device.client, "get_multiple_as_dict", mock_get_multiple_as_dict)
    monkeypatch.setattr(sun2000_device.client, "get", mock_client_get)

    batch_result = await sun2000_device.batch_update([rn.STARTUP_TIME, rn.SHUTDOWN_TIME])
    assert batch_result[rn.STARTUP_TIME].value == expected_utc
    assert batch_result[rn.SHUTDOWN_TIME].value == expected_utc

    single_result = await sun2000_device.get(rn.STARTUP_TIME)
    assert single_result.value == expected_utc


async def test_timestamp_register_none_not_adjusted(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid (None) timestamp register values stay None."""
    sun2000_device._time_zone = -300
    sun2000_device._dst = True

    async def mock_get_multiple_as_dict(names: list[rn.RegisterName]) -> dict[rn.RegisterName, Result[Any]]:
        return {name: Result(None, None) for name in names}

    monkeypatch.setattr(sun2000_device.client, "get_multiple_as_dict", mock_get_multiple_as_dict)

    result = await sun2000_device.batch_update([rn.STARTUP_TIME])
    assert result[rn.STARTUP_TIME].value is None


async def test_detect_state_changes_updates_timezone_and_dst(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling TIME_ZONE and DAYLIGHT_SAVING_TIME updates cached values for subsequent timestamp reads."""
    sun2000_device._time_zone = 0
    sun2000_device._dst = False
    raw_local = datetime(2026, 8, 21, 7, 0, 0, tzinfo=UTC)

    async def mock_get_multiple_as_dict(names: list[rn.RegisterName]) -> dict[rn.RegisterName, Result[Any]]:
        responses: dict[rn.RegisterName, Result[Any]] = {
            rn.TIME_ZONE: Result(60, "min"),
            rn.DAYLIGHT_SAVING_TIME: Result(value=True, unit=None),
            rn.STARTUP_TIME: Result(raw_local, None),
        }
        return {name: responses[name] for name in names}

    monkeypatch.setattr(sun2000_device.client, "get_multiple_as_dict", mock_get_multiple_as_dict)

    await sun2000_device.batch_update([rn.TIME_ZONE, rn.DAYLIGHT_SAVING_TIME])
    assert sun2000_device._time_zone == 60
    assert sun2000_device._dst is True

    result = await sun2000_device.batch_update([rn.STARTUP_TIME])
    assert result[rn.STARTUP_TIME].value == datetime(2026, 8, 21, 5, 0, 0, tzinfo=UTC)


async def test_file_timestamps_adjusted_for_inverter_timezone(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timestamps read from alarm and performance files are converted to UTC."""
    sun2000_device._time_zone = -300
    sun2000_device._dst = True

    raw_occur = int(datetime(2026, 8, 21, 7, 0, 0, tzinfo=UTC).timestamp())
    raw_recover = int(datetime(2026, 8, 21, 8, 0, 0, tzinfo=UTC).timestamp())
    expected_occur = datetime(2026, 8, 21, 11, 0, 0, tzinfo=UTC)
    expected_recover = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)

    active_payload = struct.pack(ActiveAlarmsDataFile.RECORD_STRUCT, 1, 0, 2001, raw_occur, 0, 0, 1)
    history_payload = struct.pack(HistoryAlarmsDataFile.RECORD_STRUCT, 1, 0, 2001, raw_occur, raw_recover, 0, 0, 1)
    performance_payload = struct.pack(">IBi", raw_occur, 4, 150)

    async def mock_read_file(file_type: int, customized_data: bytes | None = None) -> bytes:
        if file_type == ActiveAlarmsDataFile.FILE_TYPE:
            return active_payload
        if file_type == HistoryAlarmsDataFile.FILE_TYPE:
            return history_payload
        return performance_payload

    monkeypatch.setattr(sun2000_device, "read_file", mock_read_file)

    active_alarms = await sun2000_device.get_active_alarms()
    assert len(active_alarms) == 1
    assert active_alarms[0].occur_time == expected_occur

    history_alarms = await sun2000_device.get_history_alarms(0, 1)
    assert len(history_alarms) == 1
    assert history_alarms[0].occur_time == expected_occur
    assert history_alarms[0].recover_time == expected_recover

    perf_points = await sun2000_device.get_performance_data(PerformanceRequestType.HOUR_POWER, 0, 1)
    assert len(perf_points) == 1
    assert perf_points[0].time == expected_occur


def test_feature_mask_30316_all_ones_decodes_as_a_mask() -> None:
    """0xFFFF must not decode to None: every bit is set."""
    assert REGISTERS[rn.FEATURE_MASK_30316].decode((0xFFFF,)).value == rv.FeatureMask30316(0xFFFF)


@pytest.mark.parametrize(
    ("register_response", "expected"),
    [
        pytest.param(Result(value=False, unit=None), True, id="readable_false"),
        pytest.param(Result(value=True, unit=None), True, id="readable_true"),
        pytest.param(Result(value=None, unit=None), False, id="invalid_value_none"),
        pytest.param(
            ReadException(_READ_FAILED_MSG, modbus_exception_code=0x03),
            False,
            id="illegal_data_value",
        ),
        pytest.param(
            ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02),
            False,
            id="illegal_data_address",
        ),
    ],
)
async def test_supports_ess_low_power_register_probe(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
    register_response: Result[Any] | Exception,
    *,
    expected: bool,
) -> None:
    """When FEATURE_MASK_30342 bit 4 is set, STORAGE_ESS_LOW_POWER must be readable with a non-None value."""
    await _populate_with_mocked_responses(
        sun2000_device,
        monkeypatch,
        {
            rn.FEATURE_MASK_30342: Result(rv.FeatureMask30342.ESS_LOW_POWER, None),
            rn.STORAGE_ESS_LOW_POWER: register_response,
        },
    )

    assert sun2000_device.supports_ess_low_power is expected


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ConnectionInterruptedException("disconnected"), id="connection_interrupted"),
        pytest.param(TimeoutError(), id="timeout"),
    ],
)
async def test_supports_ess_low_power_probe_propagates_transient_errors(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    """Transient communication errors when probing STORAGE_ESS_LOW_POWER must propagate."""
    with pytest.raises(type(error)):
        await _populate_with_mocked_responses(
            sun2000_device,
            monkeypatch,
            {
                rn.FEATURE_MASK_30342: Result(rv.FeatureMask30342.ESS_LOW_POWER, None),
                rn.STORAGE_ESS_LOW_POWER: error,
            },
        )
