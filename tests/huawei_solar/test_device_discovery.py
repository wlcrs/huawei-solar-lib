"""Tests for device discovery."""

from unittest.mock import AsyncMock, Mock

from huawei_solar.device_discovery import get_device_infos


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
