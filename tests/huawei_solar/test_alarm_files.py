"""Tests for decoding the active (0xA1) and history (0xA2) alarm files.

No alarm record has been captured from a real device yet: the vectors below are synthetic and follow the record
layout of the FusionSolar app (AlarmManagerModbus, TopnUtils, AlarmDatabaseHelper).
"""

import logging
import struct
from datetime import UTC, datetime

import pytest
from huawei_solar.files import ActiveAlarmsDataFile, AlarmLevel, HistoryAlarmsDataFile

OCCUR = datetime(2026, 11, 15, 3, 10, tzinfo=UTC)  # 1794712200, device-local wall clock encoded as if UTC

# EMMA 4006 "Charger Communication Error", equip 6, ctrl 0x0001 (major), normal reason 2
EMMA_4006 = bytes.fromhex("02 01 00 00 06 00 a6 0f 88 22 f9 6a 00 00 00 00 01 00 00 02")
# EMMA 4021 "CT connection abnormal", equip 0, ctrl 0x0801 (bit 11 set, bit 10 clear), reason byte 3
EMMA_4021_TOPN = bytes.fromhex("03 01 00 00 00 00 b5 0f 88 22 f9 6a 00 00 00 00 01 08 03 00")
# LUNA2000 BCU-style id 3021, equip 3, ctrl 0x0002 (minor), reason field 10 45
LUNA_3021 = bytes.fromhex("04 01 00 00 03 00 cd 0b 88 22 f9 6a 00 00 00 00 02 00 10 45")


def _active_record(
    alarm_id: int,
    control_word: int,
    reason: bytes,
    *,
    serial_no: int = 1,
    equip_id: int = 0,
    param: int = 0,
) -> bytes:
    return struct.pack(
        ActiveAlarmsDataFile.RECORD_STRUCT,
        serial_no,
        equip_id,
        alarm_id,
        int(OCCUR.timestamp()),
        param,
        control_word,
        reason,
    )


def test_record_sizes() -> None:
    assert struct.calcsize(ActiveAlarmsDataFile.RECORD_STRUCT) == 20
    assert struct.calcsize(HistoryAlarmsDataFile.RECORD_STRUCT) == 24


def test_normal_reason_is_the_second_byte() -> None:
    """The reason of a normal alarm is byte 19, not the little-endian u16 (which would give 512 here)."""
    (alarm,) = ActiveAlarmsDataFile(EMMA_4006).alarms

    assert alarm.serial_no == 258
    assert alarm.equip_id == 6
    assert alarm.alarm_id == 4006
    assert alarm.occur_time == OCCUR
    assert alarm.alarm_param == 0
    assert alarm.control_word == 0x0001
    assert alarm.reason_id == 2
    assert alarm.level is AlarmLevel.MAJOR
    assert alarm.topn is False
    assert alarm.location is False
    assert alarm.slot is None
    assert alarm.cabinet is None
    assert alarm.reason_raw == 0x0002


def test_normal_reason_same_in_both_layouts() -> None:
    assert ActiveAlarmsDataFile(EMMA_4006, hems_layout=True).alarms[0].reason_id == 2


def test_topn_reason_in_hems_layout() -> None:
    """Through an EMMA, bit 11 set and bit 10 clear marks a TopN alarm: the reason is byte 18."""
    (alarm,) = ActiveAlarmsDataFile(EMMA_4021_TOPN, hems_layout=True).alarms

    assert alarm.alarm_id == 4021
    assert alarm.topn is True
    assert alarm.location is False
    assert alarm.reason_id == 3
    assert alarm.level is AlarmLevel.MAJOR
    assert alarm.slot is None
    assert alarm.reason_raw == 0x0300


def test_topn_bits_differ_outside_hems_layout() -> None:
    """For a directly connected inverter the TopN flag is bit 12: the same record is a normal alarm."""
    (alarm,) = ActiveAlarmsDataFile(EMMA_4021_TOPN).alarms

    assert alarm.topn is False
    assert alarm.reason_id == 0


def test_topn_reason_in_direct_layout() -> None:
    (alarm,) = ActiveAlarmsDataFile(_active_record(2001, 0x1000, b"\x05\x00")).alarms

    assert alarm.topn is True
    assert alarm.location is False
    assert alarm.reason_id == 5
    assert alarm.level is AlarmLevel.CRITICAL


def test_luna_bcu_reason_slot_and_cabinet() -> None:
    """LUNA2000 BCU ids 3000-3999 pack reason:6, slot:6, cabinet:4 big-endian in the reason field."""
    (alarm,) = ActiveAlarmsDataFile(LUNA_3021).alarms

    assert alarm.alarm_id == 3021
    assert alarm.equip_id == 3
    assert alarm.level is AlarmLevel.MINOR
    assert alarm.topn is False
    assert alarm.location is False
    assert alarm.reason_id == 5
    assert alarm.slot == 1
    assert alarm.cabinet == 1
    assert alarm.reason_raw == 0x1045


def test_luna_bcu_reason_with_high_bits() -> None:
    # w = 0xABCD: reason 0x0D, slot (0xABCD >> 6) & 0x3F = 0x2F, cabinet 0xA
    (alarm,) = ActiveAlarmsDataFile(_active_record(3999, 0x0000, b"\xab\xcd")).alarms

    assert (alarm.reason_id, alarm.slot, alarm.cabinet) == (0x0D, 0x2F, 0x0A)


def test_luna_bcu_id_with_topn_flag_uses_the_topn_byte() -> None:
    (alarm,) = ActiveAlarmsDataFile(_active_record(3021, 0x1002, b"\x07\x45")).alarms

    assert alarm.topn is True
    assert alarm.reason_id == 7
    assert alarm.slot is None
    assert alarm.cabinet is None


def test_ids_just_outside_the_bcu_range_are_normal() -> None:
    alarms = ActiveAlarmsDataFile(_active_record(2999, 0, b"\x10\x45") + _active_record(4000, 0, b"\x10\x45")).alarms

    assert [(a.reason_id, a.slot) for a in alarms] == [(0x45, None), (0x45, None)]


@pytest.mark.parametrize(
    ("control_word", "hems_layout"),
    [(0x1800, False), (0x0C00, True)],
)
def test_location_reason_slot_and_cabinet(control_word: int, *, hems_layout: bool) -> None:
    """Both flag bits set mark a Location alarm: a little-endian reason:6, slot:6, cabinet:4 bitfield."""
    data = _active_record(2001, control_word | 0x0003, b"\x45\x10")
    (alarm,) = ActiveAlarmsDataFile(data, hems_layout=hems_layout).alarms

    assert alarm.location is True
    assert alarm.topn is False
    assert alarm.reason_id == 5
    assert alarm.slot == 1
    assert alarm.cabinet == 1
    assert alarm.level is AlarmLevel.WARNING


def test_location_takes_precedence_for_bcu_ids() -> None:
    (alarm,) = ActiveAlarmsDataFile(_active_record(3021, 0x1800, b"\x45\x10")).alarms

    assert alarm.location is True
    assert (alarm.reason_id, alarm.slot, alarm.cabinet) == (5, 1, 1)


@pytest.mark.parametrize(
    ("control_word", "expected"),
    [
        (0x0000, AlarmLevel.CRITICAL),
        (0x0001, AlarmLevel.MAJOR),
        (0x0002, AlarmLevel.MINOR),
        (0x0003, AlarmLevel.WARNING),
        (0xFFFC, AlarmLevel.CRITICAL),
        (0x1803, AlarmLevel.WARNING),
    ],
)
def test_level_from_control_word(control_word: int, expected: AlarmLevel) -> None:
    (alarm,) = ActiveAlarmsDataFile(_active_record(2001, control_word, b"\x00\x01")).alarms

    assert alarm.level is expected


def test_level_order_and_names() -> None:
    """Same scale as FusionSolar: 0 is the most severe."""
    assert [level.value for level in AlarmLevel] == [0, 1, 2, 3]
    assert [str(level) for level in AlarmLevel] == ["Critical", "Major", "Minor", "Warning"]


@pytest.mark.parametrize("param", [-1, -1000, -(2**31), 2**31 - 1, 7])
def test_alarm_param_is_signed(param: int) -> None:
    (alarm,) = ActiveAlarmsDataFile(_active_record(2001, 0, b"\x00\x01", param=param)).alarms

    assert alarm.alarm_param == param


def test_negative_param_from_raw_bytes() -> None:
    data = bytearray(EMMA_4006)
    data[12:16] = b"\xfe\xff\xff\xff"
    (alarm,) = ActiveAlarmsDataFile(bytes(data)).alarms

    assert alarm.alarm_param == -2


def test_empty_file_has_no_alarms(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert ActiveAlarmsDataFile(b"").alarms == []
        assert HistoryAlarmsDataFile(b"").alarms == []

    assert not caplog.records


def test_several_records() -> None:
    alarms = ActiveAlarmsDataFile(EMMA_4006 + EMMA_4021_TOPN + LUNA_3021, hems_layout=True).alarms

    assert [(a.serial_no, a.alarm_id, a.reason_id) for a in alarms] == [(258, 4006, 2), (259, 4021, 3), (260, 3021, 5)]


def test_trailing_bytes_are_ignored_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        alarms = ActiveAlarmsDataFile(EMMA_4006 + b"\x01\x02\x03").alarms

    assert [alarm.alarm_id for alarm in alarms] == [4006]
    assert "3 trailing bytes" in caplog.text
    assert "01 02 03" in caplog.text


def test_short_file_is_ignored_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert ActiveAlarmsDataFile(EMMA_4006[:19]).alarms == []

    assert "19 trailing bytes" in caplog.text


def _history_record(alarm_id: int, control_word: int, reason: bytes, *, param: int = 0) -> bytes:
    return struct.pack(
        HistoryAlarmsDataFile.RECORD_STRUCT,
        9,
        2,
        alarm_id,
        int(OCCUR.timestamp()),
        int(OCCUR.timestamp()) + 600,
        param,
        control_word,
        reason,
    )


def test_history_record() -> None:
    (alarm,) = HistoryAlarmsDataFile(_history_record(4204, 0x0001, b"\x00\x13", param=-3)).alarms

    assert alarm.serial_no == 9
    assert alarm.equip_id == 2
    assert alarm.alarm_id == 4204
    assert alarm.occur_time == OCCUR
    assert alarm.recover_time == datetime(2026, 11, 15, 3, 20, tzinfo=UTC)
    assert alarm.alarm_param == -3
    assert alarm.reason_id == 19
    assert alarm.level is AlarmLevel.MAJOR
    assert alarm.reason_raw == 0x0013


def test_history_records_always_use_the_hems_flag_bits() -> None:
    """FusionSolar decodes history flags with bits 11/10 whatever the connection."""
    alarms = HistoryAlarmsDataFile(
        _history_record(4021, 0x0801, b"\x03\x00")
        + _history_record(2001, 0x0C00, b"\x45\x10")
        + _history_record(2001, 0x1000, b"\x03\x04")
    ).alarms

    assert [(a.topn, a.location, a.reason_id, a.slot) for a in alarms] == [
        (True, False, 3, None),
        (False, True, 5, 1),
        (False, False, 4, None),
    ]


def test_history_luna_bcu_reason() -> None:
    (alarm,) = HistoryAlarmsDataFile(_history_record(3021, 0x0002, b"\x10\x45")).alarms

    assert (alarm.reason_id, alarm.slot, alarm.cabinet) == (5, 1, 1)


def test_history_trailing_bytes_are_ignored(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        alarms = HistoryAlarmsDataFile(_history_record(4204, 1, b"\x00\x01") + b"\x00" * 20).alarms

    assert len(alarms) == 1
    assert "20 trailing bytes in the history alarms file" in caplog.text


def test_level_severity_grows_with_seriousness() -> None:
    assert [level.severity for level in AlarmLevel] == [4, 3, 2, 1]
    assert max(AlarmLevel, key=lambda level: level.severity) is AlarmLevel.CRITICAL
