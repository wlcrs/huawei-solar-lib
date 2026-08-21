"""Tests for DeviceGroupMixin and multi-device register reading."""

from unittest.mock import AsyncMock, patch

import huawei_solar.register_names as rn
import pytest
from huawei_solar.exceptions import ReadException
from huawei_solar.modbus_client import AsyncHuaweiSolarClient

from huawei_solar.device import SDongleDevice, SUN2000Device


@pytest.fixture
def sdongle_with_slaves(huawei_solar: AsyncHuaweiSolarClient) -> tuple[SDongleDevice, list[SUN2000Device]]:
    """Create a mock SDongleDevice and downstream SUN2000Devices."""
    sdongle = SDongleDevice(
        client=huawei_solar.for_unit_id(0),
        model_name="SDongleA-05",
        primary_device=None,
    )
    dev1 = SUN2000Device(
        client=huawei_solar.for_unit_id(1),
        model_name="SUN2000-3KTL-L1",
        primary_device=sdongle,
    )
    dev2 = SUN2000Device(
        client=huawei_solar.for_unit_id(2),
        model_name="SUN2000-5KTL-L1",
        primary_device=sdongle,
    )
    return sdongle, [dev1, dev2]


async def test_client_get_multi_device(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """Test get_multi_device on RegisterAwareModbusClient."""
    results = await huawei_solar.get_multi_device(rn.MODEL_ID, unit_ids=[1, 2])
    assert len(results) == 2
    assert results[1].value == 348
    assert results[2].value == 348


async def test_client_get_multi_device_scattered(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """Test get_multi_device_scattered on RegisterAwareModbusClient."""
    results = await huawei_solar.get_multi_device_scattered(
        {
            1: [rn.MODEL_ID, rn.DEVICE_STATUS],
            2: [rn.MODEL_ID, rn.NB_PV_STRINGS],
        },
    )
    assert len(results) == 2
    assert results[1][rn.MODEL_ID].value == 348
    assert results[1][rn.DEVICE_STATUS].value == "Standby: no irradiation"
    assert results[2][rn.MODEL_ID].value == 348
    assert results[2][rn.NB_PV_STRINGS].value == 2


async def test_gateway_group_get(
    sdongle_with_slaves: tuple[SDongleDevice, list[SUN2000Device]],
) -> None:
    """Test group_get on SDongleDevice across downstream slaves."""
    sdongle, (dev1, dev2) = sdongle_with_slaves

    results = await sdongle.group_get(rn.MODEL_ID, devices=[dev1, dev2])
    assert len(results) == 2
    assert results[dev1].value == 348
    assert results[dev2].value == 348


async def test_gateway_group_batch_update(
    sdongle_with_slaves: tuple[SDongleDevice, list[SUN2000Device]],
) -> None:
    """Test group_batch_update on SDongleDevice across downstream slaves."""
    sdongle, (dev1, dev2) = sdongle_with_slaves

    results = await sdongle.group_batch_update(
        {
            dev1: [rn.MODEL_ID, rn.DEVICE_STATUS],
            dev2: [rn.MODEL_ID, rn.NB_PV_STRINGS],
        },
    )
    assert results[dev1][rn.MODEL_ID].value == 348
    assert results[dev1][rn.DEVICE_STATUS].value == "Standby: no irradiation"
    assert results[dev2][rn.MODEL_ID].value == 348
    assert results[dev2][rn.NB_PV_STRINGS].value == 2


async def test_gateway_group_batch_update_all(
    sdongle_with_slaves: tuple[SDongleDevice, list[SUN2000Device]],
) -> None:
    """Test group_batch_update_all on SDongleDevice across all downstream slaves."""
    sdongle, (dev1, dev2) = sdongle_with_slaves

    results = await sdongle.group_batch_update_all([rn.MODEL_ID, rn.DEVICE_STATUS], devices=[dev1, dev2])
    assert len(results) == 2
    assert results[dev1][rn.MODEL_ID].value == 348
    assert results[dev1][rn.DEVICE_STATUS].value == "Standby: no irradiation"
    assert results[dev2][rn.MODEL_ID].value == 348
    assert results[dev2][rn.DEVICE_STATUS].value == "Standby: no irradiation"


async def test_gateway_group_fallback_on_error(
    sdongle_with_slaves: tuple[SDongleDevice, list[SUN2000Device]],
) -> None:
    """Test that group_batch_update falls back and permanently disables custom read on error."""
    sdongle, (dev1, dev2) = sdongle_with_slaves
    assert sdongle.supports_custom_multi_device_read is True

    mock_custom = AsyncMock(side_effect=ReadException("0x41 0x37 unsupported"))
    with patch.object(sdongle.client, "get_multi_device_scattered", mock_custom):
        results = await sdongle.group_batch_update(
            {
                dev1: [rn.MODEL_ID, rn.DEVICE_STATUS],
                dev2: [rn.MODEL_ID, rn.NB_PV_STRINGS],
            },
        )
        assert results[dev1][rn.MODEL_ID].value == 348
        assert results[dev1][rn.DEVICE_STATUS].value == "Standby: no irradiation"
        assert results[dev2][rn.MODEL_ID].value == 348
        assert results[dev2][rn.NB_PV_STRINGS].value == 2
        assert mock_custom.call_count == 1
        assert sdongle.supports_custom_multi_device_read is False

        # Subsequent call should not even attempt get_multi_device_scattered
        subsequent_results = await sdongle.group_batch_update(
            {
                dev1: [rn.MODEL_ID],
            },
        )
        assert subsequent_results[dev1][rn.MODEL_ID].value == 348
        assert mock_custom.call_count == 1  # Not called again
