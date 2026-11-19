"""Check if the register config is correct."""

import logging

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
