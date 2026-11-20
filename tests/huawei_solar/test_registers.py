"""Check if the register config is correct."""

import logging

import huawei_solar.register_values as rv
import pytest
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar.register_definitions import TargetDevice

_LOGGER = logging.getLogger(__name__)


@pytest.mark.parametrize("target_device", list(TargetDevice))
def test_register_config(target_device: TargetDevice) -> None:
    """Parse all REGISTERS and check for correct order and potential overlaps."""
    registers = [r for r in REGISTERS.values() if target_device in r.target_device]
    registers.sort(key=lambda x: x.register)

    for idx in range(1, len(registers)):
        if registers[idx].register in [32066, 32072, 40000]:
            # skip these registers, as they have multiple entries
            continue
        if registers[idx - 1].register + registers[idx - 1].length > registers[idx].register:
            msg = (
                f"Requested registers must be in monotonically increasing order, "
                f"but {registers[idx - 1].register} + {registers[idx - 1].length} > {registers[idx].register}!"
            )
            raise ValueError(msg)
        if registers[idx - 1].register + registers[idx - 1].length < registers[idx].register:
            _LOGGER.info(
                "There is a gap between %s and %s!",
                {registers[idx - 1].register},
                {registers[idx].register},
            )


def test_all_register_names_have_a_register() -> None:
    """Check that all register names have a corresponding register defined."""
    register_names_without_register = []

    for register_name in dir(rn):
        if register_name.startswith("_"):
            continue
        register_value = getattr(rn, register_name)
        if not isinstance(register_value, str):
            continue
        if register_value not in REGISTERS:
            register_names_without_register.append(register_name)

    assert not register_names_without_register, f"Register names without a register: {register_names_without_register}"


def test_storage_unit_1_state_of_health_register() -> None:
    """Verify STORAGE_UNIT_1_STATE_OF_HEALTH (37005) decoding."""
    register = REGISTERS[rn.STORAGE_UNIT_1_STATE_OF_HEALTH]
    decoded = register.decode((985,))
    assert decoded.value == 98.5
    assert decoded.unit == "%"
    assert register.decode((0xFFFF,)).value is None


def test_feature_mask_30283_register() -> None:
    """Verify FEATURE_MASK_30283 (30283) decoding."""
    register = REGISTERS[rn.FEATURE_MASK_30283]
    assert register.decode((1 << 8,)).value == rv.FeatureMask30283.THIRD_PARTY_CONTROL
    assert register.decode((1 << 12,)).value == rv.FeatureMask30283.CURRENT_LIMITING_GRID_CONNECTION
    assert register.decode((1 << 20,)).value == rv.FeatureMask30283.THREE_PHASE_UNBALANCE_CONTROL
    assert register.decode((0xFFFFFFFF,)).value is None


def test_feature_mask_30306_register() -> None:
    """Verify FEATURE_MASK_30306 (30306) decoding."""
    register = REGISTERS[rn.FEATURE_MASK_30306]
    assert register.decode((1 << 9,)).value == rv.FeatureMask30306.BATTERY_RECHARGE
    assert register.decode((1 << 10,)).value == rv.FeatureMask30306.BATTERY_SAFETY_SELF_CHECK
    assert register.decode((1 << 15,)).value == rv.FeatureMask30306.DISCHARGE_POWER_ADJUSTMENT
    assert register.decode((0xFFFF,)).value is None
