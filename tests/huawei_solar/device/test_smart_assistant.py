"""Tests for the SmartAssistantDevice class."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from huawei_solar.registers import REGISTERS

from huawei_solar import AsyncHuaweiSolarClient
from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.device import EMMADevice, SmartAssistantDevice
from huawei_solar.register_definitions import Result, TargetDevice


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("SmartAssistant", True),
        ("SmartAssistant SA4H", True),
        ("SA4H", True),
        ("SmartHEMS", False),
        ("SUN2000-10KTL-M1", False),
    ],
)
def test_supports_device(model_name: str, *, expected: bool) -> None:
    """SmartAssistantDevice matches SmartAssistant and SA4H model names."""
    assert SmartAssistantDevice.supports_device(model_name) is expected


async def test_create_smart_assistant_device(monkeypatch: pytest.MonkeyPatch) -> None:
    """SmartAssistantDevice inherits EMMADevice field population and feature detection."""
    client = AsyncMock(spec=AsyncHuaweiSolarClient)
    client.unit_id = 0
    utc_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[Any]]:
        if names == [rn.SERIAL_NUMBER, rn.EMMA_SOFTWARE_VERSION]:
            return [Result("SA4H123", None), Result("V100R025C00", None)]
        msg = f"Unexpected get_multiple: {names}"
        raise AssertionError(msg)

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        responses: dict[rn.RegisterName, Result[Any]] = {
            rn.EMMA_MODEL: Result("SA4H", None),
            rn.EMMA_LOCAL_TIME: Result(utc_time, None),
            rn.EMMA_SYSTEM_TIME: Result(utc_time, None),
            rn.EMMA_BATTERY_PRODUCT_MODEL: Result(rv.StorageProductModel.HUAWEI_LUNA2000, None),
            rn.EMMA_FEATURE_MASK_30164: Result(rv.EmmaFeatureMask30164(0), None),
        }
        if name in responses:
            return responses[name]
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(client, "get", mock_get)

    device = await SmartAssistantDevice.create(client, model_name="SmartAssistant")

    assert isinstance(device, EMMADevice)
    assert device.serial_number == "SA4H123"
    assert device.software_version == "V100R025C00"
    assert device.model_name == "SA4H"
    assert device.has_battery is True
    assert device.supports_capacity_control is True
    assert device.supports_power_limited_grid_connection is True
    assert device.supports_di_scheduling is True


def test_smart_assistant_registers_target_and_codec() -> None:
    """Shared and HEMS-specific registers target SMART_ASSISTANT and encode/decode properly."""
    assert TargetDevice.SMART_ASSISTANT in REGISTERS[rn.MODEL_NAME].target_device
    assert TargetDevice.SMART_ASSISTANT in REGISTERS[rn.SERIAL_NUMBER].target_device
    assert TargetDevice.SMART_ASSISTANT in REGISTERS[rn.EMMA_MODEL].target_device

    backup_time = REGISTERS[rn.HEMS_BACKUP_TIME]
    assert TargetDevice.SMART_ASSISTANT in backup_time.target_device
    assert backup_time.decode((120,)) == Result(120, "min")

    charge_from_ac = REGISTERS[rn.HEMS_CHARGE_FROM_AC]
    assert TargetDevice.SMART_ASSISTANT in charge_from_ac.target_device
    assert charge_from_ac.writeable is True
    assert charge_from_ac.encode(True) == (1,)  # noqa: FBT003
    assert charge_from_ac.decode((1,)) == Result(value=True, unit=None)

    off_grid_soc = REGISTERS[rn.HEMS_OFF_GRID_BACKUP_POWER_SOC]
    assert TargetDevice.SMART_ASSISTANT in off_grid_soc.target_device
    assert off_grid_soc.writeable is True
    assert off_grid_soc.encode(20.5) == (205,)
    assert off_grid_soc.decode((205,)) == Result(20.5, "%")

    ess_grid_power = REGISTERS[rn.HEMS_ESS_GRID_CHARGING_POWER]
    assert TargetDevice.SMART_ASSISTANT in ess_grid_power.target_device
    assert ess_grid_power.writeable is True
    assert ess_grid_power.encode(5000) == (5000,)
    assert ess_grid_power.decode((5000,)) == Result(5000, "W")


async def test_smart_assistant_get_and_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """SmartAssistantDevice can read and write HEMS registers."""
    client = AsyncMock(spec=AsyncHuaweiSolarClient)
    client.unit_id = 0
    device = SmartAssistantDevice(client=client, model_name="SmartAssistant")

    monkeypatch.setattr(client, "get", AsyncMock(return_value=Result(45, "min")))
    monkeypatch.setattr(client, "set", AsyncMock(return_value=True))

    assert await device.get(rn.HEMS_BACKUP_TIME) == Result(45, "min")
    assert await device.set(rn.HEMS_CHARGE_FROM_AC, value=True) is True
