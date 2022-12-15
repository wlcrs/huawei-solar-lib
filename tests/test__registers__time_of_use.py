from unittest.mock import MagicMock

import pytest

from huawei_solar.exceptions import TimeOfUsePeriodsException
from huawei_solar.registers import HUAWEI_LUNA2000_TimeOfUsePeriod, LG_RESU_TimeOfUsePeriod, TimeOfUsePeriodsValidator


def test__validate__tou_periods__HUAWEI_LUNA2000__too_long_span__start_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=60 * 24 + 1, end_time=15, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=[tou]).validate()
    assert err.value.args[0] == "TOU period is invalid (Spans over more than one day)"


def test__validate__tou_periods__HUAWEI_LUNA2000__too_long_span__end_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=15, end_time=60 * 24 + 1, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=[tou]).validate()
    assert err.value.args[0] == "TOU period is invalid (Spans over more than one day)"


def test__validate__tou_periods__HUAWEI_LUNA2000__negative__start_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=-10, end_time=15, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=[tou]).validate()
    assert err.value.args[0] == "TOU period is invalid (Below zero)"


def test__validate__tou_periods__HUAWEI_LUNA2000__negative__end_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=15, end_time=-2, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=[tou]).validate()
    assert err.value.args[0] == "TOU period is invalid (Below zero)"


def test__validate__tou_periods__HUAWEI_LUNA2000__start_time_bigger_than_end_time():
    tou = HUAWEI_LUNA2000_TimeOfUsePeriod(
        start_time=15, end_time=2, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
    )
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=[tou]).validate()
    assert err.value.args[0] == "TOU period is invalid (start-time is greater than end-time)"


def test__validate__tou_periods__HUAWEI_LUNA2000__overlapping__1():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=120, end_time=160, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=100, end_time=150, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
    ]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=tou).validate()
    assert err.value.args[0] == "TOU periods are overlapping"


def test__validate__tou_periods__HUAWEI_LUNA2000__overlapping__2():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=15, end_time=120, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=100, end_time=150, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
    ]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=tou).validate()
    assert err.value.args[0] == "TOU periods are overlapping"


def test__validate__tou_periods__HUAWEI_LUNA2000__OK():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=15, end_time=120, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=121, end_time=150, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
    ]
    TimeOfUsePeriodsValidator(tou_periods=tou).validate()


def test__validate__tou_periods__HUAWEI_LUNA2000__OK_2():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=15, end_time=120, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=0, end_time=14, charge_flag=0, days_effective=[True, True, True, True, True, True, True]
        ),
    ]
    TimeOfUsePeriodsValidator(tou_periods=tou).validate()


def test__validate__tou_periods__HUAWEI_LUNA2000__OK__different_days():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=0, end_time=120, charge_flag=0, days_effective=[False, False, False, True, True, False, True]
        ),
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=0, end_time=120, charge_flag=0, days_effective=[True, False, True, False, False, True, False]
        ),
    ]
    validator = TimeOfUsePeriodsValidator(tou_periods=tou)
    validator.validate()
    assert validator.data_type is HUAWEI_LUNA2000_TimeOfUsePeriod


def test__validate__tou_periodsG__RESU___OK():
    tou = [
        LG_RESU_TimeOfUsePeriod(start_time=5, end_time=15, electricity_price=1),
        LG_RESU_TimeOfUsePeriod(start_time=16, end_time=20, electricity_price=1),
    ]
    validator = TimeOfUsePeriodsValidator(tou_periods=tou)
    validator.validate()
    assert validator.data_type is LG_RESU_TimeOfUsePeriod


def test__validate__tou_periodsG__RESU___overlaping():
    tou = [
        LG_RESU_TimeOfUsePeriod(start_time=5, end_time=15, electricity_price=1),
        LG_RESU_TimeOfUsePeriod(start_time=5, end_time=15, electricity_price=1),
    ]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=tou).validate()
    assert err.value.args[0] == "TOU periods are overlapping"


def test__validate__tou_periods__unknown_type():
    mock = MagicMock()
    mock.start_time = 10
    mock.end_time = 20
    tou = [mock]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=tou).validate()
    assert err.value.args[0] == "TOU period is of an unexpected type"


def test__validate__tou_periods__different_types():
    tou = [
        HUAWEI_LUNA2000_TimeOfUsePeriod(
            start_time=0, end_time=120, charge_flag=0, days_effective=[False, False, False, True, True, False, True]
        ),
        LG_RESU_TimeOfUsePeriod(start_time=16, end_time=20, electricity_price=1),
    ]
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=tou).validate()
    assert err.value.args[0] == "TOU periods cannot be of different types"


def test__validate__data_type__none():
    with pytest.raises(expected_exception=TimeOfUsePeriodsException) as err:
        TimeOfUsePeriodsValidator(tou_periods=None).data_type
    assert err.value.args[0] == "Execute validate function to be able to read the TOU data type"
