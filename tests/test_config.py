"""check if the register config is correct"""

import logging

from huawei_solar.registers import REGISTERS, TargetDevice

_LOGGER = logging.getLogger(__name__)


def test_register_config():
    """Parse all REGISTERS and check for correct order and potential overlaps"""
    registers = [r for r in REGISTERS.values() if TargetDevice.SUN2000 in r.target_device]
    registers.sort(key=lambda x: x.register)

    for idx in range(1, len(registers)):
        if registers[idx].register in [32066, 32072, 40000, 47028, 47255]:
            # skip these registers, as they have multiple entries
            continue
        if registers[idx - 1].register + registers[idx - 1].length > registers[idx].register:
            raise ValueError(
                f"Requested registers must be in monotonically increasing order, "
                f"but {registers[idx-1].register} + {registers[idx-1].length} > {registers[idx].register}!",
            )
        if registers[idx - 1].register + registers[idx - 1].length < registers[idx].register:
            _LOGGER.info(
                "There is a gap between %s and %s!",
                {registers[idx - 1].register},
                {registers[idx].register},
            )


def test_register_config_emma():
    """Parse all REGISTERS and check for correct order and potential overlaps"""
    registers = [r for r in REGISTERS.values() if TargetDevice.EMMA in r.target_device]
    registers.sort(key=lambda x: x.register)

    for idx in range(1, len(registers)):
        if registers[idx].register in []:
            # skip these registers, as they have multiple entries
            continue
        if registers[idx - 1].register + registers[idx - 1].length > registers[idx].register:
            raise ValueError(
                f"Requested registers must be in monotonically increasing order, "
                f"but {registers[idx-1].register} + {registers[idx-1].length} > {registers[idx].register}!",
            )
        if registers[idx - 1].register + registers[idx - 1].length < registers[idx].register:
            _LOGGER.info(
                "There is a gap between %s and %s!",
                {registers[idx - 1].register},
                {registers[idx].register},
            )
