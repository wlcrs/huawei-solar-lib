"""Register definitions from the Huawei inverter"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from functools import partial
from inspect import isclass
import typing as t

from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder

from huawei_solar.exceptions import (
    DecodeError,
    EncodeError,
    PeakPeriodsValidationError,
    TimeOfUsePeriodsException,
    WriteException,
)
import huawei_solar.register_names as rn
import huawei_solar.register_values as rv

if t.TYPE_CHECKING:
    # pylint: disable=all
    from .huawei_solar import AsyncHuaweiSolar


@dataclass
class RegisterDefinition:
    """Base class for register definitions."""

    def __init__(self, register, length, writeable=False, readable=True):
        self.register = register
        self.length = length
        self.writeable = writeable
        self.readable = readable

    def encode(self, data, builder: BinaryPayloadBuilder):
        raise NotImplementedError()

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        raise NotImplementedError()


class StringRegister(RegisterDefinition):
    """A string register."""

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        try:
            return decoder.decode_string(self.length * 2).decode("utf-8").strip("\0")
        except UnicodeDecodeError as err:
            raise DecodeError from err


class NumberRegister(RegisterDefinition):
    """Base class for number registers."""

    def __init__(
        self,
        unit,
        gain,
        register,
        length,
        decode_function_name,
        encode_function_name,
        writeable=False,
        readable=True,
        invalid_value=None,
    ):
        super().__init__(register, length, writeable, readable)
        self.unit = unit
        self.gain = gain

        self._decode_function_name = decode_function_name
        self._encode_function_name = encode_function_name
        self._invalid_value = invalid_value

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        result = getattr(decoder, self._decode_function_name)()

        if self._invalid_value is not None and result == self._invalid_value:
            return None

        if self.gain != 1:
            result /= self.gain
        if callable(self.unit):
            result = self.unit(result)
        elif isinstance(self.unit, dict):
            try:
                result = self.unit[result]
            except KeyError as err:
                raise DecodeError from err

        return result

    def encode(self, data, builder: BinaryPayloadBuilder):

        if self.unit == bool:
            data = int(data)
        elif isclass(self.unit):
            if not isinstance(data, self.unit):
                raise WriteException(f"Expected data of type {self.unit}, but got {type(data)}")

            if issubclass(self.unit, IntEnum):
                data = int(data)
            else:
                raise WriteException("Unsupported type.")

        if self.gain != 1:
            data *= self.gain

        data = int(data)  # it should always be an int!

        getattr(builder, self._encode_function_name)(data)


class U16Register(NumberRegister):
    """Unsigned 16-bit register"""

    def __init__(self, unit, gain, register, length, writeable=False, readable=True, ignore_invalid=False):
        super().__init__(
            unit,
            gain,
            register,
            length,
            "decode_16bit_uint",
            "add_16bit_uint",
            writeable=writeable,
            readable=readable,
            invalid_value=2**16 - 1 if not ignore_invalid else None,
        )


class U32Register(NumberRegister):
    """Unsigned 32-bit register"""

    def __init__(self, unit, gain, register, length, writeable=False):
        super().__init__(
            unit,
            gain,
            register,
            length,
            "decode_32bit_uint",
            "add_32bit_uint",
            writeable=writeable,
            invalid_value=2**32 - 1,
        )


class I16Register(NumberRegister):
    """Signed 16-bit register"""

    def __init__(self, unit, gain, register, length, writeable=False):
        super().__init__(
            unit,
            gain,
            register,
            length,
            "decode_16bit_int",
            "add_16bit_int",
            writeable=writeable,
            invalid_value=2**15 - 1,
        )


class I32Register(NumberRegister):
    """Signed 32-bit register."""

    def __init__(self, unit, gain, register, length, writeable=False):
        super().__init__(
            unit,
            gain,
            register,
            length,
            "decode_32bit_int",
            "add_32bit_int",
            writeable=writeable,
            invalid_value=2**31 - 1,
        )


class I32AbsoluteValueRegister(NumberRegister):
    """Signed 32-bit register, converted into the equivalent absolute number.

    Use case: for registers of which the value should always be interpreted
     as a positive number, but are (in some cases) being reported as a
     negative number.

    cfr. https://github.com/wlcrs/huawei_solar/issues/54

    """

    def __init__(self, unit, gain, register, length, writeable=False):
        super().__init__(
            unit,
            gain,
            register,
            length,
            "decode_32bit_int",
            "add_32bit_int",
            writeable=writeable,
            invalid_value=2**31 - 1,
        )

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        return abs(super().decode(decoder, inverter))


def bitfield_decoder(definition, bitfield):
    """Decodes a bitfield into a list of statuses."""
    result = []
    for key, value in definition.items():
        if isinstance(value, rv.OnOffBit):
            result.append(value.on_value if key & bitfield else value.off_value)
        elif key & bitfield:
            result.append(value)

    return result


class TimestampRegister(U32Register):
    """Timestamp register."""

    def __init__(self, register, length, writeable=False):
        super().__init__(None, 1, register, length, writeable=writeable)

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        value = super().decode(decoder, inverter)

        if value is None:
            return None

        try:
            return datetime.fromtimestamp(value - 60 * inverter.time_zone, timezone.utc)
        except OverflowError as err:
            raise DecodeError(f"Received invalid timestamp {value}") from err


@dataclass
class LG_RESU_TimeOfUsePeriod:  # pylint: disable=invalid-name
    start_time: int  # minutes sinds midnight
    end_time: int  # minutes sinds midnight
    electricity_price: float


class ChargeFlag(IntEnum):
    CHARGE = 0
    DISCHARGE = 1


@dataclass
class HUAWEI_LUNA2000_TimeOfUsePeriod:  # pylint: disable=invalid-name
    start_time: int  # minutes since midnight
    end_time: int  # minutes since midnight
    charge_flag: ChargeFlag
    days_effective: t.Tuple[bool, bool, bool, bool, bool, bool, bool]  # Valid on days Sunday to Saturday


LG_RESU_TOU_PERIODS = 10
HUAWEI_LUNA2000_TOU_PERIODS = 14


class TimeOfUseRegisters(RegisterDefinition):
    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        if inverter.battery_type == rv.StorageProductModel.LG_RESU:
            return self.decode_lg_resu(decoder)
        elif inverter.battery_type == rv.StorageProductModel.HUAWEI_LUNA2000:
            return self.decode_huawei_luna2000(decoder)
        return DecodeError(f"Invalid model to decode TOU Registers for: {inverter.battery_type}")

    def decode_lg_resu(self, decoder: BinaryPayloadDecoder) -> list[LG_RESU_TimeOfUsePeriod]:
        number_of_periods = decoder.decode_16bit_uint()
        assert number_of_periods <= LG_RESU_TOU_PERIODS

        periods = []
        for _ in range(LG_RESU_TOU_PERIODS):
            periods.append(
                LG_RESU_TimeOfUsePeriod(
                    decoder.decode_16bit_uint(),
                    decoder.decode_16bit_uint(),
                    decoder.decode_32bit_uint() / 1000,
                )
            )

        return periods[:number_of_periods]

    def _validate(self, data: t.Union[list[HUAWEI_LUNA2000_TimeOfUsePeriod], list[LG_RESU_TimeOfUsePeriod]]):
        # validate data type

        if len(data) == 0:
            return  # nothing to check

        if len({type(period) for period in data}) != 1:
            raise TimeOfUsePeriodsException("TOU periods cannot be of different types")

        # Sanity check of each period individually
        for tou_period in data:
            if tou_period.start_time < 0 or tou_period.end_time < 0:
                raise TimeOfUsePeriodsException("TOU period is invalid (Below zero)")
            if tou_period.start_time > 24 * 60 or tou_period.end_time > 24 * 60:
                raise TimeOfUsePeriodsException("TOU period is invalid (Spans over more than one day)")
            if tou_period.start_time >= tou_period.end_time:
                raise TimeOfUsePeriodsException("TOU period is invalid (start-time is greater than end-time)")

        if isinstance(data[0], HUAWEI_LUNA2000_TimeOfUsePeriod):
            return self._validate_huawei_luna2000(data)
        elif isinstance(data[0], LG_RESU_TimeOfUsePeriod):
            return self._validate_lg_resu(data)
        else:
            raise TimeOfUsePeriodsException("TOU period is of an unexpected type")

    def _validate_huawei_luna2000(self, data: list[HUAWEI_LUNA2000_TimeOfUsePeriod]):
        # Sanity checks between periods

        for day_idx in range(0, 7):
            # find all ranges that are valid for the given day
            active_periods: list[HUAWEI_LUNA2000_TimeOfUsePeriod] = list(
                filter(lambda period: period.days_effective[day_idx], data)
            )

            active_periods.sort(key=lambda a: a.start_time)

            for period_idx in range(1, len(active_periods)):
                current_period = active_periods[period_idx]
                prev_period = active_periods[period_idx - 1]
                if (
                    prev_period.start_time <= current_period.start_time < prev_period.end_time
                    or prev_period.start_time < current_period.end_time <= prev_period.end_time
                ):
                    raise TimeOfUsePeriodsException("TOU periods are overlapping")

    def _validate_lg_resu(self, data: list[HUAWEI_LUNA2000_TimeOfUsePeriod]):
        # Sanity checks between periods

        # make a copy of the data to sort
        sorted_periods: list[HUAWEI_LUNA2000_TimeOfUsePeriod] = data.copy()

        sorted_periods.sort(key=lambda a: a.start_time)

        for period_idx in range(1, len(sorted_periods)):
            current_period = sorted_periods[period_idx]
            prev_period = sorted_periods[period_idx - 1]
            if (
                prev_period.start_time <= current_period.start_time < prev_period.end_time
                or prev_period.start_time < current_period.end_time <= prev_period.end_time
            ):
                raise TimeOfUsePeriodsException("TOU periods are overlapping")

    def encode(
        self,
        data: t.Union[list[HUAWEI_LUNA2000_TimeOfUsePeriod], list[LG_RESU_TimeOfUsePeriod]],
        builder: BinaryPayloadBuilder,
    ):
        self._validate(data)

        if len(data) == 0 or isinstance(data[0], HUAWEI_LUNA2000_TimeOfUsePeriod):
            return self.encode_huawei_luna2000(data=data, builder=builder)
        elif isinstance(data[0], LG_RESU_TimeOfUsePeriod):
            return self.encode_lg_resu(data=data, builder=builder)
        else:
            raise EncodeError(f"Invalid dataclass to encode for TOU Registers: {type(data[0])}")

    def encode_lg_resu(self, data: list[LG_RESU_TimeOfUsePeriod], builder: BinaryPayloadBuilder):
        assert len(data) <= LG_RESU_TOU_PERIODS
        builder.add_16bit_uint(len(data))

        for period in data:
            builder.add_16bit_uint(period.start_time),
            builder.add_16bit_uint(period.end_time),
            builder.add_32bit_uint(period.electricity_price * 1000)

        # pad with empty periods
        for _ in range(len(data), LG_RESU_TOU_PERIODS):
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)
            builder.add_32bit_uint(0)

    def decode_huawei_luna2000(self, decoder: BinaryPayloadDecoder) -> list[HUAWEI_LUNA2000_TimeOfUsePeriod]:
        number_of_periods = decoder.decode_16bit_uint()
        assert number_of_periods <= HUAWEI_LUNA2000_TOU_PERIODS

        def _days_effective_parser(value):
            result = []
            mask = 0x1
            for _ in range(7):
                result.append((value & mask) != 0)
                mask = mask << 1

            return tuple(result)

        periods = []
        for _ in range(HUAWEI_LUNA2000_TOU_PERIODS):
            periods.append(
                HUAWEI_LUNA2000_TimeOfUsePeriod(
                    decoder.decode_16bit_uint(),
                    decoder.decode_16bit_uint(),
                    ChargeFlag(decoder.decode_8bit_uint()),
                    _days_effective_parser(decoder.decode_8bit_uint()),
                )
            )

        return periods[:number_of_periods]

    def encode_huawei_luna2000(self, data: list[HUAWEI_LUNA2000_TimeOfUsePeriod], builder: BinaryPayloadBuilder):
        assert len(data) <= HUAWEI_LUNA2000_TOU_PERIODS
        builder.add_16bit_uint(len(data))

        def _days_effective_builder(days_tuple):
            result = 0
            mask = 0x1
            for i in range(7):
                if days_tuple[i]:
                    result += mask
                mask = mask << 1

            return result

        for period in data:
            builder.add_16bit_uint(period.start_time),
            builder.add_16bit_uint(period.end_time),
            builder.add_8bit_uint(int(period.charge_flag))
            builder.add_8bit_uint(_days_effective_builder(period.days_effective))

        # pad with empty periods
        for _ in range(len(data), HUAWEI_LUNA2000_TOU_PERIODS):
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)


@dataclass
class ChargeDischargePeriod:
    start_time: int  # minutes sinds midnight
    end_time: int  # minutes sinds midnight
    power: int  # power in watts


CHARGE_DISCHARGE_PERIODS = 10


class ChargeDischargePeriodRegisters(RegisterDefinition):
    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar") -> list[ChargeDischargePeriod]:
        number_of_periods = decoder.decode_16bit_uint()
        assert number_of_periods <= CHARGE_DISCHARGE_PERIODS

        periods = []
        for _ in range(10):
            periods.append(
                ChargeDischargePeriod(
                    decoder.decode_16bit_uint(),
                    decoder.decode_16bit_uint(),
                    decoder.decode_32bit_int(),
                )
            )

        return periods[:number_of_periods]

    def encode(self, data: list[ChargeDischargePeriod], builder: BinaryPayloadBuilder):
        assert len(data) <= CHARGE_DISCHARGE_PERIODS
        builder.add_16bit_uint(len(data))

        for period in data:
            builder.add_16bit_uint(period.start_time),
            builder.add_16bit_uint(period.end_time),
            builder.add_32bit_uint(period.power)

        # pad with empty periods
        for _ in range(len(data), CHARGE_DISCHARGE_PERIODS):
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)
            builder.add_32bit_uint(0)


@dataclass
class PeakSettingPeriod:
    start_time: int  # minutes sinds midnight
    end_time: int  # minutes sinds midnight
    power: int  # power in watts
    days_effective: t.Tuple[bool, bool, bool, bool, bool, bool, bool]  # Valid on days Sunday to


PEAK_SETTING_PERIODS = 14


def _days_effective_builder(days_tuple):
    result = 0
    mask = 0x1
    for i in range(7):
        if days_tuple[i]:
            result += mask
        mask = mask << 1

    return result


def _days_effective_parser(value):
    result = []
    mask = 0x1
    for _ in range(7):
        result.append((value & mask) != 0)
        mask = mask << 1

    return tuple(result)


class PeakSettingPeriodRegisters(RegisterDefinition):
    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar") -> list[PeakSettingPeriod]:
        number_of_periods = decoder.decode_16bit_uint()

        # Safety check
        if number_of_periods > PEAK_SETTING_PERIODS:
            number_of_periods = PEAK_SETTING_PERIODS

        periods = []
        for _ in range(number_of_periods):

            start_time, end_time, peak_value, week_value = (
                decoder.decode_16bit_uint(),
                decoder.decode_16bit_uint(),
                decoder.decode_32bit_int(),
                decoder.decode_8bit_uint(),
            )

            if start_time != end_time and week_value != 0:
                periods.append(PeakSettingPeriod(start_time, end_time, peak_value, _days_effective_parser(week_value)))

        return periods[:number_of_periods]

    def _validate(self, data: list[PeakSettingPeriod]):

        for day_idx in range(0, 7):
            # find all ranges that are valid for the given day
            active_periods: list[PeakSettingPeriod] = list(filter(lambda period: period.days_effective[day_idx], data))

            if not len(active_periods):
                raise PeakPeriodsValidationError("All days of the week need to be covered")

            # require full day to be covered
            active_periods.sort(key=lambda a: a.start_time)

            if active_periods[0].start_time != 0:
                raise PeakPeriodsValidationError("Every day must be covered from 00:00")

            for period_idx in range(1, len(active_periods)):
                current_period = active_periods[period_idx]
                prev_period = active_periods[period_idx - 1]
                if (
                    prev_period.end_time != current_period.start_time
                    and prev_period.end_time + 1 != current_period.start_time
                ):
                    raise PeakPeriodsValidationError("All moments of each day need to be covered")

            if active_periods[-1].end_time not in ((24 * 60) - 1, 24 * 60):
                raise PeakPeriodsValidationError("Every day must be covered until 23:59")

    def encode(self, data: list[PeakSettingPeriod], builder: BinaryPayloadBuilder):
        if len(data) > PEAK_SETTING_PERIODS:
            data = data[:PEAK_SETTING_PERIODS]

        builder.add_16bit_uint(len(data))

        for period in data:
            builder.add_16bit_uint(period.start_time),
            builder.add_16bit_uint(period.end_time),
            builder.add_32bit_uint(period.power)
            builder.add_8bit_uint(_days_effective_builder(period.days_effective))

        # pad with empty periods
        for _ in range(len(data), PEAK_SETTING_PERIODS):
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)
            builder.add_32bit_uint(0)
            builder.add_8bit_uint(0)


REGISTERS: dict[str, RegisterDefinition] = {
    rn.MODEL_NAME: StringRegister(30000, 15),
    rn.SERIAL_NUMBER: StringRegister(30015, 10),
    rn.PN: StringRegister(30025, 10),
    rn.MODEL_ID: U16Register(None, 1, 30070, 1),
    rn.NB_PV_STRINGS: U16Register(None, 1, 30071, 1),
    rn.NB_MPP_TRACKS: U16Register(None, 1, 30072, 1),
    rn.RATED_POWER: U32Register("W", 1, 30073, 2),
    rn.P_MAX: U32Register("W", 1, 30075, 2),
    rn.S_MAX: U32Register("VA", 1, 30077, 2),
    rn.Q_MAX_OUT: I32Register("VAr", 1, 30079, 2),
    rn.Q_MAX_IN: I32Register("VAr", 1, 30081, 2),
    rn.STATE_1: U16Register(partial(bitfield_decoder, rv.STATE_CODES_1), 1, 32000, 1),
    rn.STATE_2: U16Register(partial(bitfield_decoder, rv.STATE_CODES_2), 1, 32002, 1),
    rn.STATE_3: U32Register(partial(bitfield_decoder, rv.STATE_CODES_3), 1, 32003, 2),
    rn.ALARM_1: U16Register(partial(bitfield_decoder, rv.ALARM_CODES_1), 1, 32008, 1, ignore_invalid=True),
    rn.ALARM_2: U16Register(partial(bitfield_decoder, rv.ALARM_CODES_2), 1, 32009, 1, ignore_invalid=True),
    rn.ALARM_3: U16Register(partial(bitfield_decoder, rv.ALARM_CODES_3), 1, 32010, 1),
    rn.INPUT_POWER: I32Register("W", 1, 32064, 2),
    rn.GRID_VOLTAGE: U16Register("V", 10, 32066, 1),
    rn.LINE_VOLTAGE_A_B: U16Register("V", 10, 32066, 1),
    rn.LINE_VOLTAGE_B_C: U16Register("V", 10, 32067, 1),
    rn.LINE_VOLTAGE_C_A: U16Register("V", 10, 32068, 1),
    rn.PHASE_A_VOLTAGE: U16Register("V", 10, 32069, 1),
    rn.PHASE_B_VOLTAGE: U16Register("V", 10, 32070, 1),
    rn.PHASE_C_VOLTAGE: U16Register("V", 10, 32071, 1),
    rn.GRID_CURRENT: I32Register("A", 1000, 32072, 2),
    rn.PHASE_A_CURRENT: I32Register("A", 1000, 32072, 2),
    rn.PHASE_B_CURRENT: I32Register("A", 1000, 32074, 2),
    rn.PHASE_C_CURRENT: I32Register("A", 1000, 32076, 2),
    rn.DAY_ACTIVE_POWER_PEAK: I32Register("W", 1, 32078, 2),
    rn.ACTIVE_POWER: I32Register("W", 1, 32080, 2),
    rn.REACTIVE_POWER: I32Register("VA", 1, 32082, 2),
    rn.POWER_FACTOR: I16Register(None, 1000, 32084, 1),
    rn.GRID_FREQUENCY: U16Register("Hz", 100, 32085, 1),
    rn.EFFICIENCY: U16Register("%", 100, 32086, 1),
    rn.INTERNAL_TEMPERATURE: I16Register("°C", 10, 32087, 1),
    rn.INSULATION_RESISTANCE: U16Register("MOhm", 100, 32088, 1),
    rn.DEVICE_STATUS: U16Register(rv.DEVICE_STATUS_DEFINITIONS, 1, 32089, 1),
    rn.FAULT_CODE: U16Register(None, 1, 32090, 1),
    rn.STARTUP_TIME: TimestampRegister(32091, 2),
    rn.SHUTDOWN_TIME: TimestampRegister(32093, 2),
    rn.ACCUMULATED_YIELD_ENERGY: U32Register("kWh", 100, 32106, 2),
    # last contact with server?
    rn.UNKNOWN_TIME_1: TimestampRegister(32110, 2),
    rn.DAILY_YIELD_ENERGY: U32Register("kWh", 100, 32114, 2),
    # something todo with startup time?
    rn.UNKNOWN_TIME_2: TimestampRegister(32156, 2),
    # something todo with shutdown time?
    rn.UNKNOWN_TIME_3: TimestampRegister(32160, 2),
    rn.UNKNOWN_TIME_4: TimestampRegister(35113, 2),  # installation time?
    rn.NB_OPTIMIZERS: U16Register(None, 1, 37200, 1),
    rn.NB_ONLINE_OPTIMIZERS: U16Register(None, 1, 37201, 1),
    rn.SYSTEM_TIME: TimestampRegister(40000, 2),
    rn.SYSTEM_TIME_RAW: U32Register("seconds", 1, 40000, 2),
    # seems to be the same as unknown_time_4
    rn.UNKNOWN_TIME_5: TimestampRegister(40500, 2),
    rn.STARTUP: U16Register(None, 1, 40200, 1, writeable=True, readable=False),
    rn.SHUTDOWN: U16Register(None, 1, 40201, 1, writeable=True, readable=False),
    rn.GRID_CODE: U16Register(rv.GRID_CODES, 1, 42000, 1),
    rn.TIME_ZONE: I16Register("min", 1, 43006, 1, writeable=True),
}


PV_REGISTERS = {
    rn.PV_01_VOLTAGE: I16Register("V", 10, 32016, 1),
    rn.PV_01_CURRENT: I16Register("A", 100, 32017, 1),
    rn.PV_02_VOLTAGE: I16Register("V", 10, 32018, 1),
    rn.PV_02_CURRENT: I16Register("A", 100, 32019, 1),
    rn.PV_03_VOLTAGE: I16Register("V", 10, 32020, 1),
    rn.PV_03_CURRENT: I16Register("A", 100, 32021, 1),
    rn.PV_04_VOLTAGE: I16Register("V", 10, 32022, 1),
    rn.PV_04_CURRENT: I16Register("A", 100, 32023, 1),
    rn.PV_05_VOLTAGE: I16Register("V", 10, 32024, 1),
    rn.PV_05_CURRENT: I16Register("A", 100, 32025, 1),
    rn.PV_06_VOLTAGE: I16Register("V", 10, 32026, 1),
    rn.PV_06_CURRENT: I16Register("A", 100, 32027, 1),
    rn.PV_07_VOLTAGE: I16Register("V", 10, 32028, 1),
    rn.PV_07_CURRENT: I16Register("A", 100, 32029, 1),
    rn.PV_08_VOLTAGE: I16Register("V", 10, 32030, 1),
    rn.PV_08_CURRENT: I16Register("A", 100, 32031, 1),
    rn.PV_09_VOLTAGE: I16Register("V", 10, 32032, 1),
    rn.PV_09_CURRENT: I16Register("A", 100, 32033, 1),
    rn.PV_10_VOLTAGE: I16Register("V", 10, 32034, 1),
    rn.PV_10_CURRENT: I16Register("A", 100, 32035, 1),
    rn.PV_11_VOLTAGE: I16Register("V", 10, 32036, 1),
    rn.PV_11_CURRENT: I16Register("A", 100, 32037, 1),
    rn.PV_12_VOLTAGE: I16Register("V", 10, 32038, 1),
    rn.PV_12_CURRENT: I16Register("A", 100, 32039, 1),
    rn.PV_13_VOLTAGE: I16Register("V", 10, 32040, 1),
    rn.PV_13_CURRENT: I16Register("A", 100, 32041, 1),
    rn.PV_14_VOLTAGE: I16Register("V", 10, 32042, 1),
    rn.PV_14_CURRENT: I16Register("A", 100, 32043, 1),
    rn.PV_15_VOLTAGE: I16Register("V", 10, 32044, 1),
    rn.PV_15_CURRENT: I16Register("A", 100, 32045, 1),
    rn.PV_16_VOLTAGE: I16Register("V", 10, 32046, 1),
    rn.PV_16_CURRENT: I16Register("A", 100, 32047, 1),
    rn.PV_17_VOLTAGE: I16Register("V", 10, 32048, 1),
    rn.PV_17_CURRENT: I16Register("A", 100, 32049, 1),
    rn.PV_18_VOLTAGE: I16Register("V", 10, 32050, 1),
    rn.PV_18_CURRENT: I16Register("A", 100, 32051, 1),
    rn.PV_19_VOLTAGE: I16Register("V", 10, 32052, 1),
    rn.PV_19_CURRENT: I16Register("A", 100, 32053, 1),
    rn.PV_20_VOLTAGE: I16Register("V", 10, 32054, 1),
    rn.PV_20_CURRENT: I16Register("A", 100, 32055, 1),
    rn.PV_21_VOLTAGE: I16Register("V", 10, 32056, 1),
    rn.PV_21_CURRENT: I16Register("A", 100, 32057, 1),
    rn.PV_22_VOLTAGE: I16Register("V", 10, 32058, 1),
    rn.PV_22_CURRENT: I16Register("A", 100, 32059, 1),
    rn.PV_23_VOLTAGE: I16Register("V", 10, 32060, 1),
    rn.PV_23_CURRENT: I16Register("A", 100, 32061, 1),
    rn.PV_24_VOLTAGE: I16Register("V", 10, 32062, 1),
    rn.PV_24_CURRENT: I16Register("A", 100, 32063, 1),
}

REGISTERS.update(PV_REGISTERS)

BATTERY_REGISTERS = {
    rn.STORAGE_UNIT_1_RUNNING_STATUS: U16Register(rv.StorageStatus, 1, 37000, 1),
    rn.STORAGE_UNIT_1_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 37001, 2),
    rn.STORAGE_UNIT_1_BUS_VOLTAGE: U16Register("V", 10, 37003, 1),
    rn.STORAGE_UNIT_1_STATE_OF_CAPACITY: U16Register("%", 10, 37004, 1),
    rn.STORAGE_UNIT_1_WORKING_MODE_B: U16Register(rv.StorageWorkingModesB, 1, 37006, 1),
    rn.STORAGE_UNIT_1_RATED_CHARGE_POWER: U32Register("W", 1, 37007, 2),
    rn.STORAGE_UNIT_1_RATED_DISCHARGE_POWER: U32Register("W", 1, 37009, 2),
    rn.STORAGE_UNIT_1_FAULT_ID: U16Register(None, 1, 37014, 1),
    rn.STORAGE_UNIT_1_CURRENT_DAY_CHARGE_CAPACITY: U32Register("kWh", 100, 37015, 2),
    rn.STORAGE_UNIT_1_CURRENT_DAY_DISCHARGE_CAPACITY: U32Register("kWh", 100, 37017, 2),
    rn.STORAGE_UNIT_1_BUS_CURRENT: I16Register("A", 10, 37021, 1),
    rn.STORAGE_UNIT_1_BATTERY_TEMPERATURE: I16Register("°C", 10, 37022, 1),
    rn.STORAGE_UNIT_1_REMAINING_CHARGE_DIS_CHARGE_TIME: U16Register("min", 1, 37025, 1),
    rn.STORAGE_UNIT_1_DCDC_VERSION: StringRegister(37026, 10),
    rn.STORAGE_UNIT_1_BMS_VERSION: StringRegister(37036, 10),
    rn.STORAGE_MAXIMUM_CHARGE_POWER: U32Register("W", 1, 37046, 2),
    rn.STORAGE_MAXIMUM_DISCHARGE_POWER: U32Register("W", 1, 37048, 2),
    rn.STORAGE_UNIT_1_SERIAL_NUMBER: StringRegister(37052, 10),
    rn.STORAGE_UNIT_1_TOTAL_CHARGE: U32Register("kWh", 100, 37066, 2),
    rn.STORAGE_UNIT_1_TOTAL_DISCHARGE: U32Register("kWh", 100, 37068, 2),
    rn.STORAGE_UNIT_2_SERIAL_NUMBER: StringRegister(37700, 10),
    rn.STORAGE_UNIT_2_STATE_OF_CAPACITY: U16Register("%", 10, 37738, 1),
    rn.STORAGE_UNIT_2_RUNNING_STATUS: U16Register(rv.StorageStatus, 1, 37741, 1),
    rn.STORAGE_UNIT_2_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 37743, 2),
    rn.STORAGE_UNIT_2_CURRENT_DAY_CHARGE_CAPACITY: U32Register("kWh", 100, 37746, 2),
    rn.STORAGE_UNIT_2_CURRENT_DAY_DISCHARGE_CAPACITY: U32Register("kWh", 100, 37748, 2),
    rn.STORAGE_UNIT_2_BUS_VOLTAGE: U16Register("V", 10, 37750, 1),
    rn.STORAGE_UNIT_2_BUS_CURRENT: I16Register("A", 10, 37751, 1),
    rn.STORAGE_UNIT_2_BATTERY_TEMPERATURE: I16Register("°C", 10, 37752, 1),
    rn.STORAGE_UNIT_2_TOTAL_CHARGE: U32Register("kWh", 100, 37753, 2),
    rn.STORAGE_UNIT_2_TOTAL_DISCHARGE: U32Register("kWh", 100, 37755, 2),
    rn.STORAGE_RATED_CAPACITY: U32Register("Wh", 1, 37758, 2),
    rn.STORAGE_STATE_OF_CAPACITY: U16Register("%", 10, 37760, 1),
    rn.STORAGE_RUNNING_STATUS: U16Register(rv.StorageStatus, 1, 37762, 1),
    rn.STORAGE_BUS_VOLTAGE: U16Register("V", 10, 37763, 1),
    rn.STORAGE_BUS_CURRENT: I16Register("A", 10, 37764, 1),
    rn.STORAGE_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 37765, 2),
    rn.STORAGE_TOTAL_CHARGE: U32Register("kWh", 100, 37780, 2),
    rn.STORAGE_TOTAL_DISCHARGE: U32Register("kWh", 100, 37782, 2),
    rn.STORAGE_CURRENT_DAY_CHARGE_CAPACITY: U32Register("kWh", 100, 37784, 2),
    rn.STORAGE_CURRENT_DAY_DISCHARGE_CAPACITY: U32Register("kWh", 100, 37786, 2),
    rn.STORAGE_UNIT_2_SOFTWARE_VERSION: StringRegister(37799, 15),
    rn.STORAGE_UNIT_1_SOFTWARE_VERSION: StringRegister(37814, 15),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_SERIAL_NUMBER: StringRegister(38200, 10),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_FIRMWARE_VERSION: StringRegister(38210, 15),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_WORKING_STATUS: U16Register(None, 1, 38228, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_STATE_OF_CAPACITY: U16Register("%", 10, 38229, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38233, 2),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_VOLTAGE: U16Register("V", 10, 38235, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_CURRENT: I16Register("A", 10, 38236, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_TOTAL_CHARGE: U32Register("kWh", 100, 38238, 2),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_TOTAL_DISCHARGE: U32Register("kWh", 100, 38240, 2),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_SERIAL_NUMBER: StringRegister(38242, 10),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_FIRMWARE_VERSION: StringRegister(38252, 15),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_WORKING_STATUS: U16Register(None, 1, 38270, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_STATE_OF_CAPACITY: U16Register("%", 10, 38271, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38275, 2),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_VOLTAGE: U16Register("V", 10, 38277, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_CURRENT: I16Register("A", 10, 38278, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_TOTAL_CHARGE: U32Register("kWh", 100, 38280, 2),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_TOTAL_DISCHARGE: U32Register("kWh", 100, 38282, 2),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_SERIAL_NUMBER: StringRegister(38284, 10),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_FIRMWARE_VERSION: StringRegister(38294, 15),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_WORKING_STATUS: U16Register(None, 1, 38312, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_STATE_OF_CAPACITY: U16Register("%", 10, 38313, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38317, 2),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_VOLTAGE: U16Register("V", 10, 38319, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_CURRENT: I16Register("A", 10, 38320, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_TOTAL_CHARGE: U32Register("kWh", 100, 38322, 2),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_TOTAL_DISCHARGE: U32Register("kWh", 100, 38324, 2),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_SERIAL_NUMBER: StringRegister(38326, 10),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_FIRMWARE_VERSION: StringRegister(38336, 15),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_WORKING_STATUS: U16Register(None, 1, 38354, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_STATE_OF_CAPACITY: U16Register("%", 10, 38355, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38359, 2),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_VOLTAGE: U16Register("V", 10, 38361, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_CURRENT: I16Register("A", 10, 38362, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_TOTAL_CHARGE: U32Register("kWh", 100, 38364, 2),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_TOTAL_DISCHARGE: U32Register("kWh", 100, 38366, 2),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_SERIAL_NUMBER: StringRegister(38368, 10),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_FIRMWARE_VERSION: StringRegister(38378, 15),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_WORKING_STATUS: U16Register(None, 1, 38396, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_STATE_OF_CAPACITY: U16Register("%", 10, 38397, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38401, 2),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_VOLTAGE: U16Register("V", 10, 38403, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_CURRENT: I16Register("A", 10, 38404, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_TOTAL_CHARGE: U32Register("kWh", 100, 38406, 2),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_TOTAL_DISCHARGE: U32Register("kWh", 100, 38408, 2),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_SERIAL_NUMBER: StringRegister(38410, 10),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_FIRMWARE_VERSION: StringRegister(38420, 15),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_WORKING_STATUS: U16Register(None, 1, 38438, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_STATE_OF_CAPACITY: U16Register("%", 10, 38439, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38443, 2),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_VOLTAGE: U16Register("V", 10, 38445, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_CURRENT: I16Register("A", 10, 38446, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_TOTAL_CHARGE: U32Register("kWh", 100, 38448, 2),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_TOTAL_DISCHARGE: U32Register("kWh", 100, 38450, 2),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38452, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38453, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38454, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38455, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38456, 1),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38457, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38458, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38459, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38460, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38461, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38462, 1),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38463, 1),
    rn.STORAGE_UNIT_1_PRODUCT_MODEL: U16Register(rv.StorageProductModel, 1, 47000, 1),
    rn.STORAGE_WORKING_MODE_A: I16Register(rv.StorageWorkingModesA, 1, 47004, 1),
    rn.STORAGE_TIME_OF_USE_PRICE: I16Register(bool, 1, 47027, 1),
    rn.STORAGE_TIME_OF_USE_PRICE_PERIODS: TimeOfUseRegisters(47028, 41, writeable=True),
    rn.STORAGE_LCOE: U32Register(None, 1000, 47069, 2),
    rn.STORAGE_MAXIMUM_CHARGING_POWER: U32Register("W", 1, 47075, 2, writeable=True),
    rn.STORAGE_MAXIMUM_DISCHARGING_POWER: U32Register("W", 1, 47077, 2, writeable=True),
    rn.STORAGE_POWER_LIMIT_GRID_TIED_POINT: I32Register("W", 1, 47079, 2),
    rn.STORAGE_CHARGING_CUTOFF_CAPACITY: U16Register("%", 10, 47081, 1, writeable=True),
    rn.STORAGE_DISCHARGING_CUTOFF_CAPACITY: U16Register("%", 10, 47082, 1, writeable=True),
    rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD: U16Register("min", 1, 47083, 1, writeable=True),
    rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_POWER: I32Register("min", 1, 47084, 2),
    rn.STORAGE_WORKING_MODE_SETTINGS: U16Register(rv.StorageWorkingModesC, 1, 47086, 1, writeable=True),
    rn.STORAGE_CHARGE_FROM_GRID_FUNCTION: U16Register(bool, 1, 47087, 1, writeable=True),
    rn.STORAGE_GRID_CHARGE_CUTOFF_STATE_OF_CHARGE: U16Register("%", 10, 47088, 1, writeable=True),
    rn.STORAGE_UNIT_2_PRODUCT_MODEL: U16Register(rv.StorageProductModel, 1, 47089, 1),
    rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE: U16Register(
        rv.StorageForcibleChargeDischarge, 1, 47100, 1, writeable=True
    ),
    rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC: U16Register("%", 10, 47101, 1, writeable=True),
    rn.STORAGE_BACKUP_POWER_STATE_OF_CHARGE: U16Register("%", 10, 47102, 1, writeable=True),
    rn.STORAGE_UNIT_1_NO: U16Register(None, 1, 47107, 1),
    rn.STORAGE_UNIT_2_NO: U16Register(None, 1, 47108, 1),
    rn.STORAGE_FIXED_CHARGING_AND_DISCHARGING_PERIODS: ChargeDischargePeriodRegisters(47200, 41, writeable=True),
    rn.STORAGE_POWER_OF_CHARGE_FROM_GRID: U32Register("W", 1, 47242, 2, writeable=True),
    rn.STORAGE_MAXIMUM_POWER_OF_CHARGE_FROM_GRID: U32Register("W", 1, 47244, 2, writeable=True),
    rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE: U16Register(None, 1, 47246, 1, writeable=True),
    rn.STORAGE_FORCIBLE_CHARGE_POWER: U32Register(None, 1, 47247, 2, writeable=True),
    rn.STORAGE_FORCIBLE_DISCHARGE_POWER: U32Register(None, 1, 47249, 2, writeable=True),
    rn.STORAGE_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS: TimeOfUseRegisters(47255, 43, writeable=True),
    rn.STORAGE_EXCESS_PV_ENERGY_USE_IN_TOU: U16Register(rv.StorageExcessPvEnergyUseInTOU, 1, 47299, 1, writeable=True),
    rn.ACTIVE_POWER_CONTROL_MODE: U16Register(rv.ActivePowerControlMode, 1, 47415, 1, writeable=True),
    rn.MAXIMUM_FEED_GRID_POWER_WATT: I32Register("W", 1, 47416, 2, writeable=True),
    rn.MAXIMUM_FEED_GRID_POWER_PERCENT: I16Register("%", 10, 47418, 1, writeable=True),
    rn.DONGLE_PLANT_MAXIMUM_CHARGE_FROM_GRID_POWER: U32Register("W", 1, 47590, 2, writeable=True),
    rn.BACKUP_SWITCH_TO_OFF_GRID: U16Register(None, 1, 47604, 1, writeable=True),
    rn.BACKUP_VOLTAGE_INDEPENDEND_OPERATION: U16Register(
        rv.BackupVoltageIndependentOperation, 1, 47604, 1, writeable=True
    ),
    rn.STORAGE_UNIT_1_PACK_1_NO: U16Register(None, 1, 47750, 1),
    rn.STORAGE_UNIT_1_PACK_2_NO: U16Register(None, 1, 47751, 1),
    rn.STORAGE_UNIT_1_PACK_3_NO: U16Register(None, 1, 47752, 1),
    rn.STORAGE_UNIT_2_PACK_1_NO: U16Register(None, 1, 47753, 1),
    rn.STORAGE_UNIT_2_PACK_2_NO: U16Register(None, 1, 47754, 1),
    rn.STORAGE_UNIT_2_PACK_3_NO: U16Register(None, 1, 47755, 1),
}
REGISTERS.update(BATTERY_REGISTERS)

CAPACITY_CONTROL_REGISTERS = {
    # We must check if we can read from these registers to know if this feature is supported
    # by the inverter/battery firmware
    rn.STORAGE_CAPACITY_CONTROL_MODE: U16Register(rv.StorageCapacityControlMode, 1, 47954, 1, writeable=True),
    rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING: U16Register("%", 10, 47955, 1, writeable=True),
    rn.STORAGE_CAPACITY_CONTROL_PERIODS: PeakSettingPeriodRegisters(47956, 64, writeable=True),
}

REGISTERS.update(CAPACITY_CONTROL_REGISTERS)

METER_REGISTERS = {
    rn.METER_STATUS: U16Register(rv.MeterStatus, 1, 37100, 1),
    rn.GRID_A_VOLTAGE: I32Register("V", 10, 37101, 2),
    rn.GRID_B_VOLTAGE: I32Register("V", 10, 37103, 2),
    rn.GRID_C_VOLTAGE: I32Register("V", 10, 37105, 2),
    rn.ACTIVE_GRID_A_CURRENT: I32Register("I", 100, 37107, 2),
    rn.ACTIVE_GRID_B_CURRENT: I32Register("I", 100, 37109, 2),
    rn.ACTIVE_GRID_C_CURRENT: I32Register("I", 100, 37111, 2),
    rn.POWER_METER_ACTIVE_POWER: I32Register("W", 1, 37113, 2),
    rn.POWER_METER_REACTIVE_POWER: I32Register("Var", 1, 37115, 2),
    rn.ACTIVE_GRID_POWER_FACTOR: I16Register(None, 1000, 37117, 1),
    rn.ACTIVE_GRID_FREQUENCY: I16Register("Hz", 100, 37118, 1),
    # cfr. https://github.com/wlcrs/huawei_solar/issues/54
    rn.GRID_EXPORTED_ENERGY: I32AbsoluteValueRegister("kWh", 100, 37119, 2),
    rn.GRID_ACCUMULATED_ENERGY: I32Register("kWh", 100, 37121, 2),
    rn.GRID_ACCUMULATED_REACTIVE_POWER: I32Register("kVarh", 100, 37123, 2),
    rn.METER_TYPE: U16Register(rv.MeterType, 1, 37125, 1),
    rn.ACTIVE_GRID_A_B_VOLTAGE: I32Register("V", 10, 37126, 2),
    rn.ACTIVE_GRID_B_C_VOLTAGE: I32Register("V", 10, 37128, 2),
    rn.ACTIVE_GRID_C_A_VOLTAGE: I32Register("V", 10, 37130, 2),
    rn.ACTIVE_GRID_A_POWER: I32Register("W", 1, 37132, 2),
    rn.ACTIVE_GRID_B_POWER: I32Register("W", 1, 37134, 2),
    rn.ACTIVE_GRID_C_POWER: I32Register("W", 1, 37136, 2),
    rn.METER_TYPE_CHECK: U16Register(rv.MeterTypeCheck, 1, 37125, 2),
}

REGISTERS.update(METER_REGISTERS)
