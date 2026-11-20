"""Tests for the SCharger feature mask and the device connection status."""

from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from huawei_solar.device.scharger import SChargerDevice
from huawei_solar.exceptions import ConnectionInterruptedException, ReadException

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.register_definitions import Result


async def _create(feature_mask_4: Any) -> SChargerDevice:  # noqa: ANN401
    async def get(name: rn.RegisterName) -> Result[Any]:
        if name == rn.CHARGER_MODEL:
            return Result("SCharger-22KT-S0", None)
        assert name == rn.CHARGER_FEATURE_MASK_4
        if isinstance(feature_mask_4, BaseException):
            raise feature_mask_4
        return Result(feature_mask_4, None)

    client = Mock()
    client.unit_id = 6
    client.get_multiple = AsyncMock(return_value=[Result("ESN", None), Result("V100R023C10SPC231", None)])
    client.get = AsyncMock(side_effect=get)
    return await SChargerDevice.create(client, model_name="FusionCharge")


@pytest.mark.parametrize(
    ("feature_mask_4", "expected"),
    [
        # SCharger-22KT-S0 V100R023C10SPC231: 40104 = 0x00000005.
        (rv.ChargerFeatureMask4(0x5), True),
        (rv.ChargerFeatureMask4(0x1), False),
        # Unreadable or invalid: keep the random-delay settings, as before the check.
        (None, True),
        (ReadException("Modbus exception 0x02"), True),
        (TimeoutError(), True),
    ],
)
async def test_random_delay_follows_feature_mask_4(feature_mask_4: Any, *, expected: bool) -> None:  # noqa: ANN401
    """Random-delay charging is offered like the FusionSolar app does."""
    device = await _create(feature_mask_4)
    assert device.supports_random_delay is expected


async def test_feature_mask_probe_does_not_hide_a_dropped_connection() -> None:
    """A dropped connection still fails the setup."""
    with pytest.raises(ConnectionInterruptedException):
        await _create(ConnectionInterruptedException("lost"))
