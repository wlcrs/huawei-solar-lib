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


def test_active_power_control_mode_remote_output_control() -> None:
    """47415 = 200 is "Remote output control" in the app."""
    assert (
        REGISTERS[rn.ACTIVE_POWER_CONTROL_MODE].decode((200,)).value == rv.ActivePowerControlMode.REMOTE_OUTPUT_CONTROL
    )


def test_storage_working_mode_still_rejects_unknown_values() -> None:
    """Values the app does not list still fail the read."""
    with pytest.raises(DecodeError):
        REGISTERS[rn.STORAGE_UNIT_1_WORKING_MODE_B].decode((13,))
