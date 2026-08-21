"""Tests for the SUN2000Device class."""

import huawei_solar.register_names as rn
import pytest
from huawei_solar.exceptions import WriteException

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

