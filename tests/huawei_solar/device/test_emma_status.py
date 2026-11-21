"""Tests for the EMMA system state and active alarm count registers."""

from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from huawei_solar.device.emma import EMMADevice
from huawei_solar.exceptions import ConnectionInterruptedException, DecodeError, ReadException
from huawei_solar.registers import REGISTERS

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.register_definitions import Result

_NOT_SUPPORTED = "Modbus exception 0x03"
_ALARM_COUNTS = [
    rn.EMMA_ACTIVE_ALARMS_CRITICAL,
    rn.EMMA_ACTIVE_ALARMS_MAJOR,
    rn.EMMA_ACTIVE_ALARMS_MINOR,
    rn.EMMA_ACTIVE_ALARMS_WARNING,
]


def _emma_client(*, system_state: Any, alarm_counts: Any) -> Mock:  # noqa: ANN401
    not_supported = ReadException(_NOT_SUPPORTED)
    answers: dict[rn.RegisterName, Result[Any] | Exception] = {
        rn.EMMA_MODEL: Result("EMMA-A02", None),
        rn.EMMA_LOCAL_TIME: not_supported,
        rn.EMMA_SYSTEM_TIME: not_supported,
        rn.EMMA_BATTERY_PRODUCT_MODEL: not_supported,
        rn.EMMA_FEATURE_MASK_30164: not_supported,
        rn.EMMA_SYSTEM_STATE: system_state if isinstance(system_state, Exception) else Result(system_state, None),
    }

    async def get_multiple(names: list[rn.RegisterName]) -> list[Result[Any]]:
        if names == [rn.SERIAL_NUMBER, rn.SOFTWARE_VERSION]:
            return [Result("EMMA_SN", None), Result("SmartHEMS V100R025C00SPC142", None)]
        if names == _ALARM_COUNTS:
            if isinstance(alarm_counts, Exception):
                raise alarm_counts
            return [Result(alarm_counts, None)] * 4
        msg = f"unexpected get_multiple {names}"
        raise AssertionError(msg)

    async def get(name: rn.RegisterName) -> Result[Any]:
        if name not in answers:
            msg = f"unexpected get {name}"
            raise AssertionError(msg)
        answer = answers[name]
        if isinstance(answer, Exception):
            raise answer
        return answer

    client = Mock()
    client.unit_id = 0
    client.get_multiple = AsyncMock(side_effect=get_multiple)
    client.get = AsyncMock(side_effect=get)
    return client


async def _create(client: Mock) -> EMMADevice:
    return await EMMADevice.create(client, model_name="SmartHEMS")


@pytest.mark.parametrize(
    ("system_state", "alarm_counts", "expected_state", "expected_counts"),
    [
        (rv.EmmaSystemState.ON_GRID, 0, True, True),
        # Answered with the U16 invalid value (0xFFFF): still supported, shows as unknown.
        (None, None, True, True),
        (ReadException(_NOT_SUPPORTED, modbus_exception_code=3), ReadException(_NOT_SUPPORTED), False, False),
        # A timeout means "not supported" too; the setup goes on without these entities.
        (TimeoutError(), TimeoutError(), False, False),
        # Each probe stands on its own.
        (ReadException(_NOT_SUPPORTED, modbus_exception_code=3), 0, False, True),
        (rv.EmmaSystemState.ON_GRID, TimeoutError(), True, False),
        # A state this library does not know fails decoding: not offered, the setup goes on.
        (DecodeError("9 is not a valid EmmaSystemState"), 0, False, True),
    ],
)
async def test_emma_probes_status_registers(
    system_state: Any,  # noqa: ANN401
    alarm_counts: Any,  # noqa: ANN401
    *,
    expected_state: bool,
    expected_counts: bool,
) -> None:
    """Entities for these undocumented registers are only offered when the EMMA answers them."""
    device = await _create(_emma_client(system_state=system_state, alarm_counts=alarm_counts))

    assert device.supports_system_state is expected_state
    assert device.supports_active_alarm_counts is expected_counts


async def test_emma_probe_does_not_hide_a_dropped_connection() -> None:
    """A dropped connection still fails the setup, so the integration retries it."""
    client = _emma_client(system_state=ConnectionInterruptedException("lost"), alarm_counts=0)

    with pytest.raises(ConnectionInterruptedException):
        await _create(client)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1, rv.EmmaSystemState.ON_GRID),
        (2, rv.EmmaSystemState.OFF_GRID),
        (3, rv.EmmaSystemState.STANDBY_OR_EXCEPTION),
        (0xFFFF, None),
    ],
)
def test_emma_system_state_decoding(raw: int, expected: rv.EmmaSystemState | None) -> None:
    """Known values decode to the enum; the U16 invalid value decodes to None."""
    assert REGISTERS[rn.EMMA_SYSTEM_STATE].decode((raw,)).value == expected


def test_emma_system_state_unknown_value_fails() -> None:
    """The register is undocumented: a value this library does not know fails the read instead of being dropped."""
    with pytest.raises(DecodeError, match="not a valid EmmaSystemState"):
        REGISTERS[rn.EMMA_SYSTEM_STATE].decode((9,))
