"""Tests for the SUN2000Device class."""

from typing import Any

import huawei_solar.register_values as rv
import pytest
from huawei_solar.exceptions import ReadException, WriteException
from huawei_solar.register_values import StorageProductModel

from huawei_solar import register_names as rn
from huawei_solar.device import SUN2000Device
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

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        if name == rn.NB_PV_STRINGS:
            return Result(2, None)
        if name == rn.NB_OPTIMIZERS:
            raise ReadException(_READ_FAILED_MSG)
        if name == rn.STORAGE_UNIT_1_PRODUCT_MODEL:
            return Result(StorageProductModel.HUAWEI_LUNA2000, None)
        if name == rn.STORAGE_UNIT_2_PRODUCT_MODEL:
            return Result(StorageProductModel.NONE, None)
        if name == rn.FEATURE_MASK_3:
            return Result(rv.FeatureMask3.CAPACITY_CONTROL, None)
        if name == rn.FEATURE_MASK_30342:
            return Result(rv.FeatureMask30342.ESS_LOW_POWER, None)
        if name == rn.METER_STATUS:
            raise ReadException(_READ_FAILED_MSG)
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(sun2000_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(sun2000_device, "get", mock_get)
    await sun2000_device._populate_additional_fields()

    assert sun2000_device.supports_capacity_control is True
    assert sun2000_device.supports_ess_low_power is True


async def test_supports_ess_low_power_when_bit_cleared(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When FEATURE_MASK_30342 has bit 4 cleared, supports_ess_low_power is False."""

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        if name == rn.NB_PV_STRINGS:
            return Result(2, None)
        if name == rn.NB_OPTIMIZERS:
            raise ReadException(_READ_FAILED_MSG)
        if name == rn.STORAGE_UNIT_1_PRODUCT_MODEL:
            return Result(StorageProductModel.HUAWEI_LUNA2000, None)
        if name == rn.STORAGE_UNIT_2_PRODUCT_MODEL:
            return Result(StorageProductModel.NONE, None)
        if name == rn.FEATURE_MASK_3:
            return Result(rv.FeatureMask3(0), None)
        if name == rn.FEATURE_MASK_30342:
            return Result(rv.FeatureMask30342(0), None)
        if name == rn.METER_STATUS:
            raise ReadException(_READ_FAILED_MSG)
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(sun2000_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(sun2000_device, "get", mock_get)
    await sun2000_device._populate_additional_fields()

    assert sun2000_device.supports_capacity_control is False
    assert sun2000_device.supports_ess_low_power is False


async def test_supports_ess_low_power_when_read_exception(
    sun2000_device: SUN2000Device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When reading FEATURE_MASK_30342 raises ReadException, supports_ess_low_power is False."""

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SN123", None), Result("PN123", None), Result("V100", None), Result("V100", None)]

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        if name == rn.NB_PV_STRINGS:
            return Result(2, None)
        if name == rn.NB_OPTIMIZERS:
            raise ReadException(_READ_FAILED_MSG)
        if name == rn.STORAGE_UNIT_1_PRODUCT_MODEL:
            return Result(StorageProductModel.HUAWEI_LUNA2000, None)
        if name == rn.STORAGE_UNIT_2_PRODUCT_MODEL:
            return Result(StorageProductModel.NONE, None)
        if name == rn.FEATURE_MASK_3:
            raise ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02)
        if name == rn.FEATURE_MASK_30342:
            raise ReadException(_READ_FAILED_MSG, modbus_exception_code=0x02)
        if name == rn.METER_STATUS:
            raise ReadException(_READ_FAILED_MSG)
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(sun2000_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(sun2000_device, "get", mock_get)
    await sun2000_device._populate_additional_fields()

    assert sun2000_device.supports_capacity_control is False
    assert sun2000_device.supports_ess_low_power is False
