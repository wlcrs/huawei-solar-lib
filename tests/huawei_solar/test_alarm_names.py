"""Tests for the names, levels and manual-clear flags of alarms read from the alarm files."""

import struct
from datetime import UTC, datetime

import pytest
from huawei_solar.alarm_names import (
    EMMA_ALARM_CODES,
    HUAWEI_FILE_ALARM_CODES,
    MANUAL_CLEAR_ALARMS,
    SCHARGER_ALARM_CODES,
    SMARTGUARD_ALARM_CODES,
    is_manual_clear_alarm,
)
from huawei_solar.files import ActiveAlarm, ActiveAlarmsDataFile, AlarmLevel, HistoryAlarmsDataFile, lookup_alarm
from huawei_solar.register_values import HUAWEI_ALARM_CODES

from huawei_solar import HUAWEI_FILE_ALARM_CODES as EXPORTED_FILE_ALARM_CODES

OCCUR = datetime(2026, 11, 15, 3, 10, tzinfo=UTC)
EMMA_4006 = bytes.fromhex("02 01 00 00 06 00 a6 0f 88 22 f9 6a 00 00 00 00 01 00 00 02")


def _alarm(alarm_id: int, control_word: int = 0x0001, reason_id: int = 1) -> ActiveAlarm:
    return ActiveAlarm(
        serial_no=1,
        equip_id=0,
        alarm_id=alarm_id,
        occur_time=OCCUR,
        alarm_param=0,
        control_word=control_word,
        reason_id=reason_id,
    )


def test_tables_cover_the_three_families() -> None:
    assert len(EMMA_ALARM_CODES) == 33
    assert len(SMARTGUARD_ALARM_CODES) == 13
    assert len(SCHARGER_ALARM_CODES) == 32
    assert len(HUAWEI_FILE_ALARM_CODES) == 78
    assert EXPORTED_FILE_ALARM_CODES is HUAWEI_FILE_ALARM_CODES


def test_tables_are_consistent() -> None:
    families = [EMMA_ALARM_CODES, SMARTGUARD_ALARM_CODES, SCHARGER_ALARM_CODES]
    assert sum(len(family) for family in families) == len(HUAWEI_FILE_ALARM_CODES)
    assert not set(HUAWEI_FILE_ALARM_CODES) & set(HUAWEI_ALARM_CODES)
    for alarm_id, alarm in HUAWEI_FILE_ALARM_CODES.items():
        assert alarm.id == alarm_id
        assert alarm.level in {"Critical", "Major", "Minor", "Warning"}
        assert alarm.name
        assert alarm.name == alarm.name.strip()
        assert not alarm.name.endswith(".")


def test_emma_alarm_name_from_file() -> None:
    (alarm,) = ActiveAlarmsDataFile(EMMA_4006, hems_layout=True).alarms

    assert alarm.name == "Charger Communication Error"
    assert alarm.alarm_info == EMMA_ALARM_CODES[4006]
    assert alarm.effective_level is AlarmLevel.MAJOR
    assert alarm.manual_clear is False


@pytest.mark.parametrize(
    ("alarm_id", "name", "level"),
    [
        (2112, "Phase Sequence Abnormal", AlarmLevel.MAJOR),
        (4003, "The auxiliary power supply is faulty", AlarmLevel.CRITICAL),
        (4010, "Management System Certificate About to Expire", AlarmLevel.WARNING),
        (4022, "Meter Communication Error", AlarmLevel.MINOR),
        (4204, "Device fault", AlarmLevel.MAJOR),
        (4206, "Overtemperature", AlarmLevel.MINOR),
        (4207, "Abnormal Grounding", AlarmLevel.WARNING),
        (62903, "EPO Activated", AlarmLevel.CRITICAL),
        (63394, "EV Charging Abnormal", AlarmLevel.WARNING),
        (63490, "Certificate for Communication with OCPP System About to Expire", AlarmLevel.MAJOR),
    ],
)
def test_names_and_catalogue_levels(alarm_id: int, name: str, level: AlarmLevel) -> None:
    alarm = _alarm(alarm_id, control_word=0x0003)

    assert alarm.name == name
    assert alarm.effective_level is level
    # the control word level is still available as is
    assert alarm.level is AlarmLevel.WARNING


def test_inverter_alarm_falls_back_to_register_alarm_codes() -> None:
    alarm = _alarm(2001)

    assert alarm.name == "High String Input Voltage"
    assert lookup_alarm(2001) == HUAWEI_ALARM_CODES[2001]
    assert alarm.effective_level is AlarmLevel.MAJOR


def test_unknown_alarm_gets_generic_name_and_control_word_level() -> None:
    alarm = _alarm(4999, control_word=0x0002, reason_id=7)

    assert alarm.alarm_info is None
    assert lookup_alarm(4999) is None
    assert alarm.name == "Alarm 4999-7"
    assert alarm.effective_level is AlarmLevel.MINOR
    assert alarm.manual_clear is False


def test_level_without_scale_falls_back_to_control_word() -> None:
    """SmartLogger DI custom alarms have the level "Adaptable": the control word decides."""
    alarm = _alarm(1107, control_word=0x0000)

    assert alarm.name == "DI1 Custom Alarm"
    assert alarm.effective_level is AlarmLevel.CRITICAL


def test_history_alarm_names() -> None:
    record = struct.pack(
        HistoryAlarmsDataFile.RECORD_STRUCT,
        1,
        2,
        4211,
        int(OCCUR.timestamp()),
        int(OCCUR.timestamp()),
        0,
        0x0003,
        b"\x00\x01",
    )
    (alarm,) = HistoryAlarmsDataFile(record).alarms

    assert alarm.name == "Overload"
    assert alarm.effective_level is AlarmLevel.MAJOR
    assert alarm.level is AlarmLevel.WARNING


@pytest.mark.parametrize(
    ("alarm_id", "reason_id", "expected"),
    [
        (4014, 1, True),
        (2002, 7, True),
        (2021, 1, True),
        (2021, 2, False),
        (4006, 1, False),
        (4202, 1, False),
        (62903, 1, False),
        (4999, 1, False),
    ],
)
def test_manual_clear(alarm_id: int, reason_id: int, *, expected: bool) -> None:
    assert is_manual_clear_alarm(alarm_id, reason_id) is expected
    assert _alarm(alarm_id, reason_id=reason_id).manual_clear is expected


def test_manual_clear_in_the_three_families_is_only_emma_4014() -> None:
    assert {alarm_id for alarm_id in MANUAL_CLEAR_ALARMS if alarm_id in HUAWEI_FILE_ALARM_CODES} == {4014}
