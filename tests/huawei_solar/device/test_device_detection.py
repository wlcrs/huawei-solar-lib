"""Tests for device detection in huawei_solar.device.__init__."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from huawei_solar.device.emma import EMMADevice
from huawei_solar.device.meter import MeterDevice
from huawei_solar.device.scharger import SChargerDevice
from huawei_solar.device.sdongle import SDongleDevice
from huawei_solar.device.smart_ac_gun import SmartAcGunDevice
from huawei_solar.device.smartguard import SmartGuardDevice
from huawei_solar.device.smartlogger import SmartLoggerDevice
from huawei_solar.device.sun2000 import SUN2000Device
from huawei_solar.exceptions import DeviceDetectionError, ReadException
from tmodbus.exceptions import IllegalDataAddressError

from huawei_solar import register_names as rn
from huawei_solar.device import (
    DEFAULT_SDONGLE_UNIT_ID,
    create_sub_device_instance,
    detect_device_type,
    get_device_class_for_model,
)
from huawei_solar.register_definitions import Result

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
    monkeypatch.setattr(SmartLoggerDevice, "supports_device", staticmethod(lambda model: model == "smartlogger-model"))
    monkeypatch.setattr(MeterDevice, "supports_device", staticmethod(lambda model: model == "meter-model"))
    monkeypatch.setattr(SmartAcGunDevice, "supports_device", staticmethod(lambda model: model == "smartacgun-model"))
    monkeypatch.setattr(SmartGuardDevice, "supports_device", staticmethod(lambda model: model == "smartguard-model"))


@pytest.mark.parametrize(
    ("model_name", "expected_class"),
    [
        ("sun2000-model", SUN2000Device),
        ("emma-model", EMMADevice),
        ("scharger-model", SChargerDevice),
        ("sdongle-model", SDongleDevice),
        ("smartlogger-model", SmartLoggerDevice),
        ("meter-model", MeterDevice),
        ("smartacgun-model", SmartAcGunDevice),
        ("smartguard-model", SmartGuardDevice),
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
            rn.CHARGER_GUN_WORK_STATUS,
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


async def test_detect_device_type_smart_ac_gun_via_probe() -> None:
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
        if register == rn.CHARGER_GUN_WORK_STATUS:
            return _value_result(1)
        msg = f"Unexpected register read: {register!r}"
        raise AssertionError(msg)

    client = _client_with_get(unit_id=7, side_effect=side_effect)

    detected_class, detected_name = await detect_device_type(client)

    assert detected_class is SmartAcGunDevice
    assert detected_name == "SmartAcGun"


async def test_detect_device_type_raises_when_no_detection_path_matches() -> None:
    def side_effect(register: str) -> Any:  # noqa: ANN401
        if register in (
            rn.MODEL_NAME,
            rn.SMARTLOGGER_DEVICE_NAME,
            rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN,
            rn.SMARTLOGGER_EXTERNAL_METER_ACTIVE_POWER,
            rn.CHARGER_GUN_WORK_STATUS,
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


@pytest.mark.parametrize(
    ("model_name", "expected_class"),
    [
        ("DTSU666_H", MeterDevice),
        ("DDSU666-H", MeterDevice),
        ("PowerMeter", MeterDevice),
        ("SmartGuard-63A-T0", SmartGuardDevice),
        ("SmartGuard-63A-S0", SmartGuardDevice),
        ("FusionCharge-22KT-S0", SChargerDevice),
        ("SmartAcGun", SmartAcGunDevice),
    ],
)
def test_real_model_names_map_to_expected_classes(model_name: str, expected_class: type) -> None:
    """Test that real device models encountered in the wild map to the correct device classes."""
    assert get_device_class_for_model(model_name) is expected_class


async def test_create_sub_device_instance_same_unit_id_raises() -> None:
    """create_sub_device_instance raises ValueError when unit_id matches primary_device unit_id."""
    primary_client = Mock()
    primary_client.unit_id = 1
    primary_device = Mock(spec=SUN2000Device)
    primary_device.client = primary_client

    with pytest.raises(ValueError, match="The unit_id for the sub-device must be different"):
        await create_sub_device_instance(primary_device, 1)


async def test_create_sub_device_instance_holds_lock_during_detection_and_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """primary_device.update_lock must be held during detect_device_type and device.create."""
    primary_client = Mock()
    primary_client.unit_id = 1
    sub_client = Mock()
    sub_client.unit_id = 2
    primary_client.for_unit_id = Mock(return_value=sub_client)

    primary_device = Mock(spec=SUN2000Device)
    primary_device.client = primary_client
    primary_device.update_lock = asyncio.Lock()
    primary_device.serial_number = "PRIMARY_SN"

    lock_held_during_detect = False
    lock_held_during_populate = False

    async def mock_detect(client: Any) -> tuple[type, str]:  # noqa: ANN401
        nonlocal lock_held_during_detect
        lock_held_during_detect = primary_device.update_lock.locked()
        return MeterDevice, "PowerMeter"

    monkeypatch.setattr("huawei_solar.device.detect_device_type", mock_detect)

    original_populate = MeterDevice._populate_additional_fields

    async def mock_populate(self: MeterDevice) -> None:
        nonlocal lock_held_during_populate
        lock_held_during_populate = primary_device.update_lock.locked()
        await original_populate(self)

    monkeypatch.setattr(MeterDevice, "_populate_additional_fields", mock_populate)

    sub_device = await create_sub_device_instance(primary_device, 2)

    assert isinstance(sub_device, MeterDevice)
    assert lock_held_during_detect is True
    assert lock_held_during_populate is True
    assert not primary_device.update_lock.locked()


async def test_create_sub_device_instance_sun2000_does_not_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_sub_device_instance creating a SUN2000Device sub-device does not deadlock on update_lock."""
    primary_client = Mock()
    primary_client.unit_id = 1
    sub_client = Mock()
    sub_client.unit_id = 2
    primary_client.for_unit_id = Mock(return_value=sub_client)

    primary_device = Mock(spec=SUN2000Device)
    primary_device.client = primary_client
    primary_device.update_lock = asyncio.Lock()
    primary_device.serial_number = "PRIMARY_SN"

    async def mock_detect(client: Any) -> tuple[type, str]:  # noqa: ANN401
        return SUN2000Device, "SUN2000-10KTL"

    monkeypatch.setattr("huawei_solar.device.detect_device_type", mock_detect)

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[str]]:
        return [Result("SUB_SN", None), Result("PN", None), Result("V1", None), Result("V2", None)]

    sub_client.get_multiple = mock_get_multiple

    responses: dict[rn.RegisterName, Result[Any] | Exception] = {
        rn.NB_PV_STRINGS: Result(2, None),
        rn.NB_OPTIMIZERS: ReadException(_READ_FAILED_MSG),
        rn.STORAGE_UNIT_1_PRODUCT_MODEL: ReadException(_READ_FAILED_MSG),
        rn.STORAGE_UNIT_2_PRODUCT_MODEL: ReadException(_READ_FAILED_MSG),
        rn.FEATURE_MASK_3: ReadException(_READ_FAILED_MSG),
        rn.FEATURE_MASK_30308: ReadException(_READ_FAILED_MSG),
        rn.FEATURE_MASK_30320: ReadException(_READ_FAILED_MSG),
        rn.METER_STATUS: ReadException(_READ_FAILED_MSG),
    }

    async def mock_raw_get(self: SUN2000Device, name: rn.RegisterName) -> Result[Any]:
        if name in responses:
            val = responses[name]
            if isinstance(val, Exception):
                raise val
            return val
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(SUN2000Device, "_raw_get", mock_raw_get)

    sub_device = await create_sub_device_instance(primary_device, 2)

    assert isinstance(sub_device, SUN2000Device)
    assert sub_device.serial_number == "SUB_SN"
    assert sub_device.primary_device is primary_device
    assert not primary_device.update_lock.locked()
