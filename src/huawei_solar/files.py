"""File definitions from the Huawei inverter."""

import logging
import struct
from calendar import monthrange
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from huawei_solar.exceptions import DecodeError
from huawei_solar.modbus_pdu import PerformanceDataFrame
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
    """Alarm severity level extracted from control word bits 0-1."""

    PROMPT = 0  # Suggestion / informational notification
    WARNING = 1  # Minor warning
    MAJOR = 2  # Major alarm
    CRITICAL = 3  # Critical fault requiring immediate action


@dataclass(frozen=True, slots=True)
class ActiveAlarm:
    """Active Alarm entry.

    Attributes:
        serial_no: Monotonically increasing unique sequence ID assigned by device firmware.
        equip_id: Logical Modbus device address / slave ID of reporting unit.
        alarm_id: Huawei alarm identifier code (maps to device alarm catalog, e.g. 2001, 2062).
        occur_time: Timestamp when the alarm condition was initially triggered.
        alarm_param: Auxiliary fault parameter (e.g. faulty PV string index, phase, or measured value).
        control_word: Raw 16-bit control bitmask containing severity level (bits 0-1) and routing flags.
        reason_id: Cause / sub-cause code specifying the precise failure mode or physical slot/location.

    """

    serial_no: int
    equip_id: int
    alarm_id: int
    occur_time: datetime
    alarm_param: int
    control_word: int
    reason_id: int

    @property
    def level(self) -> AlarmLevel:
        """Extract alarm severity level from control word (Bits 0-1)."""
        level_val = (((self.control_word >> 1) & 1) * 2) + (self.control_word & 1)
        return AlarmLevel(level_val)

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
    """Active Alarms Data File (File Type 0xA1 / 161)."""

    FILE_TYPE = 0xA1
    RECORD_STRUCT = "<IHHIIHH"

    def __init__(self, file_data: bytes) -> None:
        """Decode Active Alarms file."""
        self.alarms: list[ActiveAlarm] = []

        record_size = struct.calcsize(ActiveAlarmsDataFile.RECORD_STRUCT)
        if len(file_data) < record_size:
            return

        record_count = len(file_data) // record_size
        offset = 0

        try:
            for _ in range(record_count):
                (
                    serial_no,
                    equip_id,
                    alarm_id,
                    occur_time,
                    alarm_param,
                    control_word,
                    reason_id,
                ) = struct.unpack_from(
                    ActiveAlarmsDataFile.RECORD_STRUCT,
                    file_data,
                    offset,
                )
                offset += record_size

                self.alarms.append(
                    ActiveAlarm(
                        serial_no=serial_no,
                        equip_id=equip_id,
                        alarm_id=alarm_id,
                        occur_time=datetime.fromtimestamp(occur_time, tz=UTC),
                        alarm_param=alarm_param,
                        control_word=control_word,
                        reason_id=reason_id,
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


@dataclass(frozen=True, slots=True)
class HistoryAlarm:
    """Historical Alarm entry.

    Attributes:
        serial_no: Monotonically increasing unique sequence ID assigned by device firmware.
        equip_id: Logical Modbus device address / slave ID of reporting unit.
        alarm_id: Huawei alarm identifier code (maps to device alarm catalog, e.g. 2001, 2062).
        occur_time: Timestamp when the alarm condition was initially triggered.
        recover_time: Timestamp when the alarm condition cleared or recovered.
        alarm_param: Auxiliary fault parameter (e.g. faulty PV string index, phase, or measured value).
        control_word: Raw 16-bit control bitmask containing severity level (bits 0-1) and routing flags.
        reason_id: Cause / sub-cause code specifying the precise failure mode or physical slot/location.

    """

    serial_no: int
    equip_id: int
    alarm_id: int
    occur_time: datetime
    recover_time: datetime
    alarm_param: int
    control_word: int
    reason_id: int

    @property
    def level(self) -> AlarmLevel:
        """Extract alarm severity level from control word (Bits 0-1)."""
        level_val = (((self.control_word >> 1) & 1) * 2) + (self.control_word & 1)
        return AlarmLevel(level_val)

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
    """History Alarms Data File (File Type 0xA2 / 162)."""

    FILE_TYPE = 0xA2
    RECORD_STRUCT = "<IHHIIIHH"

    def __init__(self, file_data: bytes) -> None:
        """Decode History Alarms file."""
        self.alarms: list[HistoryAlarm] = []

        record_size = struct.calcsize(HistoryAlarmsDataFile.RECORD_STRUCT)
        if len(file_data) < record_size:
            return

        record_count = len(file_data) // record_size
        offset = 0

        try:
            for _ in range(record_count):
                (
                    serial_no,
                    equip_id,
                    alarm_id,
                    occur_time,
                    recover_time,
                    alarm_param,
                    control_word,
                    reason_id,
                ) = struct.unpack_from(
                    HistoryAlarmsDataFile.RECORD_STRUCT,
                    file_data,
                    offset,
                )
                offset += record_size

                self.alarms.append(
                    HistoryAlarm(
                        serial_no=serial_no,
                        equip_id=equip_id,
                        alarm_id=alarm_id,
                        occur_time=datetime.fromtimestamp(occur_time, tz=UTC),
                        recover_time=datetime.fromtimestamp(recover_time, tz=UTC),
                        alarm_param=alarm_param,
                        control_word=control_word,
                        reason_id=reason_id,
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
    """Decode Huawei Modbus 0x41/0x36 performance frames or their bare segment payloads.

    Each segment starts with a device timestamp and byte count, followed by signed
    32-bit samples. Monthly and yearly buckets advance by calendar months or years
    in UTC from the segment start, clamping the day to the end of shorter months.
    The cycle override applies to the fixed-interval request types.
    """

    _SEGMENT_HEADER = struct.Struct(">IB")
    _SAMPLE = struct.Struct(">i")

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

    # App cycles in seconds. Insulation and daily battery energy default to daily
    # samples. Absorbed energy follows the corresponding generation interval.
    DEFAULT_CYCLES: ClassVar[dict[PerformanceRequestType | int, int]] = {
        PerformanceRequestType.HOUR_POWER: 3600,
        PerformanceRequestType.DAY_POWER: 86400,
        PerformanceRequestType.MONTH_POWER: 2678400,
        PerformanceRequestType.YEAR_POWER: 32140800,
        PerformanceRequestType.OUTPUT_POWER: 300,
        PerformanceRequestType.INSULATION_RESISTANCE: 86400,
        PerformanceRequestType.BATTERY_CHARGE_AND_DISCHARGE_POWER: 300,
        PerformanceRequestType.METER_POWER: 300,
        PerformanceRequestType.BATTERY_CHARGE_DAY_POWER: 86400,
        PerformanceRequestType.BATTERY_DISCHARGE_DAY_POWER: 86400,
        PerformanceRequestType.ABSORB_HOUR_POWER: 3600,
        PerformanceRequestType.ABSORB_DAY_POWER: 86400,
        PerformanceRequestType.ABSORB_MONTH_POWER: 2678400,
        PerformanceRequestType.ABSORB_YEAR_POWER: 32140800,
    }

    def __init__(
        self,
        file_data: bytes | Iterable[PerformanceDataFrame],
        request_type: PerformanceRequestType | int = PerformanceRequestType.HOUR_POWER,
        cycle: int | None = None,
    ) -> None:
        """Decode frames in order, validating each frame's segment count."""
        self.data_points: list[PerformanceDataPoint] = []
        self.request_type = request_type

        with suppress(ValueError):
            request_type = PerformanceRequestType(request_type)

        gain = self.GAINS.get(request_type, 100)
        # like before, a cycle of 0 (or None) means the default for the request type
        cycle_seconds = cycle or self.DEFAULT_CYCLES.get(request_type, 300)
        if isinstance(file_data, bytes):
            self._decode_segments(file_data, None, request_type, gain, cycle_seconds)
        else:
            for frame in file_data:
                if frame.request_type != request_type:
                    msg = (
                        f"Performance data frame has request type {int(frame.request_type)}, "
                        f"expected {int(request_type)}"
                    )
                    raise DecodeError(msg)
                self._decode_segments(frame.payload, frame.segment_count, request_type, gain, cycle_seconds)

    def _decode_segments(
        self,
        payload: bytes,
        segment_count: int | None,
        request_type: PerformanceRequestType | int,
        gain: int,
        cycle: int,
    ) -> None:
        offset = 0
        decoded_segments = 0
        while offset < len(payload):
            if len(payload) - offset < self._SEGMENT_HEADER.size:
                msg = "Incomplete performance data segment header"
                raise DecodeError(msg)
            start_time, nbytes = self._SEGMENT_HEADER.unpack_from(payload, offset)
            offset += self._SEGMENT_HEADER.size
            end_offset = offset + nbytes
            if end_offset > len(payload) or nbytes % self._SAMPLE.size:
                msg = f"Invalid performance data segment length: {nbytes} bytes with {len(payload) - offset} remaining"
                raise DecodeError(msg)

            start = datetime.fromtimestamp(start_time, tz=UTC)
            for index, (raw_value,) in enumerate(self._SAMPLE.iter_unpack(payload[offset:end_offset])):
                self.data_points.append(
                    PerformanceDataPoint(
                        time=self._point_time(start, index, request_type, cycle),
                        request_type=request_type,
                        value=raw_value / gain,
                    )
                )
            offset = end_offset
            decoded_segments += 1

        if segment_count is not None and decoded_segments != segment_count:
            msg = f"Performance data frame declares {segment_count} segments, found {decoded_segments}"
            raise DecodeError(msg)

    @staticmethod
    def _point_time(
        start: datetime,
        index: int,
        request_type: PerformanceRequestType | int,
        cycle: int,
    ) -> datetime:
        if request_type in (PerformanceRequestType.MONTH_POWER, PerformanceRequestType.ABSORB_MONTH_POWER):
            years, month_index = divmod(start.month - 1 + index, 12)
            year, month = start.year + years, month_index + 1
        elif request_type in (PerformanceRequestType.YEAR_POWER, PerformanceRequestType.ABSORB_YEAR_POWER):
            year, month = start.year + index, start.month
        else:
            return start + timedelta(seconds=index * cycle)

        return start.replace(year=year, month=month, day=min(start.day, monthrange(year, month)[1]))
