"""Tests for the inverter settings an energy manager holds (30298 + 30341 bit 12)."""

from typing import Any

import pytest
from huawei_solar.device.sun2000 import SUN2000Device
from huawei_solar.exceptions import ReadException
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.register_definitions import Result


def test_parameter_lock_registers() -> None:
    """Both registers are single read-only U16 registers on the inverter."""
    for name, address in ((rn.PARAMETER_LOCK_FLAGS, 30298), (rn.FEATURE_MASK_30341, 30341)):
        register = REGISTERS[name]
        assert (register.register, register.length, register.writeable) == (address, 1, False)


def test_reference_plant_values() -> None:
    """SUN2000-12K-MAP0 behind an EMMA-A02 (2026-11-15): 30298 = 0x00E7, 30341 = 0x3023."""
    flags = REGISTERS[rn.PARAMETER_LOCK_FLAGS].decode((0x00E7,)).value
    mask = REGISTERS[rn.FEATURE_MASK_30341].decode((0x3023,)).value

    assert mask & rv.FeatureMask30341.PARAMETER_LOCK
    assert flags == (
        rv.ParameterLockFlags.ACTIVE_POWER_PERCENTAGE_DERATING
        | rv.ParameterLockFlags.ACTIVE_POWER_DERATING_KW
        | rv.ParameterLockFlags.ACTIVE_POWER_FIXED_VALUE_DERATING
        | rv.ParameterLockFlags.CHARGE_FROM_GRID
        | rv.ParameterLockFlags.GRID_CHARGE_MAXIMUM_POWER
        | rv.ParameterLockFlags.GRID_CHARGE_CUTOFF_SOC
    )
    assert not flags & rv.ParameterLockFlags.END_OF_CHARGE_SOC


def test_invalid_value_decodes_to_none() -> None:
    """0xFFFF is the U16 invalid value."""
    assert REGISTERS[rn.PARAMETER_LOCK_FLAGS].decode((0xFFFF,)).value is None


def _mock_get(
    monkeypatch: pytest.MonkeyPatch,
    device: SUN2000Device,
    responses: dict[rn.RegisterName, Result[Any] | Exception],
) -> list[rn.RegisterName]:
    requested: list[rn.RegisterName] = []

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        requested.append(name)
        response = responses[name]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(device.client, "get", mock_get)
    return requested


async def test_held_parameters_read_when_mask_bit_set(
    sun2000_device: SUN2000Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With bit 12 of 30341 set, 30298 tells which settings the energy manager holds."""
    _mock_get(
        monkeypatch,
        sun2000_device,
        {
            rn.FEATURE_MASK_30341: Result(rv.FeatureMask30341(0x3023), None),
            rn.PARAMETER_LOCK_FLAGS: Result(rv.ParameterLockFlags(0x00E7), None),
        },
    )

    await sun2000_device._populate_parameters_held_by_energy_manager()

    assert sun2000_device.parameters_held_by_energy_manager == rv.ParameterLockFlags(0x00E7)


async def test_held_parameters_ignored_when_mask_bit_cleared(
    sun2000_device: SUN2000Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without bit 12 of 30341, 30298 is not in force and is not read."""
    requested = _mock_get(
        monkeypatch,
        sun2000_device,
        {rn.FEATURE_MASK_30341: Result(rv.FeatureMask30341(0x2023), None)},
    )

    await sun2000_device._populate_parameters_held_by_energy_manager()

    assert sun2000_device.parameters_held_by_energy_manager == rv.ParameterLockFlags(0)
    assert requested == [rn.FEATURE_MASK_30341]


async def test_held_parameters_empty_when_mask_not_supported(
    sun2000_device: SUN2000Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An inverter that rejects 30341 holds nothing for an energy manager."""
    requested = _mock_get(
        monkeypatch,
        sun2000_device,
        {rn.FEATURE_MASK_30341: ReadException("Illegal data address", modbus_exception_code=0x02)},
    )

    await sun2000_device._populate_parameters_held_by_energy_manager()

    assert sun2000_device.parameters_held_by_energy_manager == rv.ParameterLockFlags(0)
    assert requested == [rn.FEATURE_MASK_30341]


async def test_held_parameters_empty_when_flags_invalid(
    sun2000_device: SUN2000Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With bit 12 set but 30298 reading 0xFFFF (decoded to None), nothing is held."""
    requested = _mock_get(
        monkeypatch,
        sun2000_device,
        {
            rn.FEATURE_MASK_30341: Result(rv.FeatureMask30341(0x3023), None),
            rn.PARAMETER_LOCK_FLAGS: Result(None, None),
        },
    )

    await sun2000_device._populate_parameters_held_by_energy_manager()

    assert sun2000_device.parameters_held_by_energy_manager == rv.ParameterLockFlags(0)
    assert requested == [rn.FEATURE_MASK_30341, rn.PARAMETER_LOCK_FLAGS]


async def test_held_parameters_empty_when_flags_unreadable(
    sun2000_device: SUN2000Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With bit 12 set but 30298 rejected, nothing is held and setup continues."""
    _mock_get(
        monkeypatch,
        sun2000_device,
        {
            rn.FEATURE_MASK_30341: Result(rv.FeatureMask30341(0x3023), None),
            rn.PARAMETER_LOCK_FLAGS: ReadException("Illegal data address", modbus_exception_code=0x02),
        },
    )

    await sun2000_device._populate_parameters_held_by_energy_manager()

    assert sun2000_device.parameters_held_by_energy_manager == rv.ParameterLockFlags(0)
