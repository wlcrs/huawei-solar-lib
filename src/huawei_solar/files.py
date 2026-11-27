"""File definitions from the Huawei inverter."""

import logging
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, NamedTuple

from huawei_solar.exceptions import DecodeError
from huawei_solar.register_definitions.string import bytes_to_string
from huawei_solar.register_values import HUAWEI_ALARM_CODES, Alarm, _IntEnumWithPrettyString

_LOGGER = logging.getLogger(__name__)

OPTIMIZER_ALARM_CODES = {
    0b0000_0000_0000_0001: "Input Overvoltage",
    0b0000_0000_0000_0010: "Input Undervoltage",
    0b0000_0000_0000_1000: "Output Overvoltage",
    0b0000_0000_0001_0000: "Overtemperature",
    0b0000_0000_0010_0000: "Output Short Circuit",
    0b0000_0000_0100_0000: "EEPROM Fault",
    0b0000_0000_1000_0000: "Internal Hardware Fault",
    0b0000_0001_0000_0000: "Abnormal Voltage To Ground",
    0b0000_0010_0000_0000: "Power-off due to heartbeat timeout",
    0b0000_0100_0000_0000: "Fast shutdown",
    0b0000_1000_0000_0000: "Request Escape Alarm",
    0b0001_0000_0000_0000: "Version mismatch alarm",
    0b1000_0000_0000_0000: "Input overvoltage",
    0b0001_0000_0000_0000_0000: "Overtemperature",
    0b0010_0000_0000_0000_0000: "Output short circuit",
    0b0100_0000_0000_0000_0000: "Internal hardware fault",
    0b1000_0000_0000_0000_0000: "Version mismatch alarm",
    0b0001_0000_0000_0000_0000_0000: "Backfeed alarm",
    0b0010_0000_0000_0000_0000_0000: "Abnormal output voltage",
    0b0100_0000_0000_0000_0000_0000: "Upgrade failure",
    0b0100_0000_0000_0000_0000_0000_0000: "Display bit 16 to bit 30 alarms",
}


class OptimizerRunningStatus(_IntEnumWithPrettyString):
    """Optimizer Running Status."""

    OFFLINE = 0
    STANDBY = 1
    FAULTY = 3
    RUNNING = 4
    POWER_OFF = 12


@dataclass(frozen=True, slots=True)
class OptimizerRealTimeData:
    """Optimizer History Real Time Data."""

    optimizer_address: int
    output_power: float  # W
    voltage_to_ground: float  # V
    alarm: list[str]
    output_voltage: float  # V
    output_current: float  # A
    input_voltage: float  # V
    input_current: float  # A
    temperature: float  # C
    running_status: OptimizerRunningStatus
    accumulated_energy_yield: float  # kWh


@dataclass(frozen=True, slots=True)
class OptimizerHistoryRealTimeDataUnit:
    """Optimizer History Real Time Data Unit."""

    time: datetime
    optimizers: list[OptimizerRealTimeData]


class OptimizerRealTimeDataFile:
    """Optimizer Real Time Data File."""

    FILE_TYPE = 0x44

    HEADER = "<4s8x"
    OPTIMIZER_DATA_UNIT = "<i4xhh"

    OPTIMIZER_DATA = "<3hI6hI"

    def __init__(self, file_data: bytes) -> None:
        """Create an OptimizerRealTimeDataFile from the byte-reprenstation."""
        self.data_units: list[OptimizerHistoryRealTimeDataUnit] = []

        offset = 0

        # Check if we have an empty file
        if len(file_data) < struct.calcsize(OptimizerRealTimeDataFile.HEADER):
            return

        try:
            self.file_version = struct.unpack_from(
                OptimizerRealTimeDataFile.HEADER,
                file_data,
                offset,
            )
            offset += struct.calcsize(OptimizerRealTimeDataFile.HEADER)

            has_next_optimizer_data_unit = True
            while has_next_optimizer_data_unit:
                (time, _length, number_of_optimizers) = struct.unpack_from(
                    OptimizerRealTimeDataFile.OPTIMIZER_DATA_UNIT,
                    file_data,
                    offset,
                )
                offset += struct.calcsize(OptimizerRealTimeDataFile.OPTIMIZER_DATA_UNIT)

                optimizers = []
                for _ in range(number_of_optimizers):
                    (
                        optimizer_address,
                        output_power,
                        voltage_to_ground,
                        alarm,
                        output_voltage,
                        output_current,
                        input_voltage,
                        input_current,
                        temperature,
                        running_status,
                        accumulated_energy_yield,
                    ) = struct.unpack_from(
                        OptimizerRealTimeDataFile.OPTIMIZER_DATA,
                        file_data,
                        offset,
                    )
                    offset += struct.calcsize(OptimizerRealTimeDataFile.OPTIMIZER_DATA)

                    alarms = []
                    for bit, value in OPTIMIZER_ALARM_CODES.items():
                        if alarm & bit:
                            alarms.append(value)

                    optimizers.append(
                        OptimizerRealTimeData(
                            optimizer_address,
                            output_power / 10,
                            voltage_to_ground / 10,
                            alarms,
                            output_voltage / 10,
                            output_current / 100,
                            input_voltage / 10,
                            input_current / 100,
                            temperature / 10,
                            OptimizerRunningStatus(running_status),
                            accumulated_energy_yield / 1000,
                        ),
                    )

                self.data_units.append(
                    OptimizerHistoryRealTimeDataUnit(
                        datetime.fromtimestamp(time, tz=UTC),
                        optimizers,
                    ),
                )

                has_next_optimizer_data_unit = offset < len(file_data)
        except struct.error as err:
            msg = "Could not decode optimizer real time data file: the contents is corrupted."
            raise DecodeError(msg) from err

    def __str__(self) -> str:
        """Return a string representation of a OptimizerHistoryDataFile."""
        return f"OptimizerHistoryDataFile(file_version=f{self.file_version}, data_units=f{self.data_units})"

    @staticmethod
    def query_within_timespan(start_time: int, end_time: int) -> bytes:
        """Create a query for values within a given timeframe."""
        # the values below were deduced from observing network traffic and reverse-engineering the app
        tag = 0x10
        value_length = 12

        reserved = 0
        return struct.pack(">BBIII", tag, value_length, start_time, end_time, reserved)


class OptimizerOnlineStatus(_IntEnumWithPrettyString):
    """Optimizer Online Status."""

    OFFLINE = 0
    ONLINE = 1
    DISCONNECTED = 2


@dataclass(frozen=True, slots=True)
class OptimizerSystemInformation:
    """Optimizer System Information."""

    optimizer_address: int
    online_status: OptimizerOnlineStatus
    string_number: int
    position_in_current_string: int | None  # relative position connection starting point
    sn: str
    software_version: str
    alias: str
    model: str

    # Following fields are available in V103:
    machine_id: int | None = None
    """16-bit Hardware Model Identifie"""
    one_to_more: bool | None = None
    """ indicates a 2:1 multi-module optimizer (such as MERC-1100/1300-P-AU)."""
    rated_power: int | None = None
    """Rated output capacity in Watts (e.g. 450, 600, 1100, 1300)."""
    cpu_type: int | None = None
    """Microcontroller/chip architecture type."""


INVALID_OPTIMIZER_POSITION = 0xFFFF


class OptimizerSystemInformationDataFile:
    """Optimizer System Information Data File."""

    FILE_TYPE = 0x45

    HEADER = ">4sHH?3xH"

    # first byte of string_number is ignored, as it seems that this is
    # always a duplicate of the second byte, resulting in string
    # numbers 257 and 514 instead of 1 and 2.
    # cfr: https://github.com/wlcrs/huawei_solar/issues/76#issue-1268597032
    V100_OPTIMIZER_FEATURE_DATA = ">HHxbH20s30s"
    V101_OPTIMIZER_FEATURE_DATA = ">HHxbH20s30s20s"
    V102_OPTIMIZER_FEATURE_DATA = ">HHxbH20s30s20s30s"
    V103_OPTIMIZER_FEATURE_DATA = ">HHxbH20s30s20s30sHHHH"

    def __init__(self, file_data: bytes) -> None:
        """Create Optimizer System Information Data File."""
        self.optimizers: list[OptimizerSystemInformation] = []

        try:
            offset = 0

            (
                self.file_version,
                _feature_data_sequence_number,
                _length,
                _reserved,
                number_of_optimizers,
            ) = struct.unpack_from(
                OptimizerSystemInformationDataFile.HEADER,
                file_data,
                offset,
            )
            offset += struct.calcsize(OptimizerSystemInformationDataFile.HEADER)

            if self.file_version == b"V100":
                for _ in range(number_of_optimizers):
                    (
                        optimizer_address,
                        online_status,
                        string_number,
                        position_in_current_string,
                        sn,
                        software_version,
                    ) = struct.unpack_from(
                        OptimizerSystemInformationDataFile.V100_OPTIMIZER_FEATURE_DATA,
                        file_data,
                        offset,
                    )
                    offset += struct.calcsize(
                        OptimizerSystemInformationDataFile.V100_OPTIMIZER_FEATURE_DATA,
                    )

                    self.optimizers.append(
                        OptimizerSystemInformation(
                            optimizer_address,
                            OptimizerOnlineStatus(online_status),
                            string_number,
                            (
                                position_in_current_string
                                if position_in_current_string != INVALID_OPTIMIZER_POSITION
                                else None
                            ),
                            bytes_to_string(sn),
                            bytes_to_string(software_version),
                            alias="",
                            model="NA",
                        ),
                    )

            elif self.file_version == b"V101":
                for _ in range(number_of_optimizers):
                    (
                        optimizer_address,
                        online_status,
                        string_number,
                        position_in_current_string,
                        sn,
                        software_version,
                        alias,
                    ) = struct.unpack_from(
                        OptimizerSystemInformationDataFile.V101_OPTIMIZER_FEATURE_DATA,
                        file_data,
                        offset,
                    )
                    offset += struct.calcsize(
                        OptimizerSystemInformationDataFile.V101_OPTIMIZER_FEATURE_DATA,
                    )

                    self.optimizers.append(
                        OptimizerSystemInformation(
                            optimizer_address,
                            OptimizerOnlineStatus(online_status),
                            string_number,
                            (
                                position_in_current_string
                                if position_in_current_string != INVALID_OPTIMIZER_POSITION
                                else None
                            ),
                            bytes_to_string(sn),
                            bytes_to_string(software_version),
                            bytes_to_string(alias),
                            model="NA",
                        ),
                    )

            elif self.file_version == b"V102":
                for _ in range(number_of_optimizers):
                    (
                        optimizer_address,
                        online_status,
                        string_number,
                        position_in_current_string,
                        sn,
                        software_version,
                        alias,
                        model,
                    ) = struct.unpack_from(
                        OptimizerSystemInformationDataFile.V102_OPTIMIZER_FEATURE_DATA,
                        file_data,
                        offset,
                    )
                    offset += struct.calcsize(
                        OptimizerSystemInformationDataFile.V102_OPTIMIZER_FEATURE_DATA,
                    )

                    self.optimizers.append(
                        OptimizerSystemInformation(
                            optimizer_address,
                            OptimizerOnlineStatus(online_status),
                            string_number,
                            (
                                position_in_current_string
                                if position_in_current_string != INVALID_OPTIMIZER_POSITION
                                else None
                            ),
                            bytes_to_string(sn),
                            bytes_to_string(software_version),
                            bytes_to_string(alias),
                            bytes_to_string(model),
                        ),
                    )

            elif self.file_version == b"V103":
                for _ in range(number_of_optimizers):
                    (
                        optimizer_address,
                        online_status,
                        string_number,
                        position_in_current_string,
                        sn,
                        software_version,
                        alias,
                        model,
                        machine_id,
                        one_to_more_raw,
                        rated_power,
                        cpu_type,
                    ) = struct.unpack_from(
                        OptimizerSystemInformationDataFile.V103_OPTIMIZER_FEATURE_DATA,
                        file_data,
                        offset,
                    )
                    offset += struct.calcsize(
                        OptimizerSystemInformationDataFile.V103_OPTIMIZER_FEATURE_DATA,
                    )

                    self.optimizers.append(
                        OptimizerSystemInformation(
                            optimizer_address,
                            OptimizerOnlineStatus(online_status),
                            string_number,
                            (
                                position_in_current_string
                                if position_in_current_string != INVALID_OPTIMIZER_POSITION
                                else None
                            ),
                            bytes_to_string(sn),
                            bytes_to_string(software_version),
                            bytes_to_string(alias),
                            bytes_to_string(model),
                            machine_id=machine_id,
                            one_to_more=(one_to_more_raw & 0xFF) == 2,  # noqa: PLR2004
                            rated_power=rated_power,
                            cpu_type=cpu_type,
                        ),
                    )
            else:
                msg = f"Unsupported OptimizerSystemInformation file version: {self.file_version}"
                raise DecodeError(
                    msg,
                )
        except struct.error as err:
            msg = "Could not decode optimizer system information data file: the contents is corrupted."
            raise DecodeError(msg) from err


class AlarmLevel(_IntEnumWithPrettyString):
    """Alarm severity: control word bits 0-1, same scale as the FusionSolar alarm catalogue.

    A lower value is more severe: compare `severity` rather than the enum values to rank alarms. (Releases 3.0.8 to
    3.2.4 had this enum reversed: PROMPT=0, WARNING=1, MAJOR=2, CRITICAL=3.)
    """

    CRITICAL = 0
    MAJOR = 1
    MINOR = 2
    WARNING = 3

    @property
    def severity(self) -> int:
        """Return a rank that grows with severity: 4 for Critical down to 1 for Warning."""
        return len(AlarmLevel) - self.value


# Alarm ids of the LUNA2000 battery rack controller (BCU): their reason field packs the reason id with the
# battery pack slot and the cabinet number.
_BCU_ALARM_IDS = range(3000, 4000)


class _AlarmReason(NamedTuple):
    reason_id: int
    topn: bool
    location: bool
    slot: int | None
    cabinet: int | None


def _decode_reason(alarm_id: int, control_word: int, raw: bytes, *, hems_layout: bool) -> _AlarmReason:
    """Decode the 2-byte reason field of an alarm record like FusionSolar does.

    The reason field is not a little-endian u16 like the rest of the record. Normally the reason id is the
    second byte. Two flag bits in the control word mark a "TopN" alarm (reason in the first byte) or a "Location"
    alarm (a little-endian bitfield with the slot and cabinet). LUNA2000 BCU alarms that are not TopN use the
    same bitfield, big-endian.

    The flag bits are 11 (TopN) and 10 (Location) in history records and in records read through an EMMA
    (`hems_layout`), and 12 and 11 otherwise.
    """
    topn_bit, location_bit = (11, 10) if hems_layout else (12, 11)
    topn_flag = (control_word >> topn_bit) & 1
    location_flag = (control_word >> location_bit) & 1
    topn = topn_flag == 1 and location_flag == 0
    location = topn_flag == 1 and location_flag == 1

    if location:
        word = raw[0] | (raw[1] << 8)
    elif alarm_id in _BCU_ALARM_IDS and not topn:
        word = (raw[0] << 8) | raw[1]
    else:
        return _AlarmReason(raw[0] if topn else raw[1], topn=topn, location=False, slot=None, cabinet=None)

    return _AlarmReason(word & 0x3F, topn=topn, location=location, slot=(word >> 6) & 0x3F, cabinet=(word >> 12) & 0x0F)


@dataclass(frozen=True, slots=True)
class ActiveAlarm:
    """Active Alarm entry.

    Attributes:
        serial_no: Monotonically increasing unique sequence ID assigned by device firmware.
        equip_id: Logical address of the reporting device (its Modbus unit behind an EMMA).
        alarm_id: Huawei alarm identifier code (maps to device alarm catalog, e.g. 2001, 2062).
        occur_time: Timestamp when the alarm condition was initially triggered.
        alarm_param: Auxiliary fault parameter (signed; e.g. faulty PV string index, phase, or measured value).
        control_word: Raw 16-bit control word: severity level (bits 0-1) and the TopN/Location flags.
        reason_id: Cause / sub-cause code specifying the precise failure mode.
        topn: The control word marks this as a "TopN" alarm.
        location: The control word marks this as a "Location" alarm, with a slot and cabinet number.
        slot: Battery pack slot number (Location alarms and LUNA2000 BCU alarms 3000-3999), otherwise None.
        cabinet: Cabinet number (Location alarms and LUNA2000 BCU alarms 3000-3999), otherwise None.
        reason_raw: The two raw bytes of the reason field, as a big-endian number (for debugging).

    """

    serial_no: int
    equip_id: int
    alarm_id: int
    occur_time: datetime
    alarm_param: int
    control_word: int
    reason_id: int
    topn: bool = False
    location: bool = False
    slot: int | None = None
    cabinet: int | None = None
    reason_raw: int = 0

    @property
    def level(self) -> AlarmLevel:
        """Alarm severity level from the control word (bits 0-1)."""
        return AlarmLevel(self.control_word & 0b11)

    @property
    def alarm_info(self) -> Alarm | None:
        """Look up full Alarm metadata from master alarm catalog."""
        return HUAWEI_ALARM_CODES.get(self.alarm_id)

    @property
    def name(self) -> str:
        """Return alarm name or fallback to Alarm ID."""
        info = self.alarm_info
        return info.name if info else f"Unknown Alarm {self.alarm_id}"


class ActiveAlarmsDataFile:
    """Active Alarms Data File (File Type 0xA1 / 161).

    A bare array of 20-byte records without a header. Little-endian, except for the reason field (see
    `_decode_reason`).
    """

    FILE_TYPE = 0xA1
    # serial, equip id, alarm id, occur time, parameter (signed), control word, raw reason field
    RECORD_STRUCT = "<IHHIiH2s"

    def __init__(self, file_data: bytes, *, hems_layout: bool = False) -> None:
        """Decode Active Alarms file.

        Set `hems_layout` when the file was read through an EMMA: the TopN/Location flags then sit one bit lower
        in the control word.
        """
        self.alarms: list[ActiveAlarm] = []

        try:
            for (
                serial_no,
                equip_id,
                alarm_id,
                occur_time,
                alarm_param,
                control_word,
                raw_reason,
            ) in _iter_alarm_records(ActiveAlarmsDataFile.RECORD_STRUCT, file_data, "active"):
                reason = _decode_reason(alarm_id, control_word, raw_reason, hems_layout=hems_layout)
                self.alarms.append(
                    ActiveAlarm(
                        serial_no=serial_no,
                        equip_id=equip_id,
                        alarm_id=alarm_id,
                        occur_time=datetime.fromtimestamp(occur_time, tz=UTC),
                        alarm_param=alarm_param,
                        control_word=control_word,
                        reason_id=reason.reason_id,
                        topn=reason.topn,
                        location=reason.location,
                        slot=reason.slot,
                        cabinet=reason.cabinet,
                        reason_raw=int.from_bytes(raw_reason),
                    )
                )
        except struct.error as err:
            msg = "Could not decode active alarms data file: the contents is corrupted."
            raise DecodeError(msg) from err

    @staticmethod
    def query_active_alarms(equip_id: int = 0) -> bytes:
        """Create query custom data for active alarms file download."""
        # Tag 0x11, Length 4, equip_id uint32
        return struct.pack(">BBI", 0x11, 4, equip_id)


def _iter_alarm_records(record_struct: str, file_data: bytes, kind: str) -> Iterator[tuple[Any, ...]]:
    """Unpack the fixed-size records of an alarm file, ignoring an incomplete trailing record."""
    record_size = struct.calcsize(record_struct)
    record_count, trailing = divmod(len(file_data), record_size)
    if trailing:
        _LOGGER.warning(
            "Ignoring %d trailing bytes in the %s alarms file: %s",
            trailing,
            kind,
            file_data[-trailing:].hex(" "),
        )
    for index in range(record_count):
        yield struct.unpack_from(record_struct, file_data, index * record_size)


@dataclass(frozen=True, slots=True)
class HistoryAlarm:
    """Historical Alarm entry.

    Attributes:
        serial_no: Monotonically increasing unique sequence ID assigned by device firmware.
        equip_id: Logical address of the reporting device (its Modbus unit behind an EMMA).
        alarm_id: Huawei alarm identifier code (maps to device alarm catalog, e.g. 2001, 2062).
        occur_time: Timestamp when the alarm condition was initially triggered.
        recover_time: Timestamp when the alarm condition cleared or recovered.
        alarm_param: Auxiliary fault parameter (signed; e.g. faulty PV string index, phase, or measured value).
        control_word: Raw 16-bit control word: severity level (bits 0-1) and the TopN/Location flags.
        reason_id: Cause / sub-cause code specifying the precise failure mode.
        topn: The control word marks this as a "TopN" alarm.
        location: The control word marks this as a "Location" alarm, with a slot and cabinet number.
        slot: Battery pack slot number (Location alarms and LUNA2000 BCU alarms 3000-3999), otherwise None.
        cabinet: Cabinet number (Location alarms and LUNA2000 BCU alarms 3000-3999), otherwise None.
        reason_raw: The two raw bytes of the reason field, as a big-endian number (for debugging).

    """

    serial_no: int
    equip_id: int
    alarm_id: int
    occur_time: datetime
    recover_time: datetime
    alarm_param: int
    control_word: int
    reason_id: int
    topn: bool = False
    location: bool = False
    slot: int | None = None
    cabinet: int | None = None
    reason_raw: int = 0

    @property
    def level(self) -> AlarmLevel:
        """Alarm severity level from the control word (bits 0-1)."""
        return AlarmLevel(self.control_word & 0b11)

    @property
    def alarm_info(self) -> Alarm | None:
        """Look up full Alarm metadata from master alarm catalog."""
        return HUAWEI_ALARM_CODES.get(self.alarm_id)

    @property
    def name(self) -> str:
        """Return alarm name or fallback to Alarm ID."""
        info = self.alarm_info
        return info.name if info else f"Unknown Alarm {self.alarm_id}"


class HistoryAlarmsDataFile:
    """History Alarms Data File (File Type 0xA2 / 162).

    A bare array of 24-byte records without a header. Little-endian, except for the reason field (see
    `_decode_reason`). FusionSolar always decodes the TopN/Location flags of history records in the EMMA layout.
    """

    FILE_TYPE = 0xA2
    # serial, equip id, alarm id, occur time, recover time, parameter (signed), control word, raw reason field
    RECORD_STRUCT = "<IHHIIiH2s"

    def __init__(self, file_data: bytes) -> None:
        """Decode History Alarms file."""
        self.alarms: list[HistoryAlarm] = []

        try:
            for (
                serial_no,
                equip_id,
                alarm_id,
                occur_time,
                recover_time,
                alarm_param,
                control_word,
                raw_reason,
            ) in _iter_alarm_records(HistoryAlarmsDataFile.RECORD_STRUCT, file_data, "history"):
                reason = _decode_reason(alarm_id, control_word, raw_reason, hems_layout=True)
                self.alarms.append(
                    HistoryAlarm(
                        serial_no=serial_no,
                        equip_id=equip_id,
                        alarm_id=alarm_id,
                        occur_time=datetime.fromtimestamp(occur_time, tz=UTC),
                        recover_time=datetime.fromtimestamp(recover_time, tz=UTC),
                        alarm_param=alarm_param,
                        control_word=control_word,
                        reason_id=reason.reason_id,
                        topn=reason.topn,
                        location=reason.location,
                        slot=reason.slot,
                        cabinet=reason.cabinet,
                        reason_raw=int.from_bytes(raw_reason),
                    )
                )
        except struct.error as err:
            msg = "Could not decode history alarms data file: the contents is corrupted."
            raise DecodeError(msg) from err

    @staticmethod
    def query_within_timespan(start_time: int, end_time: int, tag: int = 0x24) -> bytes:
        """Create query custom data for history alarms file download within given timeframe."""
        if tag == 0x24:  # noqa: PLR2004
            # Tag 0x24 (36), Length 10, start_time uint32, end_time uint32, -1 (signed byte), 0 (byte)
            return struct.pack("<BBIIbb", tag, 10, start_time, end_time, -1, 0)
        # Tag 0x20 / 0x21 (32 / 33), Length 9, start_time uint32, end_time uint32, -1 (signed byte)
        return struct.pack(">BBIIb", tag, 9, start_time, end_time, -1)


class PerformanceRequestType(_IntEnumWithPrettyString):
    """Inverter Performance & History Request Types."""

    HOUR_POWER = 0
    DAY_POWER = 1
    MONTH_POWER = 2
    YEAR_POWER = 3
    OUTPUT_POWER = 4
    INSULATION_RESISTANCE = 5
    BATTERY_CHARGE_AND_DISCHARGE_POWER = 6
    METER_POWER = 7
    BATTERY_CHARGE_DAY_POWER = 8
    BATTERY_DISCHARGE_DAY_POWER = 9
    ABSORB_HOUR_POWER = 10
    ABSORB_DAY_POWER = 11
    ABSORB_MONTH_POWER = 12
    ABSORB_YEAR_POWER = 13


@dataclass(frozen=True, slots=True)
class PerformanceDataPoint:
    """Historical telemetry data point."""

    time: datetime
    request_type: PerformanceRequestType | int
    value: float


class InverterPerformanceDataFile:
    """Inverter History & Energy Performance Data File (File Type 0xA3 / 163)."""

    FILE_TYPE = 0xA3
    HUAWEI_FUNCTION_CODE = 0x41
    SUB_FUNCTION_PERFORMANCE_DATA = 0x36

    # Gains corresponding to PerformanceRequestType
    GAINS: ClassVar[dict[PerformanceRequestType | int, int]] = {
        PerformanceRequestType.HOUR_POWER: 100,
        PerformanceRequestType.DAY_POWER: 100,
        PerformanceRequestType.MONTH_POWER: 100,
        PerformanceRequestType.YEAR_POWER: 100,
        PerformanceRequestType.OUTPUT_POWER: 1000,
        PerformanceRequestType.INSULATION_RESISTANCE: 1000,
        PerformanceRequestType.BATTERY_CHARGE_AND_DISCHARGE_POWER: 1000,
        PerformanceRequestType.METER_POWER: 1000,
        PerformanceRequestType.BATTERY_CHARGE_DAY_POWER: 100,
        PerformanceRequestType.BATTERY_DISCHARGE_DAY_POWER: 100,
        PerformanceRequestType.ABSORB_HOUR_POWER: 100,
        PerformanceRequestType.ABSORB_DAY_POWER: 100,
        PerformanceRequestType.ABSORB_MONTH_POWER: 100,
        PerformanceRequestType.ABSORB_YEAR_POWER: 100,
    }

    # Default interval cycles in seconds
    DEFAULT_CYCLES: ClassVar[dict[PerformanceRequestType | int, int]] = {
        PerformanceRequestType.HOUR_POWER: 300,  # 5-minute intervals
        PerformanceRequestType.DAY_POWER: 86400,  # 1 day
        PerformanceRequestType.MONTH_POWER: 2592000,  # ~30 days
        PerformanceRequestType.YEAR_POWER: 31536000,  # ~365 days
        PerformanceRequestType.OUTPUT_POWER: 300,
        PerformanceRequestType.INSULATION_RESISTANCE: 86400,
        PerformanceRequestType.BATTERY_CHARGE_AND_DISCHARGE_POWER: 300,
        PerformanceRequestType.METER_POWER: 300,
        PerformanceRequestType.BATTERY_CHARGE_DAY_POWER: 86400,
        PerformanceRequestType.BATTERY_DISCHARGE_DAY_POWER: 86400,
        PerformanceRequestType.ABSORB_HOUR_POWER: 300,
        PerformanceRequestType.ABSORB_DAY_POWER: 86400,
        PerformanceRequestType.ABSORB_MONTH_POWER: 2592000,
        PerformanceRequestType.ABSORB_YEAR_POWER: 31536000,
    }

    def __init__(
        self,
        file_data: bytes,
        request_type: PerformanceRequestType | int = PerformanceRequestType.HOUR_POWER,
        cycle: int | None = None,
    ) -> None:
        """Decode Inverter History & Performance Data File."""
        self.data_points: list[PerformanceDataPoint] = []
        self.request_type = request_type

        try:
            req_enum = (
                PerformanceRequestType(request_type)
                if isinstance(request_type, int) and request_type in PerformanceRequestType._value2member_map_
                else request_type
            )
        except (ValueError, KeyError):
            req_enum = request_type

        gain = InverterPerformanceDataFile.GAINS.get(req_enum, 100)
        cycle_seconds = cycle or InverterPerformanceDataFile.DEFAULT_CYCLES.get(req_enum, 300)

        offset = 0
        try:
            # Handle optional frame header if raw Modbus 0x41 0x36 frame:
            # [0:addr, 1:0x41, 2:0x36, 3:datalen, 4:index, 5:seg_count]
            if (
                len(file_data) > 6  # noqa: PLR2004
                and file_data[1] == InverterPerformanceDataFile.HUAWEI_FUNCTION_CODE
                and file_data[2] == InverterPerformanceDataFile.SUB_FUNCTION_PERFORMANCE_DATA
            ):
                segment_count = file_data[5] & 0x3F
                offset = 6
            elif len(file_data) >= 5:  # noqa: PLR2004
                # Raw segment data stream without function wrapper
                segment_count = None
            else:
                return

            seg_idx = 0
            while offset + 5 <= len(file_data):
                if segment_count is not None and seg_idx >= segment_count:
                    break

                (start_time, tdata_length) = struct.unpack_from(">IB", file_data, offset)
                offset += 5

                point_count = tdata_length // 4
                for j in range(point_count):
                    if offset + 4 > len(file_data):
                        break
                    (raw_value,) = struct.unpack_from(">i", file_data, offset)
                    offset += 4

                    point_time = start_time + (j * cycle_seconds)
                    self.data_points.append(
                        PerformanceDataPoint(
                            time=datetime.fromtimestamp(point_time, tz=UTC),
                            request_type=req_enum,
                            value=raw_value / gain,
                        )
                    )
                seg_idx += 1
        except struct.error as err:
            msg = "Could not decode inverter performance data file: the contents is corrupted."
            raise DecodeError(msg) from err

    @staticmethod
    def query_within_timespan(
        request_type: PerformanceRequestType | int,
        start_time: int,
        end_time: int,
    ) -> bytes:
        """Create query custom data for performance/history data file download within given timeframe."""
        # Format: Tag 0x30, Length 12, SubId 0, Type 0, RequestType, StartTime, EndTime, 0xFF
        req_type_val = int(request_type)
        return struct.pack(">BBHBBIIB", 0x30, 12, 0, 0, req_type_val, start_time, end_time, 0xFF)
