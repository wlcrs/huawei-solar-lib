import pytest

from huawei_solar.exceptions import PeakPeriodsValidationError
import huawei_solar.register_names as rn
from huawei_solar.registers import REGISTERS, PeakSettingPeriod

ppr = REGISTERS[rn.STORAGE_CAPACITY_CONTROL_PERIODS]


def test_simple():

    pp_valid = [
        PeakSettingPeriod(
            start_time=0, end_time=1440, power=2.5, days_effective=[True, True, True, True, True, True, True]
        )
    ]

    assert ppr._validate(pp_valid) is None


def test_invalid_start_time():
    pp = [
        PeakSettingPeriod(
            start_time=60 * 24 + 1, end_time=15, power=2.5, days_effective=[True, True, True, True, True, True, True]
        )
    ]

    with pytest.raises(expected_exception=PeakPeriodsValidationError, match="Every day must be covered from 00:00"):
        ppr._validate(pp)


def test_invalid_end_time():
    pp = [
        PeakSettingPeriod(
            start_time=0, end_time=15, power=2.5, days_effective=[True, True, True, True, True, True, True]
        )
    ]

    with pytest.raises(expected_exception=PeakPeriodsValidationError, match="Every day must be covered until 23:59"):
        ppr._validate(pp)

    pp2 = [
        PeakSettingPeriod(
            start_time=0, end_time=1441, power=2.5, days_effective=[True, True, True, True, True, True, True]
        )
    ]

    with pytest.raises(expected_exception=PeakPeriodsValidationError, match="Every day must be covered until 23:59"):
        ppr._validate(pp2)


def test_all_days_of_week_covered():
    pp = [
        PeakSettingPeriod(
            start_time=0, end_time=15, power=2.5, days_effective=[False, True, True, True, True, True, True]
        )
    ]

    with pytest.raises(expected_exception=PeakPeriodsValidationError, match="All days of the week need to be covered"):
        ppr._validate(pp)


def test_multiple_periods_on_a_day():
    pp = [
        PeakSettingPeriod(
            start_time=0, end_time=1439, power=2.5, days_effective=[False, True, True, True, True, True, True]
        ),
        PeakSettingPeriod(
            start_time=0, end_time=600, power=2.5, days_effective=[True, False, False, False, False, False, False]
        ),
        PeakSettingPeriod(
            start_time=600, end_time=1439, power=2.5, days_effective=[True, False, False, False, False, False, False]
        ),
    ]

    assert ppr._validate(pp) is None

    pp2 = [
        PeakSettingPeriod(
            start_time=0, end_time=1439, power=2.5, days_effective=[False, True, True, True, True, True, True]
        ),
        PeakSettingPeriod(
            start_time=0, end_time=600, power=2.5, days_effective=[True, False, False, False, False, False, False]
        ),
        PeakSettingPeriod(
            start_time=601, end_time=1439, power=2.5, days_effective=[True, False, False, False, False, False, False]
        ),
    ]

    assert ppr._validate(pp2) is None

    pp3 = [
        PeakSettingPeriod(
            start_time=0, end_time=1439, power=2.5, days_effective=[False, True, True, True, True, True, True]
        ),
        PeakSettingPeriod(
            start_time=0, end_time=600, power=2.5, days_effective=[True, False, False, False, False, False, False]
        ),
        PeakSettingPeriod(
            start_time=602, end_time=1439, power=2.5, days_effective=[True, False, False, False, False, False, False]
        ),
    ]

    with pytest.raises(
        expected_exception=PeakPeriodsValidationError, match="All moments of each day need to be covered"
    ):
        ppr._validate(pp3)
