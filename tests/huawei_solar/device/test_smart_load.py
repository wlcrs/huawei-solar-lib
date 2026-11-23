"""Tests for the SmartLoad device."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from huawei_solar.device.emma import EMMADevice
from huawei_solar.device.smart_load import SmartLoadDevice
from huawei_solar.exceptions import ReadException
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.device import create_sub_device_instance
from huawei_solar.register_definitions import Result

DEVICE_LIST = {
    0x87: b"\x03",
    0x88: b"1=EMMA-A02;2=V100R025C00SPC142;3=P1.15-D1.0;4=EMMA_SN;5=0;6=1.0;8=HEMS;9=0",
    0x89: b"1=SmartSwitch;2=1.0;3=P1.15;4=SWITCH_SN;5=33;6=1;8=SmartSwitch;9=0",
    0x8A: b"1=SmartLoad;2=1.0;3=P1.15;4=LD26EMMA_SN;5=38;6=1;8=SmartLoad;9=0",
}


def _emma_with_sub_client(responses: dict[rn.RegisterName, Any], unit_id: int = 38) -> Mock:
    primary_client = Mock()
    primary_client.unit_id = 0
    primary_client.read_device_identification = AsyncMock(return_value=dict(DEVICE_LIST))
    sub_client = Mock()
    sub_client.unit_id = unit_id
    primary_client.for_unit_id = Mock(return_value=sub_client)

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        value = responses.get(name, ReadException("Failed to read register"))
        if isinstance(value, Exception):
            raise value
        return Result(value, None)

    sub_client.get = mock_get

    primary_device = Mock(spec=EMMADevice)
    primary_device.client = primary_client
    primary_device.update_lock = asyncio.Lock()
    primary_device.serial_number = "EMMA_SN"
    return primary_device


async def test_smart_load_detected_via_device_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register 30000 holds the user-given name, so the SmartLoad is recognised via the EMMA device list."""
    primary_device = _emma_with_sub_client(
        {rn.SMARTLOAD_NAME: "DO load1", rn.SMARTLOAD_SERIAL_NUMBER: "LD26EMMA_SN"},
    )
    detect = AsyncMock()
    monkeypatch.setattr("huawei_solar.device.detect_device_type", detect)

    device = await asyncio.wait_for(create_sub_device_instance(primary_device, 38), timeout=1)

    assert isinstance(device, SmartLoadDevice)
    assert device.model_name == "SmartLoad"
    assert device.name == "DO load1"
    assert device.serial_number == "LD26EMMA_SN"
    detect.assert_not_called()


async def test_smart_load_serial_number_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a readable serial number the SmartLoad gets one derived from the EMMA."""
    primary_device = _emma_with_sub_client({rn.SMARTLOAD_NAME: "DO load1"})
    monkeypatch.setattr("huawei_solar.device.detect_device_type", AsyncMock())

    device = await asyncio.wait_for(create_sub_device_instance(primary_device, 38), timeout=1)

    assert isinstance(device, SmartLoadDevice)
    assert device.serial_number == "EMMA_SN_smartload_38"


async def test_other_unit_ids_use_register_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Devices that are not SmartLoads are still detected via their own registers."""
    primary_device = _emma_with_sub_client({}, unit_id=33)

    async def mock_detect(client: Any) -> tuple[type, str]:  # noqa: ANN401
        msg = "not detected"
        raise ReadException(msg)

    monkeypatch.setattr("huawei_solar.device.detect_device_type", mock_detect)

    with pytest.raises(ReadException):
        await asyncio.wait_for(create_sub_device_instance(primary_device, 33), timeout=1)


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
