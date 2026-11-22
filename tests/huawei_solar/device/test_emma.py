"""Tests for the EMMADevice class."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from huawei_solar.exceptions import ReadException
from huawei_solar.register_definitions.periods import PeakSettingPeriod
from huawei_solar.registers import REGISTERS

from huawei_solar import AsyncHuaweiSolarClient
from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.device import EMMADevice
from huawei_solar.register_definitions import Result

_READ_FAILED_MSG = "read failed"


@pytest.fixture
def emma_device() -> EMMADevice:
    """Create an EMMADevice instance with a mocked client."""
    client = AsyncMock(spec=AsyncHuaweiSolarClient)
    client.unit_id = 0
    return EMMADevice(client=client, model_name="SmartHEMS")


def _setup_emma_client_mocks(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[rn.RegisterName, Result[Any] | Exception],
) -> list[rn.RegisterName]:
    """Configure client mocks and record queried single-register names."""
    queried: list[rn.RegisterName] = []
    utc_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)

    async def mock_get_multiple(names: list[rn.RegisterName]) -> list[Result[Any]]:
        if names == [rn.SERIAL_NUMBER, rn.EMMA_SOFTWARE_VERSION]:
            return [Result("EMMA123", None), Result("V100", None)]
        msg = f"Unexpected get_multiple: {names}"
        raise AssertionError(msg)

    async def mock_get(name: rn.RegisterName) -> Result[Any]:
        queried.append(name)
        if name == rn.EMMA_MODEL:
            return Result("EMMA-A02", None)
        if name in responses:
            val = responses[name]
            if isinstance(val, Exception):
                raise val
            return val
        if name in (rn.EMMA_LOCAL_TIME, rn.EMMA_SYSTEM_TIME):
            return Result(utc_time, None)
        msg = f"Unexpected get: {name}"
        raise AssertionError(msg)

    monkeypatch.setattr(emma_device.client, "get_multiple", mock_get_multiple)
    monkeypatch.setattr(emma_device.client, "get", mock_get)
    return queried


@pytest.mark.parametrize(
    ("feature_mask", "expected"),
    [
        (rv.EmmaFeatureMask30164(0), True),
        (rv.EmmaFeatureMask30164.DI_SCHEDULING, True),
        (rv.EmmaFeatureMask30164.CAPACITY_CONTROL, False),
        (rv.EmmaFeatureMask30164.CAPACITY_CONTROL | rv.EmmaFeatureMask30164.DI_SCHEDULING, False),
    ],
)
async def test_supports_capacity_control_with_feature_mask_30164(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
    feature_mask: rv.EmmaFeatureMask30164,
    *,
    expected: bool,
) -> None:
    """When LUNA2000 is connected, bit 5 of register 30164 hides/disables capacity control when set."""
    queried = _setup_emma_client_mocks(
        emma_device,
        monkeypatch,
        {
            rn.EMMA_BATTERY_PRODUCT_MODEL: Result(rv.StorageProductModel.HUAWEI_LUNA2000, None),
            rn.EMMA_FEATURE_MASK_30164: Result(feature_mask, None),
        },
    )

    await emma_device._populate_additional_fields()

    assert emma_device.serial_number == "EMMA123"
    assert emma_device.software_version == "V100"
    assert emma_device.battery_type == rv.StorageProductModel.HUAWEI_LUNA2000
    assert emma_device.supports_capacity_control is expected
    assert rn.EMMA_CAPACITY_CONTROL_MODE not in queried


@pytest.mark.parametrize(
    ("battery_response", "expected_battery_type", "expected_has_battery"),
    [
        (Result(rv.StorageProductModel.NONE, None), rv.StorageProductModel.NONE, False),
        (Result(rv.StorageProductModel.LG_RESU, None), rv.StorageProductModel.LG_RESU, True),
        (Result(None, None), rv.StorageProductModel.NONE, False),
        (ReadException(_READ_FAILED_MSG), rv.StorageProductModel.NONE, False),
    ],
)
async def test_supports_capacity_control_disabled_without_luna2000_battery(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
    battery_response: Result[Any] | Exception,
    expected_battery_type: rv.StorageProductModel,
    *,
    expected_has_battery: bool,
) -> None:
    """Capacity control is disabled without probing 40200 if no battery is present or battery is LG RESU."""
    queried = _setup_emma_client_mocks(
        emma_device,
        monkeypatch,
        {
            rn.EMMA_BATTERY_PRODUCT_MODEL: battery_response,
            rn.RATED_ESS_CAPACITY: Result(0, "kWh"),
            rn.STATE_OF_CAPACITY: Result(None, None),
            rn.EMMA_FEATURE_MASK_30164: Result(rv.EmmaFeatureMask30164(0), None),
        },
    )

    await emma_device._populate_additional_fields()

    assert emma_device.battery_type == expected_battery_type
    assert emma_device.has_battery is expected_has_battery
    assert emma_device.supports_capacity_control is False
    assert emma_device.supports_power_limited_grid_connection is True
    assert rn.EMMA_FEATURE_MASK_30164 in queried
    assert rn.EMMA_CAPACITY_CONTROL_MODE not in queried


@pytest.mark.parametrize(
    ("responses", "expected_capacity_control"),
    [
        (
            {
                rn.EMMA_BATTERY_PRODUCT_MODEL: Result(rv.StorageProductModel.NONE, None),
                rn.RATED_ESS_CAPACITY: Result(15.0, "kWh"),
                rn.STATE_OF_CAPACITY: Result(23.0, "%"),
                rn.EMMA_FEATURE_MASK_30164: Result(rv.EmmaFeatureMask30164(0), None),
            },
            True,
        ),
        (
            {
                rn.EMMA_BATTERY_PRODUCT_MODEL: Result(rv.StorageProductModel.NONE, None),
                rn.RATED_ESS_CAPACITY: Result(0, "kWh"),
                rn.STATE_OF_CAPACITY: Result(23.0, "%"),
                rn.EMMA_FEATURE_MASK_30164: Result(rv.EmmaFeatureMask30164.CAPACITY_CONTROL, None),
            },
            False,
        ),
        (
            {
                rn.EMMA_BATTERY_PRODUCT_MODEL: ReadException(_READ_FAILED_MSG),
                rn.RATED_ESS_CAPACITY: ReadException(_READ_FAILED_MSG),
                rn.STATE_OF_CAPACITY: Result(50.0, "%"),
                rn.EMMA_FEATURE_MASK_30164: Result(rv.EmmaFeatureMask30164(0), None),
            },
            True,
        ),
        (
            {
                rn.EMMA_BATTERY_PRODUCT_MODEL: Result(None, None),
                rn.RATED_ESS_CAPACITY: Result(10.0, "kWh"),
                rn.STATE_OF_CAPACITY: Result(None, None),
                rn.EMMA_FEATURE_MASK_30164: Result(rv.EmmaFeatureMask30164(0), None),
            },
            True,
        ),
    ],
)
async def test_battery_presence_fallback_via_ess_telemetry(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[rn.RegisterName, Result[Any] | Exception],
    *,
    expected_capacity_control: bool,
) -> None:
    """When 30706 returns NONE/None or is unsupported, ESS telemetry detects the battery and gates capacity control."""
    _setup_emma_client_mocks(emma_device, monkeypatch, responses)

    await emma_device._populate_additional_fields()

    assert emma_device.battery_type == rv.StorageProductModel.NONE
    assert emma_device.has_battery is True
    assert emma_device.supports_capacity_control is expected_capacity_control


async def test_battery_presence_legacy_firmware_when_30706_and_ess_unsupported(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When 30706 and ESS telemetry registers are all unsupported, preserve 2.2.0 behavior (has_battery=True)."""
    queried = _setup_emma_client_mocks(
        emma_device,
        monkeypatch,
        {
            rn.EMMA_BATTERY_PRODUCT_MODEL: ReadException(_READ_FAILED_MSG),
            rn.RATED_ESS_CAPACITY: ReadException(_READ_FAILED_MSG),
            rn.STATE_OF_CAPACITY: ReadException(_READ_FAILED_MSG),
            rn.EMMA_FEATURE_MASK_30164: ReadException(_READ_FAILED_MSG),
            rn.EMMA_CAPACITY_CONTROL_MODE: ReadException(_READ_FAILED_MSG),
        },
    )

    await emma_device._populate_additional_fields()

    assert emma_device.battery_type == rv.StorageProductModel.NONE
    assert emma_device.has_battery is True
    assert emma_device.supports_capacity_control is False
    assert rn.EMMA_CAPACITY_CONTROL_MODE in queried


@pytest.mark.parametrize(
    ("mask_response", "expected_power_limited", "expected_di_scheduling"),
    [
        (Result(rv.EmmaFeatureMask30164(0), None), True, True),
        (Result(rv.EmmaFeatureMask30164.POWER_LIMITED_GRID_CONNECTION, None), False, True),
        (Result(rv.EmmaFeatureMask30164.DI_SCHEDULING, None), True, False),
        (
            Result(
                rv.EmmaFeatureMask30164.POWER_LIMITED_GRID_CONNECTION | rv.EmmaFeatureMask30164.DI_SCHEDULING,
                None,
            ),
            False,
            False,
        ),
        (ReadException(_READ_FAILED_MSG), True, True),
        (Result(None, None), True, True),
    ],
)
async def test_feature_mask_30164_gating_without_battery(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
    mask_response: Result[Any] | Exception,
    *,
    expected_power_limited: bool,
    expected_di_scheduling: bool,
) -> None:
    """Register 30164 bits 3 and 4 hide power-limited grid connection and DI scheduling even without a battery."""
    queried = _setup_emma_client_mocks(
        emma_device,
        monkeypatch,
        {
            rn.EMMA_BATTERY_PRODUCT_MODEL: Result(rv.StorageProductModel.NONE, None),
            rn.RATED_ESS_CAPACITY: Result(0, "kWh"),
            rn.STATE_OF_CAPACITY: Result(None, None),
            rn.EMMA_FEATURE_MASK_30164: mask_response,
        },
    )

    await emma_device._populate_additional_fields()

    assert emma_device.supports_power_limited_grid_connection is expected_power_limited
    assert emma_device.supports_di_scheduling is expected_di_scheduling
    assert emma_device.supports_capacity_control is False
    assert rn.EMMA_CAPACITY_CONTROL_MODE not in queried


@pytest.mark.parametrize(
    ("mask_response", "mode_response", "expected"),
    [
        (ReadException(_READ_FAILED_MSG), Result(rv.StorageCapacityControlMode.DISABLE, None), True),
        (ReadException(_READ_FAILED_MSG), ReadException(_READ_FAILED_MSG), False),
        (Result(None, None), Result(rv.StorageCapacityControlMode.ACTIVE_CAPACITY_CONTROL, None), True),
        (Result(None, None), ReadException(_READ_FAILED_MSG), False),
    ],
)
async def test_supports_capacity_control_fallback_when_30164_unavailable(
    emma_device: EMMADevice,
    monkeypatch: pytest.MonkeyPatch,
    mask_response: Result[Any] | Exception,
    mode_response: Result[Any] | Exception,
    *,
    expected: bool,
) -> None:
    """Fall back to probing register 40200 when register 30164 is unsupported or invalid (0xFFFFFFFF)."""
    queried = _setup_emma_client_mocks(
        emma_device,
        monkeypatch,
        {
            rn.EMMA_BATTERY_PRODUCT_MODEL: Result(rv.StorageProductModel.HUAWEI_LUNA2000, None),
            rn.EMMA_FEATURE_MASK_30164: mask_response,
            rn.EMMA_CAPACITY_CONTROL_MODE: mode_response,
        },
    )

    await emma_device._populate_additional_fields()

    assert emma_device.supports_capacity_control is expected
    assert rn.EMMA_CAPACITY_CONTROL_MODE in queried


def test_emma_capacity_control_register_codecs() -> None:
    """Verify EMMA peak shaving and feature mask registers encode/decode expected values."""
    assert REGISTERS[rn.EMMA_FEATURE_MASK_30122].decode((1 << 20,)).value == (
        rv.EmmaFeatureMask30122.THREE_PHASE_UNBALANCE_CONTROL
    )
    assert REGISTERS[rn.EMMA_FEATURE_MASK_30124].decode((1 << 15,)).value == rv.EmmaFeatureMask30124.CHARGE_FROM_AC
    assert REGISTERS[rn.EMMA_FEATURE_MASK_30126].decode((1 << 19,)).value == (
        rv.EmmaFeatureMask30126.DRY_CONTACT_LIMITATION_MODE
    )
    assert REGISTERS[rn.EMMA_FEATURE_MASK_30172].decode((1 << 7,)).value == rv.EmmaFeatureMask30172.BATTERY_EOD_EOC_SOC
    assert REGISTERS[rn.EMMA_FEATURE_MASK_30164].decode((1 << 5,)).value == rv.EmmaFeatureMask30164.CAPACITY_CONTROL
    assert REGISTERS[rn.EMMA_FEATURE_MASK_30164].decode((0xFFFFFFFF,)).value is None
    assert REGISTERS[rn.EMMA_BATTERY_PRODUCT_MODEL].decode((2,)).value == rv.StorageProductModel.HUAWEI_LUNA2000

    mode_reg = REGISTERS[rn.EMMA_CAPACITY_CONTROL_MODE]
    assert mode_reg.decode((1,)).value == rv.StorageCapacityControlMode.ACTIVE_CAPACITY_CONTROL
    assert mode_reg.encode(rv.StorageCapacityControlMode.APPARENT_POWER_LIMIT) == (2,)

    soc_reg = REGISTERS[rn.EMMA_CAPACITY_CONTROL_SOC_PEAK_SHAVING]
    assert soc_reg.decode((355,)).value == 35.5
    assert soc_reg.encode(35.5) == (355,)

    periods_reg = REGISTERS[rn.EMMA_CAPACITY_CONTROL_PERIODS]
    period = PeakSettingPeriod(
        start_time=0,
        end_time=1439,
        power=2500,
        days_effective=(True, True, True, True, True, True, True),
    )
    encoded = periods_reg.encode([period])
    assert periods_reg.decode(encoded).value == [period]
