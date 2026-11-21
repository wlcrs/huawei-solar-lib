"""Tests for the LUNA2000 battery pack health registers."""

import pytest
from huawei_solar.exceptions import DecodeError
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv

_HEATING_STATUS_REGISTERS = (
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_HEATING_STATUS,
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_HEATING_STATUS,
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_HEATING_STATUS,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, rv.BatteryPackHeatingStatus.IDLE),
        (1, rv.BatteryPackHeatingStatus.HEATING),
        (2, rv.BatteryPackHeatingStatus.FAULT),
        (0xFFFF, None),
    ],
)
def test_pack_heating_status_decoding(raw: int, expected: rv.BatteryPackHeatingStatus | None) -> None:
    """Known values decode to the enum; the U16 invalid value decodes to None."""
    for name in _HEATING_STATUS_REGISTERS:
        assert REGISTERS[name].decode((raw,)).value == expected


def test_pack_heating_status_unknown_value_fails() -> None:
    """The registers are undocumented: a value this library does not know fails the read instead of being dropped."""
    for name in _HEATING_STATUS_REGISTERS:
        with pytest.raises(DecodeError, match="not a valid BatteryPackHeatingStatus"):
            REGISTERS[name].decode((7,))


def test_pack_health_and_backup_time_values() -> None:
    """Values read on a LUNA2000-S1: pack SOH 98.0 % / 100.0 %; backup time 65535 means unknown."""
    assert REGISTERS[rn.STORAGE_UNIT_1_BATTERY_PACK_1_STATE_OF_HEALTH].decode((980,)).value == 98.0
    assert REGISTERS[rn.STORAGE_UNIT_1_BATTERY_PACK_2_STATE_OF_HEALTH].decode((1000,)).value == 100.0
    assert REGISTERS[rn.STORAGE_ESTIMATED_BACKUP_TIME].decode((65535,)).value is None
    assert REGISTERS[rn.STORAGE_ESTIMATED_BACKUP_TIME].decode((95,)).value == 95


def test_pack_health_registers_sit_next_to_pack_state_of_capacity() -> None:
    """SOH is one register after each pack's state of capacity, so it shares that batch read."""
    for pack in (1, 2, 3):
        soc = REGISTERS[getattr(rn, f"STORAGE_UNIT_1_BATTERY_PACK_{pack}_STATE_OF_CAPACITY")].register
        soh = REGISTERS[getattr(rn, f"STORAGE_UNIT_1_BATTERY_PACK_{pack}_STATE_OF_HEALTH")].register
        assert soh == soc + 1
