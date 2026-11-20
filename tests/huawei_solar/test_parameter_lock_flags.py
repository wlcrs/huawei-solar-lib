"""Tests for the inverter settings an energy manager holds (30298 + 30341 bit 12)."""

from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv


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
