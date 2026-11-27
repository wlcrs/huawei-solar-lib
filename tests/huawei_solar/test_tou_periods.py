"""Tests for Huawei LUNA2000 time-of-use periods."""

import logging
import struct

import huawei_solar.register_names as rn
import pytest
from huawei_solar.exceptions import DecodeError, TimeOfUsePeriodsException
from huawei_solar.register_definitions.base import RegisterDefinition
from huawei_solar.register_definitions.periods import ChargeFlag, HUAWEI_LUNA2000_TimeOfUsePeriod
from huawei_solar.registers import REGISTERS

INVERTER_TOU = REGISTERS[rn.STORAGE_HUAWEI_LUNA2000_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS]
EMMA_TOU = REGISTERS[rn.EMMA_TOU_PERIODS]

ALL_DAYS = (True, True, True, True, True, True, True)
SUNDAY = (True, False, False, False, False, False, False)
MONDAY = (False, True, False, False, False, False, False)
TUESDAY = (False, False, True, False, False, False, False)
SATURDAY = (False, False, False, False, False, False, True)


def test_decode_discharge_to_grid_and_load() -> None:
    values = (1, 300, 420, 2, 0b0000010) + (0, 0, 0, 0) * 13
    periods = EMMA_TOU.decode(values).value

    assert periods == [HUAWEI_LUNA2000_TimeOfUsePeriod(300, 420, ChargeFlag.DISCHARGE_TO_GRID_AND_LOAD, MONDAY)]
    assert periods[0].charge_flag is ChargeFlag.DISCHARGE_TO_GRID_AND_LOAD


def test_decode_clamps_period_count(caplog: pytest.LogCaptureFixture) -> None:
    values = (15, *(field for minute in range(14) for field in (minute, minute + 1, 1, 0b1111111)))

    result = INVERTER_TOU.decode(values)

    assert result.value == [
        HUAWEI_LUNA2000_TimeOfUsePeriod(minute, minute + 1, ChargeFlag.DISCHARGE, ALL_DAYS) for minute in range(14)
    ]
    assert any(
        record.levelno == logging.WARNING and record.message == "Device reported 15 TOU periods, clamping to 14"
        for record in caplog.records
    )


def test_decode_skips_inactive_periods(caplog: pytest.LogCaptureFixture) -> None:
    values = (3, 300, 300, 0, 0b0000010, 300, 420, 0, 0, 420, 480, 0, 0b0000010) + (0, 0, 0, 0) * 11

    with caplog.at_level(logging.DEBUG, logger="huawei_solar.register_definitions.periods"):
        result = INVERTER_TOU.decode(values)

    assert result.value == [HUAWEI_LUNA2000_TimeOfUsePeriod(420, 480, ChargeFlag.CHARGE, MONDAY)]
    assert [record.message for record in caplog.records if record.levelno == logging.DEBUG] == [
        "Skipping inactive TOU period 1 (start=300, end=300, week_mask=0x2)",
        "Skipping inactive TOU period 2 (start=300, end=420, week_mask=0x0)",
    ]


def test_decode_rejects_unknown_charge_flag() -> None:
    values = (1, 300, 420, 3, 0b0000010) + (0, 0, 0, 0) * 13

    with pytest.raises(DecodeError, match="Unknown TOU charge flag 3 in period 1"):
        INVERTER_TOU.decode(values)


@pytest.mark.parametrize(("end_time", "week_mask"), [(300, 0b0000010), (420, 0)])
def test_decode_skips_inactive_period_with_unknown_charge_flag(end_time: int, week_mask: int) -> None:
    """An inactive entry is skipped before its flag is looked at, like in the app."""
    values = (1, 300, end_time, 0xFF, week_mask) + (0, 0, 0, 0) * 13

    assert INVERTER_TOU.decode(values).value == []


@pytest.mark.parametrize("register", [INVERTER_TOU, EMMA_TOU], ids=["inverter", "emma"])
def test_wrap_period_round_trip(register: RegisterDefinition[list[HUAWEI_LUNA2000_TimeOfUsePeriod]]) -> None:
    periods = [HUAWEI_LUNA2000_TimeOfUsePeriod(22 * 60, 6 * 60, ChargeFlag.DISCHARGE, ALL_DAYS)]

    encoded = struct.pack(f">{register.format}", *register.encode(periods))

    assert encoded == struct.pack(">4H", 1, 22 * 60, 6 * 60, 0x017F) + bytes(39 * 2)
    assert register.decode(struct.unpack(f">{register.format}", encoded)).value == periods


@pytest.mark.parametrize(("wrap_day", "following_day"), [(MONDAY, TUESDAY), (SATURDAY, SUNDAY)])
def test_wrap_period_overlaps_following_day(
    wrap_day: tuple[bool, bool, bool, bool, bool, bool, bool],
    following_day: tuple[bool, bool, bool, bool, bool, bool, bool],
) -> None:
    periods = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(22 * 60, 6 * 60, ChargeFlag.DISCHARGE, wrap_day),
        HUAWEI_LUNA2000_TimeOfUsePeriod(5 * 60, 7 * 60, ChargeFlag.CHARGE, following_day),
    ]

    with pytest.raises(TimeOfUsePeriodsException, match="TOU periods are overlapping"):
        INVERTER_TOU.encode(periods)


def test_wrap_period_allows_morning_on_selected_day_and_adjacent_periods() -> None:
    periods = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(22 * 60, 6 * 60, ChargeFlag.DISCHARGE, MONDAY),
        HUAWEI_LUNA2000_TimeOfUsePeriod(5 * 60, 7 * 60, ChargeFlag.CHARGE, MONDAY),
        HUAWEI_LUNA2000_TimeOfUsePeriod(21 * 60, 22 * 60, ChargeFlag.CHARGE, MONDAY),
        HUAWEI_LUNA2000_TimeOfUsePeriod(6 * 60, 7 * 60, ChargeFlag.CHARGE, TUESDAY),
    ]

    assert INVERTER_TOU.encode(periods)[0] == len(periods)


def test_encode_allows_24_hour_end_time() -> None:
    period = HUAWEI_LUNA2000_TimeOfUsePeriod(23 * 60, 24 * 60, ChargeFlag.DISCHARGE, MONDAY)

    assert INVERTER_TOU.encode([period])[:5] == (1, 1380, 1440, 1, 0b0000010)


def test_encode_rejects_equal_start_and_end_times() -> None:
    period = HUAWEI_LUNA2000_TimeOfUsePeriod(300, 300, ChargeFlag.DISCHARGE, MONDAY)

    with pytest.raises(TimeOfUsePeriodsException, match="start-time equals end-time"):
        INVERTER_TOU.encode([period])


def test_encode_rejects_more_than_fourteen_periods() -> None:
    periods = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(minute, minute + 1, ChargeFlag.DISCHARGE, MONDAY) for minute in range(15)
    ]

    with pytest.raises(TimeOfUsePeriodsException, match="Too many TOU periods: got 15, maximum is 14"):
        INVERTER_TOU.encode(periods)


def test_encode_discharge_to_grid_and_load_for_inverter() -> None:
    period = HUAWEI_LUNA2000_TimeOfUsePeriod(300, 420, ChargeFlag.DISCHARGE_TO_GRID_AND_LOAD, MONDAY)

    assert INVERTER_TOU.encode([period])[:5] == (1, 300, 420, 2, 0b0000010)


def test_encode_rejects_discharge_to_grid_and_load_for_emma() -> None:
    period = HUAWEI_LUNA2000_TimeOfUsePeriod(300, 420, ChargeFlag.DISCHARGE_TO_GRID_AND_LOAD, MONDAY)

    with pytest.raises(TimeOfUsePeriodsException, match="Discharge to grid and load is unsupported"):
        EMMA_TOU.encode([period])


def test_decode_count_with_high_bit_reads_no_periods() -> None:
    """The app reads the count as a signed short: 0xFFFF gives no periods, not 14."""
    values = (0xFFFF, 300, 420, 0, 0b0000010) + (0, 0, 0, 0) * 13

    assert INVERTER_TOU.decode(values).value == []


def test_encode_rejects_24_00_start() -> None:
    period = HUAWEI_LUNA2000_TimeOfUsePeriod(24 * 60, 6 * 60, ChargeFlag.CHARGE, MONDAY)

    with pytest.raises(TimeOfUsePeriodsException, match="start-time is 24:00"):
        INVERTER_TOU.encode([period])


def test_encode_rejects_unknown_charge_flag() -> None:
    period = HUAWEI_LUNA2000_TimeOfUsePeriod(300, 420, 3, MONDAY)  # type: ignore[arg-type]

    with pytest.raises(TimeOfUsePeriodsException, match="unknown charge flag 3"):
        INVERTER_TOU.encode([period])


def test_wrap_period_ending_at_midnight_leaves_next_day_free() -> None:
    periods = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(22 * 60, 0, ChargeFlag.DISCHARGE, MONDAY),
        HUAWEI_LUNA2000_TimeOfUsePeriod(0, 60, ChargeFlag.CHARGE, TUESDAY),
    ]

    assert INVERTER_TOU.encode(periods)[0] == len(periods)


def test_two_wrap_periods_overlap_through_the_spill() -> None:
    """Monday 22:00-06:00 spills into Tuesday 00:00-06:00; Tuesday 23:00-05:00 is fine, Monday 23:00-01:00 is not."""
    monday_night = HUAWEI_LUNA2000_TimeOfUsePeriod(22 * 60, 6 * 60, ChargeFlag.DISCHARGE, MONDAY)

    assert (
        INVERTER_TOU.encode(
            [monday_night, HUAWEI_LUNA2000_TimeOfUsePeriod(23 * 60, 5 * 60, ChargeFlag.CHARGE, TUESDAY)]
        )[0]
        == 2
    )
    with pytest.raises(TimeOfUsePeriodsException, match="TOU periods are overlapping"):
        INVERTER_TOU.encode([monday_night, HUAWEI_LUNA2000_TimeOfUsePeriod(23 * 60, 60, ChargeFlag.CHARGE, MONDAY)])


def test_valid_period_after_unknown_flag_still_fails_the_read() -> None:
    """An unknown flag fails the whole read (the app would drop that row and keep the others)."""
    values = (2, 300, 420, 3, 0b0000010, 420, 480, 0, 0b0000010) + (0, 0, 0, 0) * 12

    with pytest.raises(DecodeError, match="Unknown TOU charge flag 3 in period 1"):
        INVERTER_TOU.decode(values)


def test_wrap_spill_collides_with_another_wrap_on_the_next_day() -> None:
    """Monday 22:00-06:00 spills into Tuesday 00:00-06:00, which Tuesday 02:00-01:00 (wrapping) overlaps."""
    periods = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(22 * 60, 6 * 60, ChargeFlag.DISCHARGE, MONDAY),
        HUAWEI_LUNA2000_TimeOfUsePeriod(2 * 60, 60, ChargeFlag.CHARGE, TUESDAY),
    ]

    with pytest.raises(TimeOfUsePeriodsException, match="TOU periods are overlapping"):
        INVERTER_TOU.encode(periods)
