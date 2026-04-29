"""Register definitions of the complex registers containing time-periods."""

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from huawei_solar.exceptions import DecodeError, EncodeError, PeakPeriodsValidationError, TimeOfUsePeriodsException

from .base import RegisterDefinition, Result


@dataclass(frozen=True, slots=True)
class LG_RESU_TimeOfUsePeriod:
    """Time of use period of LG RESU."""

    start_time: int  # minutes since midnight
    end_time: int  # minutes since midnight
    electricity_price: float


class ChargeFlag(IntEnum):
    """Charge Flag."""

    CHARGE = 0
    DISCHARGE = 1


@dataclass(frozen=True, slots=True)
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

    format = f"H{'HHI' * LG_RESU_TOU_PERIODS}"
    format_size = 1 + 3 * LG_RESU_TOU_PERIODS
    length = 41

    def decode(self, values: tuple[Any, ...]) -> Result[list[LG_RESU_TimeOfUsePeriod]]:
        """Decode time of use register."""
        number_of_periods = values[0]
        if number_of_periods > LG_RESU_TOU_PERIODS:
            msg = f"Device reported {number_of_periods} TOU periods, but the maximum is {LG_RESU_TOU_PERIODS}"
            raise DecodeError(msg)

        def _decode_lg_resu_tou_period(
            start_time: int,
            end_time: int,
            electricity_price: int,
        ) -> LG_RESU_TimeOfUsePeriod:
            return LG_RESU_TimeOfUsePeriod(
                start_time,
                end_time,
                electricity_price / 1000,
            )

        return Result(
            value=[
                _decode_lg_resu_tou_period(*values[1 + idx * 3 : 1 + ((idx + 1) * 3)])
                for idx in range(number_of_periods)
            ],
            unit=None,
        )

    def _validate(
        self,
        data: list[LG_RESU_TimeOfUsePeriod],
    ) -> None:
        """Validate data type."""
        if len(data) == 0:
            return  # nothing to check

        # Sanity check of each period individually
        for tou_period in data:
            if tou_period.start_time < 0 or tou_period.end_time < 0:
                msg = "TOU period is invalid (Below zero)"
                raise TimeOfUsePeriodsException(msg)
            if tou_period.start_time > 24 * 60 or tou_period.end_time > 24 * 60:
                msg = "TOU period is invalid (Spans over more than one day)"
                raise TimeOfUsePeriodsException(
                    msg,
                )
            if tou_period.start_time >= tou_period.end_time:
                msg = "TOU period is invalid (start-time is greater than end-time)"
                raise TimeOfUsePeriodsException(
                    msg,
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
                msg = "TOU periods are overlapping"
                raise TimeOfUsePeriodsException(msg)

    def encode(self, data: list[LG_RESU_TimeOfUsePeriod]) -> tuple[Any, ...]:
        """Encode Time Of Use Period registers."""
        self._validate(data)

        values = [len(data)]

        for period in data:
            values.extend(
                [
                    period.start_time,
                    period.end_time,
                    int(period.electricity_price * 1000),
                ],
            )

        values.extend([0, 0, 0] * (LG_RESU_TOU_PERIODS - len(data)))

        return tuple(values)


HUAWEI_LUNA2000_TOU_PERIODS = 14


class HUAWEI_LUNA2000_TimeOfUseRegisters(RegisterDefinition[list[HUAWEI_LUNA2000_TimeOfUsePeriod]]):
    """Time of use register."""

    format = f"H{'HHBB' * HUAWEI_LUNA2000_TOU_PERIODS}"
    format_size = 1 + 4 * HUAWEI_LUNA2000_TOU_PERIODS
    length = 43

    def decode(self, values: tuple[Any, ...]) -> Result[list[HUAWEI_LUNA2000_TimeOfUsePeriod]]:
        """Decode time of use register."""
        number_of_periods = values[0]
        if number_of_periods > HUAWEI_LUNA2000_TOU_PERIODS:
            msg = f"Device reported {number_of_periods} TOU periods, but the maximum is {HUAWEI_LUNA2000_TOU_PERIODS}"
            raise DecodeError(msg)

        def _decode_huawei_luna2000_tou_period(
            start_time: int,
            end_time: int,
            charge: int,
            days_effective: int,
        ) -> HUAWEI_LUNA2000_TimeOfUsePeriod:
            return HUAWEI_LUNA2000_TimeOfUsePeriod(
                start_time,
                end_time,
                ChargeFlag(charge),
                _days_effective_parser(days_effective),
            )

        return Result(
            [
                _decode_huawei_luna2000_tou_period(*values[1 + idx * 4 : 1 + ((idx + 1) * 4)])
                for idx in range(number_of_periods)
            ],
            unit=None,
        )

    def _validate(
        self,
        data: list[HUAWEI_LUNA2000_TimeOfUsePeriod],
    ) -> None:
        """Validate data type."""
        if len(data) == 0:
            return  # nothing to check

        # Sanity check of each period individually
        for tou_period in data:
            if not isinstance(tou_period, HUAWEI_LUNA2000_TimeOfUsePeriod):
                msg = "TOU period is of an unexpected type"
                raise TimeOfUsePeriodsException(msg)
            if tou_period.start_time < 0 or tou_period.end_time < 0:
                msg = "TOU period is invalid (Below zero)"
                raise TimeOfUsePeriodsException(msg)
            if tou_period.start_time > 24 * 60 or tou_period.end_time > 24 * 60:
                msg = "TOU period is invalid (Spans over more than one day)"
                raise TimeOfUsePeriodsException(
                    msg,
                )
            if tou_period.start_time >= tou_period.end_time:
                msg = "TOU period is invalid (start-time is greater than end-time)"
                raise TimeOfUsePeriodsException(
                    msg,
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
                    msg = "TOU periods are overlapping"
                    raise TimeOfUsePeriodsException(msg)

    def encode(
        self,
        data: list[HUAWEI_LUNA2000_TimeOfUsePeriod],
    ) -> tuple[Any, ...]:
        """Encode Time Of Use Period registers."""
        self._validate(data)

        if len(data) > HUAWEI_LUNA2000_TOU_PERIODS:
            msg = f"Too many TOU periods: got {len(data)}, maximum is {HUAWEI_LUNA2000_TOU_PERIODS}"
            raise TimeOfUsePeriodsException(msg)

        values = [len(data)]

        def _days_effective_builder(days_tuple: tuple[bool, bool, bool, bool, bool, bool, bool]) -> int:
            result = 0
            mask = 0x1
            for i in range(7):
                if days_tuple[i]:
                    result += mask
                mask = mask << 1

            return result

        for period in data:
            values.extend(
                [
                    period.start_time,
                    period.end_time,
                    int(period.charge_flag),
                    _days_effective_builder(period.days_effective),
                ],
            )

        values.extend([0, 0, 0, 0] * (HUAWEI_LUNA2000_TOU_PERIODS - len(data)))

        return tuple(values)


@dataclass(frozen=True, slots=True)
class ChargeDischargePeriod:
    """Charge or Discharge Period."""

    start_time: int  # minutes since midnight
    end_time: int  # minutes since midnight
    power: int  # power in watts


CHARGE_DISCHARGE_PERIODS = 10


class ChargeDischargePeriodRegisters(RegisterDefinition[list[ChargeDischargePeriod]]):
    """Charge or discharge period registers."""

    format = f"H{'HHI' * CHARGE_DISCHARGE_PERIODS}"
    format_size = 1 + 3 * CHARGE_DISCHARGE_PERIODS
    length = 41

    def decode(self, values: tuple[Any, ...]) -> Result[list[ChargeDischargePeriod]]:
        """Decode ChargeDischargePeriodRegisters."""
        number_of_periods = values[0]
        if number_of_periods > CHARGE_DISCHARGE_PERIODS:
            msg = (
                f"Device reported {number_of_periods} charge/discharge periods, "
                f"but the maximum is {CHARGE_DISCHARGE_PERIODS}"
            )
            raise DecodeError(msg)

        def _decode_charge_discharge_period(start_time: int, end_time: int, power: int) -> ChargeDischargePeriod:
            return ChargeDischargePeriod(start_time, end_time, power)

        periods = [
            _decode_charge_discharge_period(*values[1 + idx * 3 : 1 + ((idx + 1) * 3)])
            for idx in range(number_of_periods)
        ]

        return Result(periods[:number_of_periods], unit=None)

    def encode(self, data: list[ChargeDischargePeriod]) -> tuple[Any, ...]:
        """Encode ChargeDischargePeriodRegisters."""
        if len(data) > CHARGE_DISCHARGE_PERIODS:
            msg = f"Too many charge/discharge periods: got {len(data)}, maximum is {CHARGE_DISCHARGE_PERIODS}"
            raise EncodeError(msg)

        values = [len(data)]

        for period in data:
            values.extend(
                [
                    period.start_time,
                    period.end_time,
                    period.power,
                ],
            )

        # pad with empty periods
        values.extend([0, 0, 0] * (CHARGE_DISCHARGE_PERIODS - len(data)))

        return tuple(values)


@dataclass(frozen=True, slots=True)
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


def _days_effective_builder(days_tuple: tuple[bool, bool, bool, bool, bool, bool, bool]) -> int:
    result = 0
    mask = 0x1
    for i in range(7):
        if days_tuple[i]:
            result += mask
        mask = mask << 1

    return result


def _days_effective_parser(value: int) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
    result = []
    mask = 0x1
    for _ in range(7):
        result.append((value & mask) != 0)
        mask = mask << 1

    return tuple(result)  # type: ignore[return-value]


class PeakSettingPeriodRegisters(RegisterDefinition[list[PeakSettingPeriod]]):
    """Peak Setting Period registers."""

    format = f"H{'HHIB' * PEAK_SETTING_PERIODS}"
    format_size = 1 + 4 * PEAK_SETTING_PERIODS
    length = 64

    def decode(self, values: tuple[Any, ...]) -> Result[list[PeakSettingPeriod]]:
        """Decode PeakSettingPeriodRegisters."""
        number_of_periods = values[0]

        # Safety check
        number_of_periods = min(number_of_periods, PEAK_SETTING_PERIODS)

        periods = []
        for idx in range(number_of_periods):
            start_time, end_time, peak_value, week_value = values[1 + (idx * 4) : 1 + ((idx + 1) * 4)]

            if start_time != end_time and week_value != 0:
                periods.append(
                    PeakSettingPeriod(
                        start_time,
                        end_time,
                        peak_value,
                        _days_effective_parser(week_value),
                    ),
                )

        return Result(periods[:number_of_periods], unit=None)

    def _validate(self, data: list[PeakSettingPeriod]) -> None:
        for day_idx in range(7):
            # find all ranges that are valid for the given day
            active_periods: list[PeakSettingPeriod] = list(
                filter(lambda period: period.days_effective[day_idx], data),
            )

            if not active_periods:
                msg = "All days of the week need to be covered"
                raise PeakPeriodsValidationError(
                    msg,
                )

            # require full day to be covered
            active_periods.sort(key=lambda a: a.start_time)

            if active_periods[0].start_time != 0:
                msg = "Every day must be covered from 00:00"
                raise PeakPeriodsValidationError(msg)

            for period_idx in range(1, len(active_periods)):
                current_period = active_periods[period_idx]
                prev_period = active_periods[period_idx - 1]
                if current_period.start_time not in (
                    prev_period.end_time,
                    prev_period.end_time + 1,
                ):
                    msg = "All moments of each day need to be covered"
                    raise PeakPeriodsValidationError(
                        msg,
                    )

            if active_periods[-1].end_time not in ((24 * 60) - 1, 24 * 60):
                msg = "Every day must be covered until 23:59"
                raise PeakPeriodsValidationError(
                    msg,
                )

    def encode(self, data: list[PeakSettingPeriod]) -> tuple[Any, ...]:
        """Encode PeakSettingPeriodRegisters."""
        if len(data) > PEAK_SETTING_PERIODS:
            data = data[:PEAK_SETTING_PERIODS]

        values = [len(data)]

        for period in data:
            values.extend(
                [
                    period.start_time,
                    period.end_time,
                    period.power,
                    _days_effective_builder(period.days_effective),
                ],
            )

        # pad with empty periods
        values.extend([0, 0, 0, 0] * (PEAK_SETTING_PERIODS - len(data)))

        return tuple(values)
