"""Tests for the SmartLoad device."""

import asyncio
from typing import Any
from unittest.mock import Mock

import pytest
from huawei_solar.device.emma import EMMADevice
from huawei_solar.device.smart_load import SmartLoadDevice
from huawei_solar.device.sun2000 import SUN2000Device
from huawei_solar.exceptions import ReadException
from huawei_solar.registers import REGISTERS
from tmodbus.exceptions import IllegalDataAddressError

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.device import create_sub_device_instance, detect_device_type
from huawei_solar.register_definitions import Result


def _emma_with_sub_client(responses: dict[rn.RegisterName, Any], unit_id: int = 38) -> Mock:
    primary_client = Mock()
    primary_client.unit_id = 0
    sub_client = Mock()
    sub_client.unit_id = unit_id
    primary_client.for_unit_id = Mock(return_value=sub_client)

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        value = responses.get(
            name,
            ReadException("Failed to read register", modbus_exception_code=IllegalDataAddressError.error_code),
        )
        if isinstance(value, Exception):
            raise value
        return Result(value, None)

    sub_client.get = mock_get

    primary_device = Mock(spec=EMMADevice)
    primary_device.client = primary_client
    primary_device.update_lock = asyncio.Lock()
    primary_device.serial_number = "EMMA_SN"
    return primary_device


async def test_smart_load_detected_when_model_name_is_unreadable() -> None:
    """The EMMA rejects reading MODEL_NAME (15 registers) on a SmartLoad, the serial number identifies it."""
    primary_device = _emma_with_sub_client(
        {
            rn.SMARTLOAD_NAME: "DO load1",
            rn.SMARTLOAD_SWITCH_STATUS: True,
            rn.SMARTLOAD_SERIAL_NUMBER: "LD26EMMA_SN",
        },
    )

    device = await asyncio.wait_for(create_sub_device_instance(primary_device, 38), timeout=1)

    assert isinstance(device, SmartLoadDevice)
    assert device.model_name == "SmartLoad"
    assert device.name == "DO load1"
    assert device.serial_number == "LD26EMMA_SN"


async def test_smart_load_detected_via_serial_number_with_name_in_model_name() -> None:
    """If MODEL_NAME returns the user-given name, the serial number still identifies the SmartLoad."""
    primary_device = _emma_with_sub_client(
        {
            rn.MODEL_NAME: "DO load1",
            rn.SMARTLOAD_NAME: "DO load1",
            rn.SMARTLOAD_SWITCH_STATUS: None,
            rn.SMARTLOAD_SERIAL_NUMBER: "LD26EMMA_SN",
        },
    )

    device_type, model_name = await detect_device_type(primary_device.client.for_unit_id(38))

    assert device_type is SmartLoadDevice
    assert model_name == "SmartLoad"


async def test_unknown_inverter_model_is_not_detected_as_smart_load() -> None:
    """A SUN2000 answers 65510 and 30020 (inside its serial number), but its serial number lacks the LD prefix."""
    primary_device = _emma_with_sub_client(
        {
            rn.MODEL_NAME: "UnknownModel",
            rn.SMARTLOAD_SWITCH_STATUS: True,
            rn.SMARTLOAD_SERIAL_NUMBER: "HV2480076397",
        },
        unit_id=6,
    )

    device_type, model_name = await detect_device_type(primary_device.client.for_unit_id(6))

    assert device_type is SUN2000Device
    assert model_name == "UnknownModel"


async def test_smart_load_serial_number_fallback() -> None:
    """Without a readable serial number the SmartLoad gets one derived from the EMMA."""
    primary_device = _emma_with_sub_client({rn.SMARTLOAD_NAME: "DO load1"})

    device = await SmartLoadDevice.create(
        primary_device.client.for_unit_id(38),
        model_name="SmartLoad",
        primary_device=primary_device,
    )

    assert device.serial_number == "EMMA_SN_smartload_38"


async def test_unknown_model_without_smart_load_serial_falls_back_to_sun2000() -> None:
    """An unknown register 30000 value without a SmartLoad serial number falls back to SUN2000Device."""
    primary_device = _emma_with_sub_client({rn.MODEL_NAME: "UnknownModel"}, unit_id=33)

    device_type, model_name = await detect_device_type(primary_device.client.for_unit_id(33))

    assert device_type is SUN2000Device
    assert model_name == "UnknownModel"


def test_smart_load_supports_device() -> None:
    assert SmartLoadDevice.supports_device("SmartLoad")
    assert not SmartLoadDevice.supports_device("SmartGuard-63A-T0")


@pytest.mark.parametrize(
    ("register_name", "raw", "expected"),
    [
        (rn.SMARTLOAD_SWITCH_STATUS, 0, False),
        (rn.SMARTLOAD_SWITCH_STATUS, 1, True),
        (rn.SMARTLOAD_SWITCH_STATUS, 0xFFFF, None),
        (rn.SMARTLOAD_OFF_GRID_AUTO_CONTROL, 0, False),
        (rn.SMARTLOAD_OFF_GRID_AUTO_CONTROL, 1, True),
        (rn.SMARTLOAD_OFF_GRID_AUTO_CONTROL, 0xFFFF, None),
        (rn.SMARTLOAD_OFF_GRID_MODE, 0, rv.SmartLoadOffGridMode.BASIC),
        (rn.SMARTLOAD_OFF_GRID_MODE, 1, rv.SmartLoadOffGridMode.BATTERY),
        (rn.SMARTLOAD_OFF_GRID_MODE, 0xFFFF, None),
        (rn.SMARTLOAD_RATED_POWER, 3000, 3000),
        (rn.SMARTLOAD_RATED_POWER, 0xFFFF, None),
        (rn.SMARTLOAD_OFF_GRID_RESUME_SOC, 80, 80),
        (rn.SMARTLOAD_OFF_GRID_STOP_SOC, 0xFFFF, None),
    ],
)
def test_smart_load_register_decoding(register_name: rn.RegisterName, raw: int, expected: object) -> None:
    """Valid 0/1 values keep their meaning, the invalid marker 65535 decodes to None."""
    result = REGISTERS[register_name].decode((raw,))

    assert result.value == expected
    if expected is None:
        assert result.value is None
