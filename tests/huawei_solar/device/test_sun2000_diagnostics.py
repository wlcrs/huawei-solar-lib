"""Tests for the inverter diagnostics from the FusionSolar app: off-grid mode, AFCI and insulation threshold."""

from typing import Any

import pytest
from huawei_solar.device.sun2000 import SUN2000Device
from huawei_solar.exceptions import ConnectionInterruptedException, ReadException
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.register_definitions import Result

_NOT_SUPPORTED = "Modbus exception 0x02"


def _mock_get(monkeypatch: pytest.MonkeyPatch, device: SUN2000Device, answers: dict[rn.RegisterName, Any]) -> None:
    async def get(name: rn.RegisterName) -> Result[Any]:
        value = answers.get(name, ReadException(_NOT_SUPPORTED, modbus_exception_code=0x02))
        if isinstance(value, BaseException):
            raise value
        return Result(value, None)

    monkeypatch.setattr(device.client, "get", get)


async def test_reference_plant(sun2000_device: SUN2000Device, monkeypatch: pytest.MonkeyPatch) -> None:
    """SUN2000-12K-MAP0 behind an EMMA-A02 (2026-11-15): 30309 = 0xFEAF, 30310 = 0xFFC9, AFCI and threshold offered."""
    _mock_get(
        monkeypatch,
        sun2000_device,
        {rn.FEATURE_MASK_30309: rv.FeatureMask30309(0xFEAF), rn.FEATURE_MASK_30310: rv.FeatureMask30310(0xFFC9)},
    )
    await sun2000_device._populate_protection_support()

    assert sun2000_device.supports_afci is True
    assert sun2000_device.supports_insulation_threshold is True


@pytest.mark.parametrize(
    "answers",
    [
        {rn.FEATURE_MASK_30309: rv.FeatureMask30309(0), rn.FEATURE_MASK_30310: rv.FeatureMask30310(0)},
        {},  # older firmware: both masks rejected
        {rn.FEATURE_MASK_30309: None, rn.FEATURE_MASK_30310: None},  # invalid value
    ],
)
async def test_cleared_or_missing_bits_hide_the_settings(
    sun2000_device: SUN2000Device, monkeypatch: pytest.MonkeyPatch, answers: dict[rn.RegisterName, Any]
) -> None:
    """A cleared bit, a rejected mask or an invalid mask hides the setting, and the setup goes on."""
    _mock_get(monkeypatch, sun2000_device, answers)
    await sun2000_device._populate_protection_support()

    assert sun2000_device.supports_afci is False
    assert sun2000_device.supports_insulation_threshold is False


async def test_dropped_connection_fails_the_setup(
    sun2000_device: SUN2000Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dropped connection is not "not supported": the setup fails and is retried."""
    _mock_get(monkeypatch, sun2000_device, {rn.FEATURE_MASK_30309: ConnectionInterruptedException("lost")})

    with pytest.raises(ConnectionInterruptedException):
        await sun2000_device._populate_protection_support()


@pytest.mark.parametrize(
    ("mask_30308", "expected"), [(rv.FeatureMask30308.BACKUP_OFF_GRID_SWITCHING, True), (0, False)]
)
async def test_off_grid_mode_follows_30308_bit_10(
    sun2000_device: SUN2000Device, monkeypatch: pytest.MonkeyPatch, mask_30308: int, *, expected: bool
) -> None:
    """Off-grid mode (42045) is offered when 30308 bit 10 is set, whatever 30316 says."""
    _mock_get(monkeypatch, sun2000_device, {rn.FEATURE_MASK_30308: rv.FeatureMask30308(mask_30308)})
    await sun2000_device._populate_backup_support()

    assert sun2000_device.supports_off_grid_mode is expected
    assert sun2000_device.supports_off_grid_switch is False  # 30316 not answered


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        (rn.OFF_GRID_MODE, 1, True),
        (rn.AFCI_ENABLED, 0, False),
        (rn.INSULATION_RESISTANCE_PROTECTION_THRESHOLD_V3, 50, 0.05),
    ],
)
def test_registers_decode_as_the_app_shows_them(name: rn.RegisterName, raw: int, expected: object) -> None:
    """The values read on the reference plant: 42045 = 1, 42073 = 1, 42097 = 50 (0.05 MOhm)."""
    assert REGISTERS[name].decode((raw,)).value == expected
