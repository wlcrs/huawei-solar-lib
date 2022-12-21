from unittest.mock import MagicMock

import pytest

from huawei_solar.exceptions import TimeOfUsePeriodsException
import huawei_solar.register_names as rn
from huawei_solar.registers import REGISTERS, HUAWEI_LUNA2000_TimeOfUsePeriod, LG_RESU_TimeOfUsePeriod

ppr = REGISTERS[rn.STORAGE_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS]


def test__validate__tou_periods__HUAWEI_LUNA2000__too_long_span__start_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=60 * 24 + 1, end_time=15, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(
        expected_exception=TimeOfUsePeriodsException, match=r"TOU period is invalid \(Spans over more than one day\)"
    ):
        ppr._validate([tou])


def test__validate__tou_periods__HUAWEI_LUNA2000__too_long_span__end_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=15, end_time=60 * 24 + 1, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(
        expected_exception=TimeOfUsePeriodsException, match=r"TOU period is invalid \(Spans over more than one day\)"
    ):
        ppr._validate([tou])


def test__validate__tou_periods__HUAWEI_LUNA2000__negative__start_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=-10, end_time=15, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(expected_exception=TimeOfUsePeriodsException, match=r"TOU period is invalid \(Below zero\)"):
        ppr._validate([tou])


def test__validate__tou_periods__HUAWEI_LUNA2000__negative__end_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=15, end_time=-2, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(expected_exception=TimeOfUsePeriodsException, match=r"TOU period is invalid \(Below zero\)"):
        ppr._validate([tou])


def test__validate__tou_periods__HUAWEI_LUNA2000__start_time_bigger_than_end_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=15, end_time=2, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(
        expected_exception=TimeOfUsePeriodsException,
        match=r"TOU period is invalid \(start-time is greater than end-time\)",
    ):
        ppr._validate([tou])


def test__validate__tou_periods__HUAWEI_LUNA2000__overlapping__1():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=120, end_time=160, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=100, end_time=150, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
    ]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException, match="TOU periods are overlapping"):
        ppr._validate(tou)


def test__validate__tou_periods__HUAWEI_LUNA2000__overlapping__2():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=15, end_time=120, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=100, end_time=150, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
    ]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException, match="TOU periods are overlapping"):
        ppr._validate(tou)


def test__validate__tou_periods__HUAWEI_LUNA2000__OK():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=15, end_time=120, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=121, end_time=150, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
    ]
    ppr._validate(tou)


def test__validate__tou_periods__HUAWEI_LUNA2000__OK_2():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=15, end_time=120, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=0, end_time=14, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
    ]
    ppr._validate(tou)


def test__validate__tou_periods__HUAWEI_LUNA2000__OK__different_days():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=0, end_time=120, charge_flag=0, days_effective=[False, False, False, True, True, False, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=0, end_time=120, charge_flag=0, days_effective=[True, False, True, False, False, True, False]
        ),
    ]

    ppr._validate(tou)


def test__validate__tou_periodsG__RESU___OK():
    tou = [
        LG_RESU_TimeOfUsePeriod(start_time=5, end_time=15, electricity_price=1),
        LG_RESU_TimeOfUsePeriod(start_time=16, end_time=20, electricity_price=1),
    ]
    ppr._validate(tou)


def test__validate__tou_periodsG__RESU___overlaping():
    tou = [
        LG_RESU_TimeOfUsePeriod(start_time=5, end_time=15, electricity_price=1),
        LG_RESU_TimeOfUsePeriod(start_time=5, end_time=15, electricity_price=1),
    ]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException, match="TOU periods are overlapping"):
        ppr._validate(tou)


def test__validate__tou_periods__unknown_type():
    mock = MagicMock()
    mock.start_time = 10
    mock.end_time = 20
    tou = [mock]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException, match="TOU period is of an unexpected type"):
        ppr._validate(tou)


def test__validate__tou_periods__different_types():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=0, end_time=120, charge_flag=0, days_effective=[False, False, False, True, True, False, True]
        ),
        LG_RESU_TimeOfUsePeriod(start_time=16, end_time=20, electricity_price=1),
    ]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException, match="TOU periods cannot be of different types"):
        ppr._validate(tou)


def test__validate__data_type__none():
    ppr._validate([])
