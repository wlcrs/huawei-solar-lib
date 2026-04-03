"""Tests for device detection in huawei_solar.device.__init__."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from huawei_solar.device.emma import EMMADevice
from huawei_solar.device.scharger import SChargerDevice
from huawei_solar.device.sdongle import SDongleDevice
from huawei_solar.device.smartlogger import SmartLoggerDevice
from huawei_solar.device.sun2000 import SUN2000Device
from huawei_solar.exceptions import DeviceDetectionError
from tmodbus.const import FunctionCode
from tmodbus.exceptions import IllegalDataAddressError

from huawei_solar import register_names as rn
from huawei_solar.device import DEFAULT_SDONGLE_UNIT_ID, detect_device_type, get_device_class_for_model


def _value_result(value: str) -> SimpleNamespace:
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


@pytest.mark.parametrize(
    ("model_name", "expected_class"),
    [
        ("sun2000-model", SUN2000Device),
        ("emma-model", EMMADevice),
        ("scharger-model", SChargerDevice),
        ("sdongle-model", SDongleDevice),
        ("smartlogger-model", SmartLoggerDevice),
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
            raise IllegalDataAddressError(
                error_code=IllegalDataAddressError.error_code,
                function_code=FunctionCode.READ_HOLDING_REGISTERS,
            )
        if register == rn.SMARTLOGGER_DEVICE_NAME:
            return _value_result("smartlogger-model")
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=1, side_effect=side_effect)

    detected_class, detected_name = await detect_device_type(client)

    assert detected_class is SmartLoggerDevice
    assert detected_name == "smartlogger-model"


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


async def test_detect_device_type_sdongle_fallback_when_other_registers_illegal() -> None:
    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register in (rn.MODEL_NAME, rn.SMARTLOGGER_DEVICE_NAME):
            raise IllegalDataAddressError(
                error_code=IllegalDataAddressError.error_code,
                function_code=FunctionCode.READ_HOLDING_REGISTERS,
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
        if register in (rn.MODEL_NAME, rn.SMARTLOGGER_DEVICE_NAME, rn.SDONGLE_DEVICE_SEARCH_STATUS):
            raise IllegalDataAddressError(
                error_code=IllegalDataAddressError.error_code,
                function_code=FunctionCode.READ_HOLDING_REGISTERS,
            )
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=1, side_effect=side_effect)

    with pytest.raises(DeviceDetectionError, match="Unable to detect the device type"):
        await detect_device_type(client)
