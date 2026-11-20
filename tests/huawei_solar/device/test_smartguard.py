"""Tests for the SmartGuard device."""

import asyncio
from typing import Any
from unittest.mock import Mock, patch

import pytest
from huawei_solar.device.emma import EMMADevice
from huawei_solar.device.smartguard import SmartGuardDevice
from huawei_solar.exceptions import ConnectionInterruptedException, DecodeError, ReadException
from huawei_solar.modbus_client import AsyncHuaweiSolarClient
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.device import create_sub_device_instance
from huawei_solar.register_definitions import Result


def _emma_with_sub_client(responses: dict[rn.RegisterName, Any]) -> tuple[Mock, Mock]:
    primary_client = Mock()
    primary_client.unit_id = 0
    sub_client = Mock()
    sub_client.unit_id = 2
    primary_client.for_unit_id = Mock(return_value=sub_client)

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        value = responses.get(name, ReadException("Failed to read register"))
        if isinstance(value, Exception):
            raise value
        return Result(value, None)

    sub_client.get = mock_get

    primary_device = Mock(spec=EMMADevice)
    primary_device.client = primary_client
    primary_device.update_lock = asyncio.Lock()
    primary_device.serial_number = "EMMA_SN"
    return primary_device, sub_client


@pytest.mark.parametrize(
    ("feature_mask", "supports_grid_switchover"),
    [(31, True), (30, False)],
)
async def test_smartguard_populates_fields_without_deadlock(
    monkeypatch: pytest.MonkeyPatch,
    feature_mask: int,
    *,
    supports_grid_switchover: bool,
) -> None:
    """The SmartGuard reads its fields while the EMMA's update_lock is held by create_sub_device_instance."""
    primary_device, _ = _emma_with_sub_client(
        {
            rn.SMARTGUARD_SOFTWARE_VERSION: "V100R024C00SPC100",
            rn.SMARTGUARD_PHASE_TYPE: rv.SmartGuardPhaseType.THREE_PHASE,
            rn.SMARTGUARD_FEATURE_MASK: feature_mask,
        }
    )

    async def mock_detect(client: Any) -> tuple[type, str]:  # noqa: ANN401
        return SmartGuardDevice, "SmartGuard-63A-T0"

    monkeypatch.setattr("huawei_solar.device.detect_device_type", mock_detect)

    device = await asyncio.wait_for(create_sub_device_instance(primary_device, 2), timeout=1)
    assert isinstance(device, SmartGuardDevice)

    assert isinstance(device, SmartGuardDevice)
    assert device.serial_number == "EMMA_SN_smartguard_2"
    assert device.software_version == "V100R024C00SPC100"
    assert device.phase_type == rv.SmartGuardPhaseType.THREE_PHASE
    assert device.supports_grid_switchover is supports_grid_switchover


async def test_smartguard_tolerates_unreadable_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Older SmartGuards that do not answer the extra registers still get created."""
    primary_device, _ = _emma_with_sub_client({})

    async def mock_detect(client: Any) -> tuple[type, str]:  # noqa: ANN401
        return SmartGuardDevice, "SmartGuard-63A-S0"

    monkeypatch.setattr("huawei_solar.device.detect_device_type", mock_detect)

    device = await asyncio.wait_for(create_sub_device_instance(primary_device, 2), timeout=1)
    assert isinstance(device, SmartGuardDevice)

    assert device.software_version is None
    assert device.phase_type is None
    assert device.supports_grid_switchover is False


async def test_smartguard_reports_empty_software_version_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """An all-zero version string must not show up as an empty software version."""
    primary_device, _ = _emma_with_sub_client({rn.SMARTGUARD_SOFTWARE_VERSION: ""})

    async def mock_detect(client: Any) -> tuple[type, str]:  # noqa: ANN401
        return SmartGuardDevice, "SmartGuard-63A-T0"

    monkeypatch.setattr("huawei_solar.device.detect_device_type", mock_detect)

    device = await asyncio.wait_for(create_sub_device_instance(primary_device, 2), timeout=1)
    assert isinstance(device, SmartGuardDevice)

    assert device.software_version is None


async def test_smartguard_tolerates_probe_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A SmartGuard that ignores unknown addresses (timeouts) is still created, without the optional fields."""
    primary_device, _ = _emma_with_sub_client(
        {rn.SMARTGUARD_PHASE_TYPE: TimeoutError(), rn.SMARTGUARD_FEATURE_MASK: TimeoutError()}
    )

    async def mock_detect(client: Any) -> tuple[type, str]:  # noqa: ANN401
        return SmartGuardDevice, "SmartGuard-63A-T0"

    monkeypatch.setattr("huawei_solar.device.detect_device_type", mock_detect)

    device = await asyncio.wait_for(create_sub_device_instance(primary_device, 2), timeout=1)
    assert isinstance(device, SmartGuardDevice)

    assert device.phase_type is None
    assert device.supports_grid_switchover is False


async def test_smartguard_creation_fails_when_the_connection_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dropped connection is not mistaken for a missing register: creation fails so setup can retry."""
    primary_device, _ = _emma_with_sub_client({rn.SMARTGUARD_PHASE_TYPE: ConnectionInterruptedException("lost")})

    async def mock_detect(client: Any) -> tuple[type, str]:  # noqa: ANN401
        return SmartGuardDevice, "SmartGuard-63A-T0"

    monkeypatch.setattr("huawei_solar.device.detect_device_type", mock_detect)

    with pytest.raises(ConnectionInterruptedException):
        await asyncio.wait_for(create_sub_device_instance(primary_device, 2), timeout=1)
    assert not primary_device.update_lock.locked()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1, rv.SmartGuardStatus.ON_GRID),
        (3, rv.SmartGuardStatus.OFF_GRID_INVERTER),
    ],
)
def test_status_decodes_known_values(raw: int, expected: rv.SmartGuardStatus) -> None:
    """The status decodes like the library's other enum registers."""
    assert REGISTERS[rn.SMARTGUARD_STATUS].decode((raw,)).value == expected


def test_status_unknown_value_fails() -> None:
    """The register is undocumented: a value this library does not know fails the read instead of being dropped."""
    with pytest.raises(DecodeError, match="not a valid SmartGuardStatus"):
        REGISTERS[rn.SMARTGUARD_STATUS].decode((8,))


def test_status_invalid_value_decodes_to_none() -> None:
    """0xFFFF is the U16 invalid value."""
    assert REGISTERS[rn.SMARTGUARD_STATUS].decode((0xFFFF,)).value is None


async def test_grid_switchover_writes_a_single_register(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """The switchover goes out as one register write of 0 (off-grid) or 1 (on-grid) to 40021."""
    with patch.object(huawei_solar, "write_single_register", return_value=0) as write_single_register:
        success = await huawei_solar.set(rn.SMARTGUARD_GRID_SWITCHOVER, rv.SmartGuardGridSwitchover.OFF_GRID)

    assert success is True
    write_single_register.assert_awaited_once_with(40021, 0)


def test_grid_switchover_register_is_write_only() -> None:
    """The switchover command cannot be read back; the status register confirms it."""
    reg = REGISTERS[rn.SMARTGUARD_GRID_SWITCHOVER]
    assert reg.writeable
    assert not reg.readable
    assert reg.register == 40021
    assert reg.encode(rv.SmartGuardGridSwitchover.OFF_GRID) == (0,)
    assert reg.encode(rv.SmartGuardGridSwitchover.ON_GRID) == (1,)


def test_off_grid_statuses() -> None:
    """Statuses 2, 3 and 4 are the off-grid states the app waits for after switching."""
    assert {int(s) for s in rv.SMARTGUARD_OFF_GRID_STATUSES} == {2, 3, 4}
