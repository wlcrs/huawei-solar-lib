"""Tests for device detection in huawei_solar.device.__init__."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from huawei_solar.device.emma import EMMADevice
from huawei_solar.device.meter import MeterDevice
from huawei_solar.device.scharger import SChargerDevice
from huawei_solar.device.sdongle import SDongleDevice
from huawei_solar.device.smartlogger import SmartLoggerDevice
from huawei_solar.device.sun2000 import SUN2000Device
from huawei_solar.exceptions import DeviceDetectionError, ReadException
from tmodbus.exceptions import IllegalDataAddressError

from huawei_solar import register_names as rn
from huawei_solar.device import DEFAULT_SDONGLE_UNIT_ID, detect_device_type, get_device_class_for_model

_READ_FAILED_MSG = "Failed to read register"


def _value_result(value: str | float) -> SimpleNamespace:
    return SimpleNamespace(value=value)


def _client_with_get(unit_id: int, side_effect: Any) -> Mock:  # noqa: ANN401
    client = Mock()
    client.unit_id = unit_id
    client.get = AsyncMock(side_effect=side_effect)
    return client


@pytest.fixture
def patched_supports_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SUN2000Device, "supports_device", staticmethod(lambda model: model == "sun2000-model"))
    monkeypatch.setattr(EMMADevice, "supports_device", staticmethod(lambda model: model == "emma-model"))
    monkeypatch.setattr(SChargerDevice, "supports_device", staticmethod(lambda model: model == "scharger-model"))
    monkeypatch.setattr(SDongleDevice, "supports_device", staticmethod(lambda model: model == "sdongle-model"))
    monkeypatch.setattr(
        SmartLoggerDevice,
        "supports_device",
        staticmethod(lambda model: model == "smartlogger-model"),
    )
    monkeypatch.setattr(MeterDevice, "supports_device", staticmethod(lambda model: model == "meter-model"))


@pytest.mark.parametrize(
    ("model_name", "expected_class"),
    [
        ("sun2000-model", SUN2000Device),
        ("emma-model", EMMADevice),
        ("scharger-model", SChargerDevice),
        ("sdongle-model", SDongleDevice),
        ("smartlogger-model", SmartLoggerDevice),
        ("meter-model", MeterDevice),
    ],
)
def test_get_device_class_for_model_all_supported_types(
    patched_supports_device: None,
    model_name: str,
    expected_class: type,
) -> None:
    assert get_device_class_for_model(model_name) is expected_class


def test_get_device_class_for_model_unknown_defaults_to_sun2000(patched_supports_device: None) -> None:
    assert get_device_class_for_model("unknown-model") is SUN2000Device


@pytest.mark.parametrize(
    ("model_name", "expected_class"),
    [
        ("sun2000-model", SUN2000Device),
        ("emma-model", EMMADevice),
        ("scharger-model", SChargerDevice),
    ],
)
async def test_detect_device_type_from_model_name(
    patched_supports_device: None,
    model_name: str,
    expected_class: type,
) -> None:
    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register == rn.MODEL_NAME:
            return _value_result(model_name)
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=1, side_effect=side_effect)

    detected_class, detected_name = await detect_device_type(client)

    assert detected_class is expected_class
    assert detected_name == model_name


async def test_detect_device_type_smartlogger_when_model_name_illegal(
    patched_supports_device: None,
) -> None:
    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register == rn.MODEL_NAME:
            raise ReadException(_READ_FAILED_MSG, modbus_exception_code=IllegalDataAddressError.error_code)
        if register == rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN:
            return _value_result("123456789012")
        if register == rn.SMARTLOGGER_DEVICE_NAME:
            return _value_result("smartlogger-model")
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=1, side_effect=side_effect)

    detected_class, detected_name = await detect_device_type(client)

    assert detected_class is SmartLoggerDevice
    assert detected_name == "smartlogger-model"


@pytest.mark.parametrize("modbus_exception_code", [0x02, 0x03])
async def test_detect_device_type_smartlogger_when_model_name_read_exception(
    patched_supports_device: None,
    modbus_exception_code: int,
) -> None:
    """register_client.get() wraps modbus exceptions in ReadException — the fallback chain must follow."""

    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register == rn.MODEL_NAME:
            raise ReadException(_READ_FAILED_MSG, modbus_exception_code=modbus_exception_code)
        if register == rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN:
            return _value_result("123456789012")
        if register == rn.SMARTLOGGER_DEVICE_NAME:
            return _value_result("smartlogger-model")
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=1, side_effect=side_effect)

    detected_class, detected_name = await detect_device_type(client)

    assert detected_class is SmartLoggerDevice
    assert detected_name == "smartlogger-model"


async def test_detect_device_type_propagates_unrelated_read_exception(
    patched_supports_device: None,
) -> None:
    """Modbus exception codes other than 0x02/0x03 must propagate, not be swallowed."""

    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register == rn.MODEL_NAME:
            raise ReadException(_READ_FAILED_MSG, modbus_exception_code=0x04)  # Server Device Failure
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=1, side_effect=side_effect)

    with pytest.raises(ReadException):
        await detect_device_type(client)


async def test_detect_device_type_sdongle_fast_track_on_unit_100() -> None:
    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register == rn.SDONGLE_DEVICE_SEARCH_STATUS:
            return _value_result("done")
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=DEFAULT_SDONGLE_UNIT_ID, side_effect=side_effect)

    detected_class, detected_name = await detect_device_type(client)

    assert detected_class is SDongleDevice
    assert detected_name == "SDongle"


async def test_detect_device_type_smartlogger_via_esn_fallback() -> None:
    """Firmwares with neither MODEL_NAME nor SMARTLOGGER_DEVICE_NAME still expose the ESN."""

    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register in (rn.MODEL_NAME, rn.SMARTLOGGER_DEVICE_NAME):
            raise ReadException(_READ_FAILED_MSG, modbus_exception_code=0x03)
        if register == rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN:
            return _value_result("102120056473")
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=7, side_effect=side_effect)

    detected_class, detected_name = await detect_device_type(client)

    assert detected_class is SmartLoggerDevice
    assert detected_name == "SmartLogger"


async def test_detect_device_type_meter_via_active_power_probe() -> None:
    """Power meters expose neither MODEL_NAME nor SMARTLOGGER_DEVICE_NAME, but answer 32278."""

    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register in (
            rn.MODEL_NAME,
            rn.SMARTLOGGER_DEVICE_NAME,
            rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN,
        ):
            raise ReadException(_READ_FAILED_MSG, modbus_exception_code=0x03)
        if register == rn.SMARTLOGGER_EXTERNAL_METER_ACTIVE_POWER:
            return _value_result(-1.394)
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=11, side_effect=side_effect)

    detected_class, detected_name = await detect_device_type(client)

    assert detected_class is MeterDevice
    assert detected_name == "PowerMeter"


async def test_detect_device_type_sdongle_fallback_when_other_registers_illegal() -> None:
    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register in (
            rn.MODEL_NAME,
            rn.SMARTLOGGER_DEVICE_NAME,
            rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN,
            rn.SMARTLOGGER_EXTERNAL_METER_ACTIVE_POWER,
        ):
            raise ReadException(
                _READ_FAILED_MSG,
                modbus_exception_code=IllegalDataAddressError.error_code,
            )
        if register == rn.SDONGLE_DEVICE_SEARCH_STATUS:
            return _value_result("done")
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=1, side_effect=side_effect)

    detected_class, detected_name = await detect_device_type(client)

    assert detected_class is SDongleDevice
    assert detected_name == "SDongle"


async def test_detect_device_type_raises_when_no_detection_path_matches() -> None:
    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register in (
            rn.MODEL_NAME,
            rn.SMARTLOGGER_DEVICE_NAME,
            rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN,
            rn.SMARTLOGGER_EXTERNAL_METER_ACTIVE_POWER,
            rn.SDONGLE_DEVICE_SEARCH_STATUS,
        ):
            raise ReadException(
                _READ_FAILED_MSG,
                modbus_exception_code=IllegalDataAddressError.error_code,
            )
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=1, side_effect=side_effect)

    with pytest.raises(DeviceDetectionError, match="Unable to detect the device type"):
        await detect_device_type(client)
