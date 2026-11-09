"""Tests for device discovery."""

from unittest.mock import AsyncMock, Mock

from huawei_solar.device_discovery import get_device_infos
from huawei_solar.modbus_client import AsyncHuaweiSolarClient
from huawei_solar.modbus_pdu import HuaweiReadDeviceIdentificationPDU
from tmodbus.pdu.device import ConformityLevel, ReadDeviceIdentificationResponse


async def test_get_device_infos_parsing() -> None:
    client = Mock()
    client.read_device_identification = AsyncMock(
        return_value={
            0x87: b"\x02",
            0x88: b"1=FusionCharge-7KS-V01;2=V100R001C00SPC020;3=1.0;4=ESN_CHARGER;5=6;6=1.0;7=0;8=1",
            0x89: b"1=SmartAcGun;2=V100R001C00SPC020;3=1.0;4=ESN_GUN;5=7;6=1.0;7=0;8=2;9=6",
        }
    )

    device_infos = await get_device_infos(client)

    assert len(device_infos) == 2

    charger = device_infos[0]
    assert charger.model == "FusionCharge-7KS-V01"
    assert charger.device_id == 6
    assert charger.parent_device_id is None

    gun = device_infos[1]
    assert gun.model == "SmartAcGun"
    assert gun.device_id == 7
    assert gun.parent_device_id == 6


def test_huawei_read_device_identification_pdu_emma_streaming() -> None:
    """Test that HuaweiReadDeviceIdentificationPDU tolerates EMMA streaming behavior."""
    pdu = HuaweiReadDeviceIdentificationPDU(read_device_id_code=0x03, object_id=0x87)
    # Raw reply from EMMA:
    # function=0x2b, sub=0x0e, dev_id=0x03, conformity=0x03, more=0xff, next=0x88, num_objs=7, obj_id=0x87, len=1, val=6
    raw_pdu = bytes.fromhex("2b 0e 03 03 ff 88 07 87 01 06")
    result = pdu.decode_response(raw_pdu)

    assert result.device_id_code == 0x03
    assert result.conformity_level == ConformityLevel.EXTENDED
    assert result.more is True
    assert result.next_object_id == 0x88
    assert result.number_of_objects == 7
    assert result.objects == {0x87: b"\x06"}


async def test_async_huawei_solar_client_read_device_identification() -> None:
    """Test AsyncHuaweiSolarClient.read_device_identification executes HuaweiReadDeviceIdentificationPDU."""
    mock_transport = Mock()
    client = AsyncHuaweiSolarClient(transport=mock_transport, unit_id=0)

    # First response: more=True, next=0x88
    resp1 = ReadDeviceIdentificationResponse(
        device_id_code=0x03,
        conformity_level=ConformityLevel.EXTENDED,
        more=True,
        next_object_id=0x88,
        number_of_objects=2,
        objects={0x87: b"\x02"},
    )
    # Second response: more=False, next=0x00
    resp2 = ReadDeviceIdentificationResponse(
        device_id_code=0x03,
        conformity_level=ConformityLevel.EXTENDED,
        more=False,
        next_object_id=0x00,
        number_of_objects=2,
        objects={0x88: b"device_entry"},
    )

    client.execute = AsyncMock(side_effect=[resp1, resp2])  # type: ignore[method-assign]

    result = await client.read_device_identification(device_code=0x03, object_id=0x87)

    assert result == {0x87: b"\x02", 0x88: b"device_entry"}
    assert client.execute.call_count == 2
    first_call_pdu = client.execute.call_args_list[0].args[0]
    assert isinstance(first_call_pdu, HuaweiReadDeviceIdentificationPDU)
    assert first_call_pdu.read_device_id_code == 0x03
    assert first_call_pdu.object_id == 0x87
    second_call_pdu = client.execute.call_args_list[1].args[0]
    assert isinstance(second_call_pdu, HuaweiReadDeviceIdentificationPDU)
    assert second_call_pdu.read_device_id_code == 0x03
    assert second_call_pdu.object_id == 0x88
