"""Register definitions from the Huawei inverter."""

# pyright: reportIncompatibleMethodOverride=false

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Flag, IntEnum, auto
from functools import partial
from inspect import isclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder

import huawei_solar.register_names as rn
import huawei_solar.register_values as rv
from huawei_solar.exceptions import (
    DecodeError,
    PeakPeriodsValidationError,
    TimeOfUsePeriodsException,
    WriteException,
)

if TYPE_CHECKING:
    from .huawei_solar import AsyncHuaweiSolar

T = TypeVar("T")

UnitType = None | str | dict[Any, T] | Callable[..., T]


class TargetDevice(Flag):
    """Target device for a register."""

    SUN2000 = auto()
    EMMA = auto()


class RegisterDefinition(Generic[T]):
    """Base class for register definitions."""

    unit: UnitType = None

    def __init__(
        self,
        register: int,
        length: int,
        writeable: bool = False,
        readable: bool = True,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Create RegisterDefinition."""
        self.register = register
        self.length = length
        self.writeable = writeable
        self.readable = readable
        self.target_device = target_device

    def encode(self, data: T, builder: BinaryPayloadBuilder):
        """Encode register to bytes."""
        raise NotImplementedError

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar") -> T:
        """Decode register to value."""
        raise NotImplementedError


class StringRegister(RegisterDefinition[str]):
    """A string register."""

    def decode(self, decoder: BinaryPayloadDecoder, _inverter: "AsyncHuaweiSolar"):
        """Decode string register."""
        str_bytes = cast(bytes, decoder.decode_string(self.length * 2))
        try:
            result = str_bytes.decode("utf-8")
        except UnicodeDecodeError as err:
            raise DecodeError from err
        else:
            return result.rstrip("\0")


class NumberRegister(RegisterDefinition[T], Generic[T]):
    """Base class for number registers."""

    def __init__(  # noqa: PLR0913
        self,
        unit: str | Callable[[int], T] | dict[int, T] | None,
        gain: int,
        register: int,
        length: int,
        decode_function_name: str,
        encode_function_name: str,
        writeable: bool = False,
        readable: bool = True,
        invalid_value: int | None = None,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Initialize NumberRegister."""
        super().__init__(
            register,
            length,
            writeable,
            readable,
            target_device=target_device,
        )
        self.unit = unit
        self.gain = gain

        self._decode_function_name = decode_function_name
        self._encode_function_name = encode_function_name
        self._invalid_value = invalid_value

    def decode(
        self,
        decoder: BinaryPayloadDecoder,
        inverter: "AsyncHuaweiSolar",  # noqa: ARG002
    ) -> T | None:
        """Decode number register."""
        result = cast(int, getattr(decoder, self._decode_function_name)())

        if self._invalid_value is not None and result == self._invalid_value:
            return None

        if callable(self.unit):
            assert self.gain == 1
            try:
                result = cast(T, self.unit(result))
            except ValueError as err:
                raise DecodeError from err
        elif isinstance(self.unit, dict):
            assert self.gain == 1
            try:
                result = cast(T, self.unit[result])
            except KeyError as err:
                raise DecodeError from err

        if self.gain != 1:
            result /= self.gain
        return result  # ignore: return-value

    def encode(self, data: T, builder: BinaryPayloadBuilder):
        """Encode number register."""
        if isinstance(data, int):
            int_data = data * self.gain
        elif isinstance(data, float):
            int_data = int(data * self.gain)  # it should always be an int!
        elif self.unit is bool:
            assert isinstance(data, bool)
            int_data = int(data)
            assert self.gain == 1
        elif isclass(self.unit) and issubclass(self.unit, IntEnum):
            assert isinstance(data, self.unit)
            int_data = int(data)
            assert self.gain == 1
        elif isclass(self.unit) and not isinstance(data, self.unit):
            raise WriteException(
                f"Expected data of type {self.unit}, but got {type(data)}",
            )
        else:
            raise WriteException(f"Unsupported type: {type(data)}.")

        getattr(builder, self._encode_function_name)(int_data)


class U16Register(NumberRegister[T], Generic[T]):
    """Unsigned 16-bit register."""

    def __init__(  # noqa: PLR0913
        self,
        unit,
        gain,
        register,
        writeable=False,
        readable=True,
        ignore_invalid=False,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Create Unsigned 16-bit register."""
        super().__init__(
            unit=unit,
            gain=gain,
            register=register,
            length=1,
            decode_function_name="decode_16bit_uint",
            encode_function_name="add_16bit_uint",
            writeable=writeable,
            readable=readable,
            invalid_value=2**16 - 1 if not ignore_invalid else None,
            target_device=target_device,
        )


class U32Register(NumberRegister[T], Generic[T]):
    """Unsigned 32-bit register."""

    def __init__(
        self,
        unit,
        gain,
        register,
        writeable=False,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Create Unsigned 32-bit register."""
        super().__init__(
            unit=unit,
            gain=gain,
            register=register,
            length=2,
            decode_function_name="decode_32bit_uint",
            encode_function_name="add_32bit_uint",
            writeable=writeable,
            invalid_value=2**32 - 1,
            target_device=target_device,
        )


class U64Register(NumberRegister[T], Generic[T]):
    """Unsigned 64-bit register."""

    def __init__(
        self,
        unit,
        gain,
        register,
        writeable=False,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Create Unsigned 64-bit register."""
        super().__init__(
            unit=unit,
            gain=gain,
            register=register,
            length=4,
            decode_function_name="decode_64bit_uint",
            encode_function_name="add_64bit_uint",
            writeable=writeable,
            invalid_value=2**63 - 1,
            target_device=target_device,
        )


class I16Register(NumberRegister[T], Generic[T]):
    """Signed 16-bit register."""

    def __init__(
        self,
        unit,
        gain,
        register,
        writeable=False,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Create Signed 16-bit register."""
        super().__init__(
            unit=unit,
            gain=gain,
            register=register,
            length=1,
            decode_function_name="decode_16bit_int",
            encode_function_name="add_16bit_int",
            writeable=writeable,
            invalid_value=2**15 - 1,
            target_device=target_device,
        )


class I32Register(NumberRegister[T], Generic[T]):
    """Signed 32-bit register."""

    def __init__(
        self,
        unit,
        gain,
        register,
        writeable=False,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Create Signed 32-bit register."""
        super().__init__(
            unit=unit,
            gain=gain,
            register=register,
            length=2,
            decode_function_name="decode_32bit_int",
            encode_function_name="add_32bit_int",
            writeable=writeable,
            invalid_value=2**31 - 1,
            target_device=target_device,
        )


class I64Register(NumberRegister[T], Generic[T]):
    """Signed 64-bit register."""

    def __init__(
        self,
        unit,
        gain,
        register,
        writeable=False,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Create Signed 64-bit register."""
        super().__init__(
            unit=unit,
            gain=gain,
            register=register,
            length=4,
            decode_function_name="decode_64bit_int",
            encode_function_name="add_64bit_int",
            writeable=writeable,
            invalid_value=2**63 - 1,
            target_device=target_device,
        )


class I32AbsoluteValueRegister(NumberRegister[T], Generic[T]):
    """Signed 32-bit register, converted into the equivalent absolute number.

    Use case: for registers of which the value should always be interpreted
     as a positive number, but are (in some cases) being reported as a
     negative number.

    cfr. https://github.com/wlcrs/huawei_solar/issues/54

    """

    def __init__(
        self,
        unit,
        gain,
        register,
        writeable=False,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Create Absolute value 32-bit register."""
        super().__init__(
            unit,
            gain,
            register,
            2,
            "decode_32bit_int",
            "add_32bit_int",
            writeable=writeable,
            invalid_value=2**31 - 1,
            target_device=target_device,
        )

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        """Decode 32-bit signed integer into absolute value."""
        value = super().decode(decoder, inverter)
        return abs(value) if value is not None else None


def bitfield_decoder(definition, bitfield):
    """Decode a bitfield into a list of statuses."""
    result = []
    for key, value in definition.items():
        if isinstance(value, rv.OnOffBit):
            result.append(value.on_value if key & bitfield else value.off_value)
        elif key & bitfield:
            result.append(value)

    return result


class TimestampRegister(U32Register[datetime]):
    """Timestamp register."""

    def __init__(
        self,
        register,
        writeable=False,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ):
        """Create timestamp register."""
        super().__init__(
            unit=None,
            gain=1,
            register=register,
            writeable=writeable,
            target_device=target_device,
        )

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        """Decode timestamp register."""
        value = super().decode(decoder, inverter)

        if value is None:
            return None

        if inverter.time_zone:
            value = value - 60 * inverter.time_zone

        # if DST is in effect, we need to shift another hour. However, the inverter
        # does not expose a register to check that.
        # Workaround: check the local time on the machine running the library if DST
        # is in effect there. We assume that both inverter and client are in the same time zone.

        if time.localtime(value).tm_isdst:
            value = value - 60 * 60

        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except OverflowError as err:
            raise DecodeError(f"Received invalid timestamp {value}") from err


@dataclass
class LG_RESU_TimeOfUsePeriod:
    """Time of use period of LG RESU."""

    start_time: int  # minutes since midnight
    end_time: int  # minutes since midnight
    electricity_price: float


class ChargeFlag(IntEnum):
    """Charge Flag."""

    CHARGE = 0
    DISCHARGE = 1


@dataclass
class HUAWEI_LUNA2000_TimeOfUsePeriod:
    """Time of use period of Huawei LUNA2000."""

    start_time: int  # minutes since midnight
    end_time: int  # minutes since midnight
    charge_flag: ChargeFlag
    days_effective: tuple[
        bool,
        bool,
        bool,
        bool,
        bool,
        bool,
        bool,
    ]  # Valid on days Sunday to Saturday


LG_RESU_TOU_PERIODS = 10


class LG_RESU_TimeOfUseRegisters(RegisterDefinition[list[LG_RESU_TimeOfUsePeriod]]):
    """Time of use register."""

    def decode(self, decoder: BinaryPayloadDecoder, _inverter: "AsyncHuaweiSolar"):
        """Decode time of use register."""
        number_of_periods = decoder.decode_16bit_uint()
        assert number_of_periods <= LG_RESU_TOU_PERIODS

        periods = [
            LG_RESU_TimeOfUsePeriod(
                decoder.decode_16bit_uint(),
                decoder.decode_16bit_uint(),
                decoder.decode_32bit_uint() / 1000,
            )
            for _ in range(LG_RESU_TOU_PERIODS)
        ]

        return periods[:number_of_periods]

    def _validate(
        self,
        data: list[LG_RESU_TimeOfUsePeriod],
    ):
        """Validate data type."""
        if len(data) == 0:
            return  # nothing to check

        # Sanity check of each period individually
        for tou_period in data:
            if tou_period.start_time < 0 or tou_period.end_time < 0:
                raise TimeOfUsePeriodsException("TOU period is invalid (Below zero)")
            if tou_period.start_time > 24 * 60 or tou_period.end_time > 24 * 60:
                raise TimeOfUsePeriodsException(
                    "TOU period is invalid (Spans over more than one day)",
                )
            if tou_period.start_time >= tou_period.end_time:
                raise TimeOfUsePeriodsException(
                    "TOU period is invalid (start-time is greater than end-time)",
                )

        # make a copy of the data to sort
        sorted_periods: list[LG_RESU_TimeOfUsePeriod] = data.copy()

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
        data: list[LG_RESU_TimeOfUsePeriod],
        builder: BinaryPayloadBuilder,
    ):
        """Encode Time Of Use Period registers."""
        self._validate(data)

        assert len(data) <= LG_RESU_TOU_PERIODS
        builder.add_16bit_uint(len(data))

        for period in data:
            builder.add_16bit_uint(period.start_time)
            builder.add_16bit_uint(period.end_time)
            builder.add_32bit_uint(int(period.electricity_price * 1000))

        # pad with empty periods
        for _ in range(len(data), LG_RESU_TOU_PERIODS):
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)
            builder.add_32bit_uint(0)


HUAWEI_LUNA2000_TOU_PERIODS = 14


class HUAWEI_LUNA2000_TimeOfUseRegisters(RegisterDefinition[list[HUAWEI_LUNA2000_TimeOfUsePeriod]]):
    """Time of use register."""

    def decode(self, decoder: BinaryPayloadDecoder, _inverter: "AsyncHuaweiSolar"):
        """Decode time of use register."""
        number_of_periods = decoder.decode_16bit_uint()
        assert number_of_periods <= HUAWEI_LUNA2000_TOU_PERIODS

        def _days_effective_parser(value):
            result = []
            mask = 0x1
            for _ in range(7):
                result.append((value & mask) != 0)
                mask = mask << 1

            return tuple(result)

        periods = [
            HUAWEI_LUNA2000_TimeOfUsePeriod(
                decoder.decode_16bit_uint(),
                decoder.decode_16bit_uint(),
                ChargeFlag(decoder.decode_8bit_uint()),
                _days_effective_parser(decoder.decode_8bit_uint()),
            )
            for _ in range(HUAWEI_LUNA2000_TOU_PERIODS)
        ]

        return periods[:number_of_periods]

    def _validate(
        self,
        data: list[HUAWEI_LUNA2000_TimeOfUsePeriod],
    ):
        """Validate data type."""
        if len(data) == 0:
            return  # nothing to check

        # Sanity check of each period individually
        for tou_period in data:
            if not isinstance(tou_period, HUAWEI_LUNA2000_TimeOfUsePeriod):
                raise TimeOfUsePeriodsException("TOU period is of an unexpected type")
            if tou_period.start_time < 0 or tou_period.end_time < 0:
                raise TimeOfUsePeriodsException("TOU period is invalid (Below zero)")
            if tou_period.start_time > 24 * 60 or tou_period.end_time > 24 * 60:
                raise TimeOfUsePeriodsException(
                    "TOU period is invalid (Spans over more than one day)",
                )
            if tou_period.start_time >= tou_period.end_time:
                raise TimeOfUsePeriodsException(
                    "TOU period is invalid (start-time is greater than end-time)",
                )

        for day_idx in range(7):
            # find all ranges that are valid for the given day
            active_periods: list[HUAWEI_LUNA2000_TimeOfUsePeriod] = list(
                filter(lambda period: period.days_effective[day_idx], data),
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

    def encode(
        self,
        data: list[HUAWEI_LUNA2000_TimeOfUsePeriod],
        builder: BinaryPayloadBuilder,
    ):
        """Encode Time Of Use Period registers."""
        self._validate(data)

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
            builder.add_16bit_uint(period.start_time)
            builder.add_16bit_uint(period.end_time)
            builder.add_8bit_uint(int(period.charge_flag))
            builder.add_8bit_uint(_days_effective_builder(period.days_effective))

        # pad with empty periods
        for _ in range(len(data), HUAWEI_LUNA2000_TOU_PERIODS):
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)


@dataclass
class ChargeDischargePeriod:
    """Charge or Discharge Period."""

    start_time: int  # minutes since midnight
    end_time: int  # minutes since midnight
    power: int  # power in watts


CHARGE_DISCHARGE_PERIODS = 10


class ChargeDischargePeriodRegisters(RegisterDefinition[list[ChargeDischargePeriod]]):
    """Charge or discharge period registers."""

    def decode(
        self,
        decoder: BinaryPayloadDecoder,
        inverter: "AsyncHuaweiSolar",  # noqa: ARG002
    ) -> list[ChargeDischargePeriod]:
        """Decode ChargeDischargePeriodRegisters."""
        number_of_periods = decoder.decode_16bit_uint()
        assert number_of_periods <= CHARGE_DISCHARGE_PERIODS

        periods = [
            ChargeDischargePeriod(
                decoder.decode_16bit_uint(),
                decoder.decode_16bit_uint(),
                decoder.decode_32bit_int(),
            )
            for _ in range(10)
        ]

        return periods[:number_of_periods]

    def encode(self, data: list[ChargeDischargePeriod], builder: BinaryPayloadBuilder):
        """Encode ChargeDischargePeriodRegisters."""
        assert len(data) <= CHARGE_DISCHARGE_PERIODS
        builder.add_16bit_uint(len(data))

        for period in data:
            builder.add_16bit_uint(period.start_time)
            builder.add_16bit_uint(period.end_time)
            builder.add_32bit_uint(period.power)

        # pad with empty periods
        for _ in range(len(data), CHARGE_DISCHARGE_PERIODS):
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)
            builder.add_32bit_uint(0)


@dataclass
class PeakSettingPeriod:
    """Peak Setting Period."""

    start_time: int  # minutes since midnight
    end_time: int  # minutes since midnight
    power: int  # power in watts
    days_effective: tuple[
        bool,
        bool,
        bool,
        bool,
        bool,
        bool,
        bool,
    ]  # Valid on days Sunday to


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


class PeakSettingPeriodRegisters(RegisterDefinition[list[PeakSettingPeriod]]):
    """Peak Setting Period registers."""

    def decode(
        self,
        decoder: BinaryPayloadDecoder,
        inverter: "AsyncHuaweiSolar",  # noqa: ARG002
    ) -> list[PeakSettingPeriod]:
        """Decode PeakSettingPeriodRegisters."""
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
                periods.append(
                    PeakSettingPeriod(
                        start_time,
                        end_time,
                        peak_value,
                        _days_effective_parser(week_value),
                    ),
                )

        return periods[:number_of_periods]

    def _validate(self, data: list[PeakSettingPeriod]):
        for day_idx in range(7):
            # find all ranges that are valid for the given day
            active_periods: list[PeakSettingPeriod] = list(
                filter(lambda period: period.days_effective[day_idx], data),
            )

            if not len(active_periods):
                raise PeakPeriodsValidationError(
                    "All days of the week need to be covered",
                )

            # require full day to be covered
            active_periods.sort(key=lambda a: a.start_time)

            if active_periods[0].start_time != 0:
                raise PeakPeriodsValidationError("Every day must be covered from 00:00")

            for period_idx in range(1, len(active_periods)):
                current_period = active_periods[period_idx]
                prev_period = active_periods[period_idx - 1]
                if current_period.start_time not in (
                    prev_period.end_time,
                    prev_period.end_time + 1,
                ):
                    raise PeakPeriodsValidationError(
                        "All moments of each day need to be covered",
                    )

            if active_periods[-1].end_time not in ((24 * 60) - 1, 24 * 60):
                raise PeakPeriodsValidationError(
                    "Every day must be covered until 23:59",
                )

    def encode(self, data: list[PeakSettingPeriod], builder: BinaryPayloadBuilder):
        """Encode PeakSettingPeriodRegisters."""
        if len(data) > PEAK_SETTING_PERIODS:
            data = data[:PEAK_SETTING_PERIODS]

        builder.add_16bit_uint(len(data))

        for period in data:
            builder.add_16bit_uint(period.start_time)
            builder.add_16bit_uint(period.end_time)
            builder.add_32bit_uint(period.power)
            builder.add_8bit_uint(_days_effective_builder(period.days_effective))

        # pad with empty periods
        for _ in range(len(data), PEAK_SETTING_PERIODS):
            builder.add_16bit_uint(0)
            builder.add_16bit_uint(0)
            builder.add_32bit_uint(0)
            builder.add_8bit_uint(0)


REGISTERS: dict[str, RegisterDefinition] = {
    rn.MODEL_NAME: StringRegister(30000, 15, target_device=TargetDevice.SUN2000 | TargetDevice.EMMA),
    rn.SERIAL_NUMBER: StringRegister(30015, 10, target_device=TargetDevice.SUN2000 | TargetDevice.EMMA),
    rn.PN: StringRegister(30025, 10),
    rn.FIRMWARE_VERSION: StringRegister(30035, 15),
    rn.SOFTWARE_VERSION: StringRegister(30050, 15),
    rn.PROTOCOL_VERSION_MODBUS: U32Register(None, 1, 30068),
    rn.MODEL_ID: U16Register(None, 1, 30070),
    rn.NB_PV_STRINGS: U16Register(None, 1, 30071),
    rn.NB_MPP_TRACKS: U16Register(None, 1, 30072),
    rn.RATED_POWER: U32Register("W", 1, 30073),
    rn.P_MAX: U32Register("W", 1, 30075),
    rn.S_MAX: U32Register("VA", 1, 30077),
    rn.Q_MAX_OUT: I32Register("var", 1, 30079),
    rn.Q_MAX_IN: I32Register("var", 1, 30081),
    rn.P_MAX_REAL: U32Register("W", 1, 30083),
    rn.S_MAX_REAL: U32Register("VA", 1, 30085),
    rn.PRODUCT_SALES_AREA: StringRegister(30105, 2),
    rn.PRODUCT_SOFTWARE_NUMBER: U16Register(None, 1, 30107),
    rn.PRODUCT_SOFTWARE_VERSION_NUMBER: U16Register(None, 1, 30108),
    rn.GRID_STANDARD_CODE_PROTOCOL_VERSION: U16Register(None, 1, 30110),
    rn.NUMBER_OF_PACKAGES_TO_BE_UPGRADED: U16Register(None, 1, 30111),
    rn.HARDWARE_FUNCTIONAL_UNIT_CONF_ID: U16Register(None, 1, 30206),
    rn.SUBDEVICE_SUPPORT_FLAG: U32Register(None, 1, 30207),
    rn.SUBDEVICE_IN_POSITION_FLAG: U32Register(None, 1, 30209),
    rn.FEATURE_MASK_1: U32Register(None, 1, 30211),
    rn.FEATURE_MASK_2: U32Register(None, 1, 30213),
    rn.FEATURE_MASK_3: U32Register(None, 1, 30215),
    rn.FEATURE_MASK_4: U32Register(None, 1, 30217),
    rn.REALTIME_MAX_ACTIVE_CAPABILITY: I32Register(None, 1, 30366),
    rn.REALTIME_MAX_INDUCTIVE_REACTIVE_CAPACITY: I32Register(None, 1, 30368),
    rn.OFFERING_NAME_OF_SOUTHBOUND_DEVICE_1: StringRegister(30561, 15),
    rn.OFFERING_NAME_OF_SOUTHBOUND_DEVICE_2: StringRegister(30576, 15),
    rn.OFFERING_NAME_OF_SOUTHBOUND_DEVICE_3: StringRegister(30591, 15),
    rn.HARDWARE_VERSION: StringRegister(31000, 15),
    rn.MONITORING_BOARD_SN: StringRegister(31015, 10),
    rn.MONITORING_SOFTWARE_VERSION: StringRegister(31025, 15),
    rn.MASTER_DSP_VERSION: StringRegister(31040, 15),
    rn.SLAVE_DSP_VERSION: StringRegister(31055, 15),
    rn.CPLD_VERSION: StringRegister(31070, 15),
    rn.AFCI_VERSION: StringRegister(31085, 15),
    rn.BUILTIN_PID_VERSION: StringRegister(31100, 15),
    rn.DC_MBUS_VERSION: StringRegister(31115, 15),
    rn.EL_MODULE_VERSION: StringRegister(31130, 15),
    rn.AFCI_2_VERSION: StringRegister(31145, 15),
    rn.REGKEY: StringRegister(31200, 10),
    rn.STATE_1: U16Register(partial(bitfield_decoder, rv.STATE_CODES_1), 1, 32000),
    rn.STATE_2: U16Register(partial(bitfield_decoder, rv.STATE_CODES_2), 1, 32002),
    rn.STATE_3: U32Register(partial(bitfield_decoder, rv.STATE_CODES_3), 1, 32003),
    rn.ALARM_1: U16Register(
        partial(bitfield_decoder, rv.ALARM_CODES_1),
        1,
        32008,
        ignore_invalid=True,
    ),
    rn.ALARM_2: U16Register(
        partial(bitfield_decoder, rv.ALARM_CODES_2),
        1,
        32009,
        ignore_invalid=True,
    ),
    rn.ALARM_3: U16Register(partial(bitfield_decoder, rv.ALARM_CODES_3), 1, 32010),
    rn.INPUT_POWER: I32Register("W", 1, 32064),
    rn.GRID_VOLTAGE: U16Register("V", 10, 32066),
    rn.LINE_VOLTAGE_A_B: U16Register("V", 10, 32066),
    rn.LINE_VOLTAGE_B_C: U16Register("V", 10, 32067),
    rn.LINE_VOLTAGE_C_A: U16Register("V", 10, 32068),
    rn.PHASE_A_VOLTAGE: U16Register("V", 10, 32069),
    rn.PHASE_B_VOLTAGE: U16Register("V", 10, 32070),
    rn.PHASE_C_VOLTAGE: U16Register("V", 10, 32071),
    rn.GRID_CURRENT: I32Register("A", 1000, 32072),
    rn.PHASE_A_CURRENT: I32Register("A", 1000, 32072),
    rn.PHASE_B_CURRENT: I32Register("A", 1000, 32074),
    rn.PHASE_C_CURRENT: I32Register("A", 1000, 32076),
    rn.DAY_ACTIVE_POWER_PEAK: I32Register("W", 1, 32078),
    rn.ACTIVE_POWER: I32Register("W", 1, 32080),
    rn.REACTIVE_POWER: I32Register("var", 1, 32082),
    rn.POWER_FACTOR: I16Register(None, 1000, 32084),
    rn.GRID_FREQUENCY: U16Register("Hz", 100, 32085),
    rn.EFFICIENCY: U16Register("%", 100, 32086),
    rn.INTERNAL_TEMPERATURE: I16Register("°C", 10, 32087),
    rn.INSULATION_RESISTANCE: U16Register("MOhm", 1000, 32088),
    rn.DEVICE_STATUS: U16Register(rv.DEVICE_STATUS_DEFINITIONS, 1, 32089),
    rn.FAULT_CODE: U16Register(None, 1, 32090),
    rn.STARTUP_TIME: TimestampRegister(32091),
    rn.SHUTDOWN_TIME: TimestampRegister(32093),
    rn.ACTIVE_POWER_FAST: I32Register("W", 1, 32095),
    rn.ACCUMULATED_YIELD_ENERGY: U32Register("kWh", 100, 32106),
    rn.TOTAL_DC_INPUT_POWER: U32Register("kWh", 100, 32108),
    rn.CURRENT_ELECTRICITY_GENERATION_STATISTICS_TIME: TimestampRegister(32110),
    rn.HOURLY_YIELD_ENERGY: U32Register("kWh", 100, 32112),
    rn.DAILY_YIELD_ENERGY: U32Register("kWh", 100, 32114),
    rn.MONTHLY_YIELD_ENERGY: U32Register("kWh", 100, 32116),
    rn.YEARLY_YIELD_ENERGY: U32Register("kWh", 100, 32118),
    rn.LATEST_ACTIVE_ALARM_SN: U32Register(None, 1, 32172),
    rn.LATEST_HISTORICAL_ALARM_SN: U32Register(None, 1, 32174),
    rn.TOTAL_BUS_VOLTAGE: I16Register("V", 10, 32176),
    rn.MAX_PV_VOLTAGE: I16Register("V", 10, 32177),
    rn.MIN_PV_VOLTAGE: I16Register("V", 10, 32178),
    rn.AVERAGE_PV_NEGATIVE_VOLTAGE_TO_GROUND: I16Register("V", 10, 32179),
    rn.MIN_PV_NEGATIVE_VOLTAGE_TO_GROUND: I16Register("V", 10, 32180),
    rn.MAX_PV_NEGATIVE_VOLTAGE_TO_GROUND: I16Register("V", 10, 32181),
    rn.INVERTER_TO_PE_VOLTAGE_TOLERANCE: U16Register("V", 1, 32182),
    rn.ISO_FEATURE_INFORMATION: U16Register(None, 1, 32183),
    rn.BUILTIN_PID_RUNNING_STATUS: U16Register(None, 1, 32190),
    rn.PV_NEGATIVE_VOLTAGE_TO_GROUND: I16Register("V", 10, 32191),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT1: U32Register("kWh", 100, 32212),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT2: U32Register("kWh", 100, 32214),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT3: U32Register("kWh", 100, 32216),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT4: U32Register("kWh", 100, 32218),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT5: U32Register("kWh", 100, 32220),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT6: U32Register("kWh", 100, 32222),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT7: U32Register("kWh", 100, 32224),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT8: U32Register("kWh", 100, 32226),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT9: U32Register("kWh", 100, 32228),
    rn.CUMULATIVE_DC_ENERGY_YIELD_MPPT10: U32Register("kWh", 100, 32230),
    rn.CAPBANK_RUNNING_TIME: U32Register("hour", 10, 35000),  # SUN2000MA-only register
    rn.INTERNAL_FAN_1_RUNNING_TIME: U32Register(
        "hour",
        10,
        35002,
    ),  # SUN2000MA-only register
    rn.INV_MODULE_A_TEMP: I16Register("°C", 10, 35021),  # SUN2000MA-only register
    rn.INV_MODULE_B_TEMP: I16Register("°C", 10, 35022),  # SUN2000MA-only register
    rn.INV_MODULE_C_TEMP: I16Register("°C", 10, 35023),  # SUN2000MA-only register
    rn.ANTI_REVERSE_MODULE_1_TEMP: I16Register(
        "°C",
        10,
        35024,
    ),  # SUN2000MA-only register
    rn.OUTPUT_BOARD_RELAY_AMBIENT_TEMP_MAX: I16Register(
        "°C",
        10,
        35025,
    ),  # SUN2000MA-only register
    rn.ANTI_REVERSE_MODULE_2_TEMP: I16Register(
        "°C",
        10,
        35027,
    ),  # SUN2000MA-only register
    rn.DC_TERMINAL_1_2_MAX_TEMP: I16Register(
        "°C",
        10,
        35028,
    ),  # SUN2000MA-only register
    rn.AC_TERMINAL_1_2_3_MAX_TEMP: I16Register(
        "°C",
        10,
        35029,
    ),  # SUN2000MA-only register
    rn.PHASE_A_DC_COMPONENT_DCI: I16Register(
        "A",
        1000,
        35038,
    ),  # SUN2000MA-only register
    rn.PHASE_B_DC_COMPONENT_DCI: I16Register(
        "A",
        1000,
        35039,
    ),  # SUN2000MA-only register
    rn.PHASE_C_DC_COMPONENT_DCI: I16Register(
        "A",
        1000,
        35040,
    ),  # SUN2000MA-only register
    rn.LEAKAGE_CURRENT_RCD: I16Register("mA", 1, 35041),  # SUN2000MA-only register
    rn.POSITIVE_BUS_VOLTAGE: I16Register("V", 10, 35042),  # SUN2000MA-only register
    rn.NEGATIVE_BUS_VOLTAGE: I16Register("V", 10, 35043),  # SUN2000MA-only register
    rn.BUS_NEGATIVE_VOLTAGE_TO_GROUND: I16Register(
        "V",
        10,
        35044,
    ),  # SUN2000MA-only register
    rn.NB_OPTIMIZERS: U16Register(None, 1, 37200),
    rn.NB_ONLINE_OPTIMIZERS: U16Register(None, 1, 37201),
    rn.SYSTEM_TIME: TimestampRegister(40000),
    rn.SYSTEM_TIME_RAW: U32Register("seconds", 1, 40000),
    rn.Q_U_CHARACTERISTIC_CURVE_MODEL: U16Register(
        None,
        1,
        40037,
        writeable=True,
    ),  # Documented as 'E16' instead of 'U16'
    rn.Q_U_SCHEDULING_TRIGGER_POWER_PERCENTAGE: I16Register(
        None,
        1,
        40038,
        writeable=True,
    ),
    rn.POWER_FACTOR_2: I16Register(None, 1000, 40122, writeable=True),
    rn.REACTIVE_POWER_COMPENSATION: I16Register(None, 1000, 40123, writeable=True),
    rn.REACTIVE_POWER_ADJUSTMENT_TIME: U16Register("seconds", 1, 40124, writeable=True),
    rn.ACTIVE_POWER_PERCENTAGE_DERATING: I16Register("%", 10, 40125, writeable=True),
    rn.ACTIVE_POWER_FIXED_VALUE_DERATING: U32Register("W", 1, 40126, writeable=True),
    rn.REACTIVE_POWER_COMPENSATION_AT_NIGHT: I16Register(
        None,
        1000,
        40128,
        writeable=True,
    ),
    rn.FIXED_REACTIVE_POWER_AT_NIGHT: I32Register("var", 1, 40129, writeable=True),
    rn.CHARACTERISTIC_CURVE_REACTIVE_POWER_ADJUSTMENT_TIME: U16Register(
        "seconds",
        1,
        40196,
        writeable=True,
    ),
    rn.PERCENT_APPARENT_POWER: U16Register("%", 10, 40197, writeable=True),
    rn.Q_U_SCHEDULING_EXIT_POWER_PERCENTAGE: I16Register("%", 1, 40198, writeable=True),
    rn.STARTUP: U16Register(None, 1, 40200, writeable=True, readable=False),
    rn.SHUTDOWN: U16Register(None, 1, 40201, writeable=True, readable=False),
    rn.GRID_CODE: U16Register(rv.GRID_CODES, 1, 42000),
    rn.MPPT_MULTIMODAL_SCANNING: U16Register(bool, 1, 42054, writeable=True),
    rn.MPPT_SCANNING_INTERVAL: U16Register("minutes", 1, 42055, writeable=True),
    rn.MPPT_PREDICTED_POWER: U32Register("W", 1, 42056),
    rn.TIME_ZONE: I16Register("min", 1, 43006, writeable=True),
    rn.WLAN_WAKEUP: I16Register(rv.WlanWakeup, 1, 45052, writeable=True),
    rn.SUN2000_EMMA: U16Register(bool, 1, 48020, writeable=True),
}


PV_REGISTERS = {
    rn.PV_01_VOLTAGE: I16Register("V", 10, 32016),
    rn.PV_01_CURRENT: I16Register("A", 100, 32017),
    rn.PV_02_VOLTAGE: I16Register("V", 10, 32018),
    rn.PV_02_CURRENT: I16Register("A", 100, 32019),
    rn.PV_03_VOLTAGE: I16Register("V", 10, 32020),
    rn.PV_03_CURRENT: I16Register("A", 100, 32021),
    rn.PV_04_VOLTAGE: I16Register("V", 10, 32022),
    rn.PV_04_CURRENT: I16Register("A", 100, 32023),
    rn.PV_05_VOLTAGE: I16Register("V", 10, 32024),
    rn.PV_05_CURRENT: I16Register("A", 100, 32025),
    rn.PV_06_VOLTAGE: I16Register("V", 10, 32026),
    rn.PV_06_CURRENT: I16Register("A", 100, 32027),
    rn.PV_07_VOLTAGE: I16Register("V", 10, 32028),
    rn.PV_07_CURRENT: I16Register("A", 100, 32029),
    rn.PV_08_VOLTAGE: I16Register("V", 10, 32030),
    rn.PV_08_CURRENT: I16Register("A", 100, 32031),
    rn.PV_09_VOLTAGE: I16Register("V", 10, 32032),
    rn.PV_09_CURRENT: I16Register("A", 100, 32033),
    rn.PV_10_VOLTAGE: I16Register("V", 10, 32034),
    rn.PV_10_CURRENT: I16Register("A", 100, 32035),
    rn.PV_11_VOLTAGE: I16Register("V", 10, 32036),
    rn.PV_11_CURRENT: I16Register("A", 100, 32037),
    rn.PV_12_VOLTAGE: I16Register("V", 10, 32038),
    rn.PV_12_CURRENT: I16Register("A", 100, 32039),
    rn.PV_13_VOLTAGE: I16Register("V", 10, 32040),
    rn.PV_13_CURRENT: I16Register("A", 100, 32041),
    rn.PV_14_VOLTAGE: I16Register("V", 10, 32042),
    rn.PV_14_CURRENT: I16Register("A", 100, 32043),
    rn.PV_15_VOLTAGE: I16Register("V", 10, 32044),
    rn.PV_15_CURRENT: I16Register("A", 100, 32045),
    rn.PV_16_VOLTAGE: I16Register("V", 10, 32046),
    rn.PV_16_CURRENT: I16Register("A", 100, 32047),
    rn.PV_17_VOLTAGE: I16Register("V", 10, 32048),
    rn.PV_17_CURRENT: I16Register("A", 100, 32049),
    rn.PV_18_VOLTAGE: I16Register("V", 10, 32050),
    rn.PV_18_CURRENT: I16Register("A", 100, 32051),
    rn.PV_19_VOLTAGE: I16Register("V", 10, 32052),
    rn.PV_19_CURRENT: I16Register("A", 100, 32053),
    rn.PV_20_VOLTAGE: I16Register("V", 10, 32054),
    rn.PV_20_CURRENT: I16Register("A", 100, 32055),
    rn.PV_21_VOLTAGE: I16Register("V", 10, 32056),
    rn.PV_21_CURRENT: I16Register("A", 100, 32057),
    rn.PV_22_VOLTAGE: I16Register("V", 10, 32058),
    rn.PV_22_CURRENT: I16Register("A", 100, 32059),
    rn.PV_23_VOLTAGE: I16Register("V", 10, 32060),
    rn.PV_23_CURRENT: I16Register("A", 100, 32061),
    rn.PV_24_VOLTAGE: I16Register("V", 10, 32062),
    rn.PV_24_CURRENT: I16Register("A", 100, 32063),
}

REGISTERS.update(PV_REGISTERS)

BATTERY_REGISTERS = {
    rn.STORAGE_UNIT_1_RUNNING_STATUS: U16Register(rv.StorageStatus, 1, 37000),
    rn.STORAGE_UNIT_1_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 37001),
    rn.STORAGE_UNIT_1_BUS_VOLTAGE: U16Register("V", 10, 37003),
    rn.STORAGE_UNIT_1_STATE_OF_CAPACITY: U16Register("%", 10, 37004),
    rn.STORAGE_UNIT_1_WORKING_MODE_B: U16Register(rv.StorageWorkingModesB, 1, 37006),
    rn.STORAGE_UNIT_1_RATED_CHARGE_POWER: U32Register("W", 1, 37007),
    rn.STORAGE_UNIT_1_RATED_DISCHARGE_POWER: U32Register("W", 1, 37009),
    rn.STORAGE_UNIT_1_FAULT_ID: U16Register(None, 1, 37014),
    rn.STORAGE_UNIT_1_CURRENT_DAY_CHARGE_CAPACITY: U32Register("kWh", 100, 37015),
    rn.STORAGE_UNIT_1_CURRENT_DAY_DISCHARGE_CAPACITY: U32Register("kWh", 100, 37017),
    rn.STORAGE_UNIT_1_BUS_CURRENT: I16Register("A", 10, 37021),
    rn.STORAGE_UNIT_1_BATTERY_TEMPERATURE: I16Register("°C", 10, 37022),
    rn.STORAGE_UNIT_1_REMAINING_CHARGE_DIS_CHARGE_TIME: U16Register("min", 1, 37025),
    rn.STORAGE_UNIT_1_DCDC_VERSION: StringRegister(37026, 10),
    rn.STORAGE_UNIT_1_BMS_VERSION: StringRegister(37036, 10),
    rn.STORAGE_MAXIMUM_CHARGE_POWER: U32Register("W", 1, 37046),
    rn.STORAGE_MAXIMUM_DISCHARGE_POWER: U32Register("W", 1, 37048),
    rn.STORAGE_UNIT_1_SERIAL_NUMBER: StringRegister(37052, 10),
    rn.STORAGE_UNIT_1_TOTAL_CHARGE: U32Register("kWh", 100, 37066),
    rn.STORAGE_UNIT_1_TOTAL_DISCHARGE: U32Register("kWh", 100, 37068),
    rn.STORAGE_UNIT_2_SERIAL_NUMBER: StringRegister(37700, 10),
    rn.STORAGE_UNIT_2_STATE_OF_CAPACITY: U16Register("%", 10, 37738),
    rn.STORAGE_UNIT_2_RUNNING_STATUS: U16Register(rv.StorageStatus, 1, 37741),
    rn.STORAGE_UNIT_2_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 37743),
    rn.STORAGE_UNIT_2_CURRENT_DAY_CHARGE_CAPACITY: U32Register("kWh", 100, 37746),
    rn.STORAGE_UNIT_2_CURRENT_DAY_DISCHARGE_CAPACITY: U32Register("kWh", 100, 37748),
    rn.STORAGE_UNIT_2_BUS_VOLTAGE: U16Register("V", 10, 37750),
    rn.STORAGE_UNIT_2_BUS_CURRENT: I16Register("A", 10, 37751),
    rn.STORAGE_UNIT_2_BATTERY_TEMPERATURE: I16Register("°C", 10, 37752),
    rn.STORAGE_UNIT_2_TOTAL_CHARGE: U32Register("kWh", 100, 37753),
    rn.STORAGE_UNIT_2_TOTAL_DISCHARGE: U32Register("kWh", 100, 37755),
    rn.STORAGE_RATED_CAPACITY: U32Register("Wh", 1, 37758),
    rn.STORAGE_STATE_OF_CAPACITY: U16Register("%", 10, 37760),
    rn.STORAGE_RUNNING_STATUS: U16Register(rv.StorageStatus, 1, 37762),
    rn.STORAGE_BUS_VOLTAGE: U16Register("V", 10, 37763),
    rn.STORAGE_BUS_CURRENT: I16Register("A", 10, 37764),
    rn.STORAGE_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 37765),
    rn.STORAGE_TOTAL_CHARGE: U32Register("kWh", 100, 37780),
    rn.STORAGE_TOTAL_DISCHARGE: U32Register("kWh", 100, 37782),
    rn.STORAGE_CURRENT_DAY_CHARGE_CAPACITY: U32Register("kWh", 100, 37784),
    rn.STORAGE_CURRENT_DAY_DISCHARGE_CAPACITY: U32Register("kWh", 100, 37786),
    rn.STORAGE_UNIT_2_SOFTWARE_VERSION: StringRegister(37799, 15),
    rn.STORAGE_UNIT_1_SOFTWARE_VERSION: StringRegister(37814, 15),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_SERIAL_NUMBER: StringRegister(38200, 10),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_FIRMWARE_VERSION: StringRegister(38210, 15),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_WORKING_STATUS: U16Register(None, 1, 38228),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_STATE_OF_CAPACITY: U16Register("%", 10, 38229),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38233),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_VOLTAGE: U16Register("V", 10, 38235),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_CURRENT: I16Register("A", 10, 38236),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_TOTAL_CHARGE: U32Register("kWh", 100, 38238),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_TOTAL_DISCHARGE: U32Register("kWh", 100, 38240),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_SERIAL_NUMBER: StringRegister(38242, 10),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_FIRMWARE_VERSION: StringRegister(38252, 15),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_WORKING_STATUS: U16Register(None, 1, 38270),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_STATE_OF_CAPACITY: U16Register("%", 10, 38271),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38275),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_VOLTAGE: U16Register("V", 10, 38277),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_CURRENT: I16Register("A", 10, 38278),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_TOTAL_CHARGE: U32Register("kWh", 100, 38280),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_TOTAL_DISCHARGE: U32Register("kWh", 100, 38282),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_SERIAL_NUMBER: StringRegister(38284, 10),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_FIRMWARE_VERSION: StringRegister(38294, 15),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_WORKING_STATUS: U16Register(None, 1, 38312),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_STATE_OF_CAPACITY: U16Register("%", 10, 38313),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38317),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_VOLTAGE: U16Register("V", 10, 38319),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_CURRENT: I16Register("A", 10, 38320),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_TOTAL_CHARGE: U32Register("kWh", 100, 38322),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_TOTAL_DISCHARGE: U32Register("kWh", 100, 38324),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_SERIAL_NUMBER: StringRegister(38326, 10),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_FIRMWARE_VERSION: StringRegister(38336, 15),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_WORKING_STATUS: U16Register(None, 1, 38354),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_STATE_OF_CAPACITY: U16Register("%", 10, 38355),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38359),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_VOLTAGE: U16Register("V", 10, 38361),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_CURRENT: I16Register("A", 10, 38362),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_TOTAL_CHARGE: U32Register("kWh", 100, 38364),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_TOTAL_DISCHARGE: U32Register("kWh", 100, 38366),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_SERIAL_NUMBER: StringRegister(38368, 10),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_FIRMWARE_VERSION: StringRegister(38378, 15),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_WORKING_STATUS: U16Register(None, 1, 38396),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_STATE_OF_CAPACITY: U16Register("%", 10, 38397),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38401),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_VOLTAGE: U16Register("V", 10, 38403),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_CURRENT: I16Register("A", 10, 38404),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_TOTAL_CHARGE: U32Register("kWh", 100, 38406),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_TOTAL_DISCHARGE: U32Register("kWh", 100, 38408),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_SERIAL_NUMBER: StringRegister(38410, 10),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_FIRMWARE_VERSION: StringRegister(38420, 15),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_WORKING_STATUS: U16Register(None, 1, 38438),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_STATE_OF_CAPACITY: U16Register("%", 10, 38439),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 38443),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_VOLTAGE: U16Register("V", 10, 38445),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_CURRENT: I16Register("A", 10, 38446),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_TOTAL_CHARGE: U32Register("kWh", 100, 38448),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_TOTAL_DISCHARGE: U32Register("kWh", 100, 38450),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38452),
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38453),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38454),
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38455),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38456),
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38457),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38458),
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38459),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38460),
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38461),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_MAXIMUM_TEMPERATURE: I16Register("°C", 10, 38462),
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_MINIMUM_TEMPERATURE: I16Register("°C", 10, 38463),
    rn.STORAGE_UNIT_1_PRODUCT_MODEL: U16Register(rv.StorageProductModel, 1, 47000),
    rn.STORAGE_WORKING_MODE_A: I16Register(rv.StorageWorkingModesA, 1, 47004),
    rn.STORAGE_TIME_OF_USE_PRICE: I16Register(bool, 1, 47027),
    rn.STORAGE_LG_RESU_TIME_OF_USE_PRICE_PERIODS: LG_RESU_TimeOfUseRegisters(47028, 41, writeable=True),
    rn.STORAGE_HUAWEI_LUNA2000_TIME_OF_USE_PRICE_PERIODS: HUAWEI_LUNA2000_TimeOfUseRegisters(47028, 41, writeable=True),
    rn.STORAGE_LCOE: U32Register(None, 1000, 47069),
    rn.STORAGE_MAXIMUM_CHARGING_POWER: U32Register("W", 1, 47075, writeable=True),
    rn.STORAGE_MAXIMUM_DISCHARGING_POWER: U32Register("W", 1, 47077, writeable=True),
    rn.STORAGE_POWER_LIMIT_GRID_TIED_POINT: I32Register("W", 1, 47079),
    rn.STORAGE_CHARGING_CUTOFF_CAPACITY: U16Register("%", 10, 47081, writeable=True),
    rn.STORAGE_DISCHARGING_CUTOFF_CAPACITY: U16Register("%", 10, 47082, writeable=True),
    rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD: U16Register(
        "min",
        1,
        47083,
        writeable=True,
    ),
    rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_POWER: I32Register("W", 1, 47084),
    rn.STORAGE_WORKING_MODE_SETTINGS: U16Register(
        rv.StorageWorkingModesC,
        1,
        47086,
        writeable=True,
    ),
    rn.STORAGE_CHARGE_FROM_GRID_FUNCTION: U16Register(bool, 1, 47087, writeable=True),
    rn.STORAGE_GRID_CHARGE_CUTOFF_STATE_OF_CHARGE: U16Register(
        "%",
        10,
        47088,
        writeable=True,
    ),
    rn.STORAGE_UNIT_2_PRODUCT_MODEL: U16Register(rv.StorageProductModel, 1, 47089),
    rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE: U16Register(
        rv.StorageForcibleChargeDischarge,
        1,
        47100,
        writeable=True,
    ),
    rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC: U16Register(
        "%",
        10,
        47101,
        writeable=True,
    ),
    rn.STORAGE_BACKUP_POWER_STATE_OF_CHARGE: U16Register(
        "%",
        10,
        47102,
        writeable=True,
    ),
    rn.STORAGE_UNIT_1_NO: U16Register(None, 1, 47107),
    rn.STORAGE_UNIT_2_NO: U16Register(None, 1, 47108),
    rn.STORAGE_FIXED_CHARGING_AND_DISCHARGING_PERIODS: ChargeDischargePeriodRegisters(
        47200,
        41,
        writeable=True,
    ),
    rn.STORAGE_POWER_OF_CHARGE_FROM_GRID: U32Register("W", 1, 47242, writeable=True),
    rn.STORAGE_MAXIMUM_POWER_OF_CHARGE_FROM_GRID: U32Register(
        "W",
        1,
        47244,
        writeable=True,
    ),
    rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE: U16Register(
        rv.StorageForcibleChargeDischargeTargetMode,
        1,
        47246,
        writeable=True,
    ),
    rn.STORAGE_FORCIBLE_CHARGE_POWER: U32Register(None, 1, 47247, writeable=True),
    rn.STORAGE_FORCIBLE_DISCHARGE_POWER: U32Register(None, 1, 47249, writeable=True),
    rn.STORAGE_LG_RESU_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS: LG_RESU_TimeOfUseRegisters(
        47255,
        43,
        writeable=True,
    ),
    rn.STORAGE_HUAWEI_LUNA2000_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS: HUAWEI_LUNA2000_TimeOfUseRegisters(
        47255,
        43,
        writeable=True,
    ),
    rn.STORAGE_EXCESS_PV_ENERGY_USE_IN_TOU: U16Register(
        rv.StorageExcessPvEnergyUseInTOU,
        1,
        47299,
        writeable=True,
    ),
    rn.ACTIVE_POWER_CONTROL_MODE: U16Register(
        rv.ActivePowerControlMode,
        1,
        47415,
        writeable=True,
    ),
    rn.MAXIMUM_FEED_GRID_POWER_WATT: I32Register("W", 1, 47416, writeable=True),
    rn.MAXIMUM_FEED_GRID_POWER_PERCENT: I16Register("%", 10, 47418, writeable=True),
    rn.REMOTE_CHARGE_DISCHARGE_CONTROL_MODE: I16Register(
        rv.RemoteChargeDischargeControlMode,
        1,
        47589,
        writeable=True,
    ),
    rn.DONGLE_PLANT_MAXIMUM_CHARGE_FROM_GRID_POWER: U32Register(
        "W",
        1,
        47590,
        writeable=True,
    ),
    rn.BACKUP_SWITCH_TO_OFF_GRID: U16Register(None, 1, 47604, writeable=True),
    rn.BACKUP_VOLTAGE_INDEPENDENT_OPERATION: U16Register(
        rv.BackupVoltageIndependentOperation,
        1,
        47605,
        writeable=True,
    ),
    rn.DEFAULT_MAXIMUM_FEED_IN_POWER: I32Register("W", 1, 47675, writeable=True),
    rn.DEFAULT_ACTIVE_POWER_CHANGE_GRADIENT: U32Register("%/s", 1000, 47677),
    rn.STORAGE_UNIT_1_PACK_1_NO: U16Register(None, 1, 47750),
    rn.STORAGE_UNIT_1_PACK_2_NO: U16Register(None, 1, 47751),
    rn.STORAGE_UNIT_1_PACK_3_NO: U16Register(None, 1, 47752),
    rn.STORAGE_UNIT_2_PACK_1_NO: U16Register(None, 1, 47753),
    rn.STORAGE_UNIT_2_PACK_2_NO: U16Register(None, 1, 47754),
    rn.STORAGE_UNIT_2_PACK_3_NO: U16Register(None, 1, 47755),
}
REGISTERS.update(BATTERY_REGISTERS)

CAPACITY_CONTROL_REGISTERS = {
    # We must check if we can read from these registers to know if this feature is supported
    # by the inverter/battery firmware
    rn.STORAGE_CAPACITY_CONTROL_MODE: U16Register(
        rv.StorageCapacityControlMode,
        1,
        47954,
        writeable=True,
    ),
    rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING: U16Register(
        "%",
        10,
        47955,
        writeable=True,
    ),
    rn.STORAGE_CAPACITY_CONTROL_PERIODS: PeakSettingPeriodRegisters(
        47956,
        64,
        writeable=True,
    ),
}

REGISTERS.update(CAPACITY_CONTROL_REGISTERS)

EMMA_REGISTERS = {
    rn.EMMA_SOFTWARE_VERSION: StringRegister(30035, 15, target_device=TargetDevice.EMMA),
    rn.EMMA_MODEL: StringRegister(30222, 20, target_device=TargetDevice.EMMA),
    rn.INVERTER_TOTAL_ABSORBED_ENERGY: U64Register("kWh", 100, 30302, target_device=TargetDevice.EMMA),
    rn.ENERGY_CHARGED_TODAY: U32Register("kWh", 100, 30306, target_device=TargetDevice.EMMA),
    rn.TOTAL_CHARGED_ENERGY: U64Register("kWh", 100, 30308, target_device=TargetDevice.EMMA),
    rn.ENERGY_DISCHARGED_TODAY: U32Register("kWh", 100, 30312, target_device=TargetDevice.EMMA),
    rn.TOTAL_DISCHARGED_ENERGY: U64Register("kWh", 100, 30314, target_device=TargetDevice.EMMA),
    rn.ESS_CHARGEABLE_ENERGY: U32Register("kWh", 1000, 30318, target_device=TargetDevice.EMMA),
    rn.ESS_DISCHARGEABLE_ENERGY: U32Register("kWh", 1000, 30320, target_device=TargetDevice.EMMA),
    rn.RATED_ESS_CAPACITY: U32Register("kWh", 1000, 30322, target_device=TargetDevice.EMMA),
    rn.CONSUMPTION_TODAY: U32Register("kWh", 100, 30324, target_device=TargetDevice.EMMA),
    rn.TOTAL_ENERGY_CONSUMPTION: U64Register("kWh", 100, 30326, target_device=TargetDevice.EMMA),
    rn.FEED_IN_TO_GRID_TODAY: U32Register("kWh", 100, 30330, target_device=TargetDevice.EMMA),
    rn.TOTAL_FEED_IN_TO_GRID: U64Register("kWh", 100, 30332, target_device=TargetDevice.EMMA),
    rn.SUPPLY_FROM_GRID_TODAY: U32Register("kWh", 100, 30336, target_device=TargetDevice.EMMA),
    rn.TOTAL_SUPPLY_FROM_GRID: U64Register("kWh", 100, 30338, target_device=TargetDevice.EMMA),
    rn.INVERTER_ENERGY_YIELD_TODAY: U32Register("kWh", 100, 30342, target_device=TargetDevice.EMMA),
    rn.INVERTER_TOTAL_ENERGY_YIELD: U32Register("kWh", 100, 30344, target_device=TargetDevice.EMMA),
    rn.PV_YIELD_TODAY: U32Register("kWh", 100, 30346, target_device=TargetDevice.EMMA),
    rn.TOTAL_PV_ENERGY_YIELD: U64Register("kWh", 100, 30348, target_device=TargetDevice.EMMA),
    rn.PV_OUTPUT_POWER: U32Register("W", 1, 30354, target_device=TargetDevice.EMMA),
    rn.LOAD_POWER: U32Register("W", 1, 30356, target_device=TargetDevice.EMMA),
    rn.FEED_IN_POWER: I32Register("W", 1, 30358, target_device=TargetDevice.EMMA),
    rn.BATTERY_CHARGE_DISCHARGE_POWER: I32Register("W", 1, 30360, target_device=TargetDevice.EMMA),
    rn.INVERTER_RATED_POWER: U32Register("W", 1, 30362, target_device=TargetDevice.EMMA),
    rn.INVERTER_ACTIVE_POWER: I32Register("W", 1, 30364, target_device=TargetDevice.EMMA),
    rn.STATE_OF_CAPACITY: U16Register("%", 100, 30368, target_device=TargetDevice.EMMA),
    rn.ESS_CHARGEABLE_CAPACITY: U32Register("kWh", 1000, 30369, target_device=TargetDevice.EMMA),
    rn.ESS_DISCHARGEABLE_CAPACITY: U32Register("kWh", 1000, 30371, target_device=TargetDevice.EMMA),
    rn.BACKUP_POWER_STATE_OF_CHARGE: U16Register("%", 100, 30373, target_device=TargetDevice.EMMA),
    rn.YIELD_THIS_MONTH: U32Register("kWh", 100, 30380, target_device=TargetDevice.EMMA),
    rn.MONTHLY_ENERGY_CONSUMPTION: U32Register("kWh", 100, 30382, target_device=TargetDevice.EMMA),
    rn.MONTHLY_FEED_IN_TO_GRID: U32Register("kWh", 100, 30384, target_device=TargetDevice.EMMA),
    rn.YIELD_THIS_YEAR: U32Register("kWh", 100, 30386, target_device=TargetDevice.EMMA),
    rn.ANNUAL_ENERGY_CONSUMPTION: U32Register("kWh", 100, 30388, target_device=TargetDevice.EMMA),
    rn.YEARLY_FEED_IN_TO_GRID: U32Register("kWh", 100, 30390, target_device=TargetDevice.EMMA),
    rn.MONTHLY_SUPPLY_FROM_GRID: U32Register("kWh", 100, 30394, target_device=TargetDevice.EMMA),
    rn.YEARLY_SUPPLY_FROM_GRID: U32Register("kWh", 100, 30396, target_device=TargetDevice.EMMA),
    rn.BACKUP_TIME_NOTIFICATION_THRESHOLD: U16Register("min", 1, 30406, target_device=TargetDevice.EMMA),
    rn.ENERGY_CHARGED_THIS_MONTH: U32Register("kWh", 100, 30407, target_device=TargetDevice.EMMA),
    rn.ENERGY_DISCHARGED_THIS_MONTH: U32Register("kWh", 100, 30409, target_device=TargetDevice.EMMA),
}

REGISTERS.update(EMMA_REGISTERS)


METER_REGISTERS = {
    rn.METER_STATUS: U16Register(rv.MeterStatus, 1, 37100),
    rn.GRID_A_VOLTAGE: I32Register("V", 10, 37101),
    rn.GRID_B_VOLTAGE: I32Register("V", 10, 37103),
    rn.GRID_C_VOLTAGE: I32Register("V", 10, 37105),
    rn.ACTIVE_GRID_A_CURRENT: I32Register("A", 100, 37107),
    rn.ACTIVE_GRID_B_CURRENT: I32Register("A", 100, 37109),
    rn.ACTIVE_GRID_C_CURRENT: I32Register("A", 100, 37111),
    rn.POWER_METER_ACTIVE_POWER: I32Register("W", 1, 37113),
    rn.POWER_METER_REACTIVE_POWER: I32Register("var", 1, 37115),
    rn.ACTIVE_GRID_POWER_FACTOR: I16Register(None, 1000, 37117),
    rn.ACTIVE_GRID_FREQUENCY: I16Register("Hz", 100, 37118),
    # cfr. https://github.com/wlcrs/huawei_solar/issues/54
    rn.GRID_EXPORTED_ENERGY: I32AbsoluteValueRegister("kWh", 100, 37119),
    rn.GRID_ACCUMULATED_ENERGY: I32Register("kWh", 100, 37121),
    rn.GRID_ACCUMULATED_REACTIVE_POWER: I32Register("kvarh", 100, 37123),
    rn.METER_TYPE: U16Register(rv.MeterType, 1, 37125),
    rn.ACTIVE_GRID_A_B_VOLTAGE: I32Register("V", 10, 37126),
    rn.ACTIVE_GRID_B_C_VOLTAGE: I32Register("V", 10, 37128),
    rn.ACTIVE_GRID_C_A_VOLTAGE: I32Register("V", 10, 37130),
    rn.ACTIVE_GRID_A_POWER: I32Register("W", 1, 37132),
    rn.ACTIVE_GRID_B_POWER: I32Register("W", 1, 37134),
    rn.ACTIVE_GRID_C_POWER: I32Register("W", 1, 37136),
    rn.METER_TYPE_CHECK: U16Register(rv.MeterTypeCheck, 1, 37138),
}

REGISTERS.update(METER_REGISTERS)
