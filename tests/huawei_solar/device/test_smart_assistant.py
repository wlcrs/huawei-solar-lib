"""Tests for the SmartAssistantDevice class."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from huawei_solar import AsyncHuaweiSolarClient
from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.device import EMMADevice, SmartAssistantDevice
from huawei_solar.register_definitions import Result


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
