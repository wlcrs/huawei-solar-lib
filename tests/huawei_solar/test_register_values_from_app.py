"""Enum values that the FusionSolar app knows (app 26.2.6, inverter.db)."""

import pytest
from huawei_solar.exceptions import DecodeError
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv


def test_storage_working_mode_third_party_dispatch() -> None:
    """37006 = 12 is "Third-party dispatch" in the app."""
    assert (
        REGISTERS[rn.STORAGE_UNIT_1_WORKING_MODE_B].decode((12,)).value == rv.StorageWorkingModesB.THIRD_PARTY_DISPATCH
    )


@pytest.mark.parametrize(
    "mode", [rv.ActivePowerControlMode.DI_ACTIVE_SCHEDULING, rv.ActivePowerControlMode.REMOTE_OUTPUT_CONTROL]
)
def test_inverter_active_power_control_modes(mode: rv.ActivePowerControlMode) -> None:
    register = REGISTERS[rn.ACTIVE_POWER_CONTROL_MODE]
    assert register.decode((mode.value,)).value is mode
    assert register.encode(mode) == (mode.value,)


@pytest.mark.parametrize(
    ("code", "mode"),
    [
        (0, rv.EmmaActivePowerControlMode.UNLIMITED),
        (5, rv.EmmaActivePowerControlMode.ZERO_POWER_GRID_CONNECTION),
        (6, rv.EmmaActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_WATT),
        (7, rv.EmmaActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_PERCENT),
    ],
)
def test_emma_active_power_control_mode_decodes_to_enum(code: int, mode: rv.EmmaActivePowerControlMode) -> None:
    register = REGISTERS[rn.EMMA_POWER_CONTROL_MODE_AT_GRID_CONNECTION_POINT]
    assert register.decode((code,)).value is mode


def test_emma_active_power_control_mode_rejects_unknown_value() -> None:
    register = REGISTERS[rn.EMMA_POWER_CONTROL_MODE_AT_GRID_CONNECTION_POINT]
    with pytest.raises(DecodeError, match="not a valid EmmaActivePowerControlMode"):
        register.decode((1,))


def test_storage_working_mode_still_rejects_unknown_values() -> None:
    """Values the app does not list still fail the read."""
    with pytest.raises(DecodeError):
        REGISTERS[rn.STORAGE_UNIT_1_WORKING_MODE_B].decode((13,))
