"""Tests for HuaweiSolarDevice.read_file: waiting for a file that is not ready, or a busy device, outside the lock."""

import asyncio
import struct
from typing import cast
from unittest.mock import AsyncMock

import pytest
from huawei_solar.exceptions import FileNotReadyError, ReadException
from huawei_solar.files import ActiveAlarmsDataFile
from huawei_solar.modbus_client import (
    FILE_BUSY_RETRY_INTERVAL,
    FILE_PREPARE_RETRY_INTERVAL,
    FILE_READ_RETRIES,
)
from huawei_solar.modbus_pdu import PermissionDeniedError

from huawei_solar import AsyncHuaweiSolarClient
from huawei_solar.device import EMMADevice, HuaweiSolarDevice, SUN2000Device

RECORD = struct.pack(ActiveAlarmsDataFile.RECORD_STRUCT, 1, 3, 4006, 1794712200, 0, 0x0001, b"\x00\x02")


def _client(unit_id: int) -> AsyncMock:
    client = AsyncMock(spec=AsyncHuaweiSolarClient)
    client.unit_id = unit_id
    # register reads (the EMMA's time registers) are not supported here
    client.get.side_effect = ReadException("not supported", modbus_exception_code=0x02)
    return client


def _get_file(device: HuaweiSolarDevice) -> AsyncMock:
    return cast("AsyncMock", device.client.get_file)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record the delays asked for instead of waiting."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


@pytest.fixture
def emma_tree() -> tuple[EMMADevice, SUN2000Device]:
    """Return an EMMA on unit 0 and an inverter behind it on unit 3; they share the update lock."""
    emma = EMMADevice(client=_client(0), model_name="SmartHEMS")
    inverter = SUN2000Device(client=_client(3), model_name="SUN2000-12K-MAP0", primary_device=emma)
    return emma, inverter


def _answers(device: HuaweiSolarDevice, *answers: bytes | Exception) -> list[bool]:
    """Answer get_file with `answers` in turn; return whether the update lock was held at each call."""
    lock_held: list[bool] = []
    remaining = list(answers)

    async def get_file(_file_type: int, _customized_data: bytes | None = None) -> bytes:
        lock_held.append(device.update_lock.locked())
        answer = remaining.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    _get_file(device).side_effect = get_file
    return lock_held


def test_default_retries_suit_periodic_polling() -> None:
    assert FILE_READ_RETRIES == 1
    assert FILE_PREPARE_RETRY_INTERVAL == 3
    assert FILE_BUSY_RETRY_INTERVAL == 10


async def test_file_not_ready_is_asked_again_without_holding_the_lock(
    emma_tree: tuple[EMMADevice, SUN2000Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emma, inverter = emma_tree
    lock_held_while_waiting: list[bool] = []

    async def fake_sleep(delay: float) -> None:
        assert delay == FILE_PREPARE_RETRY_INTERVAL
        lock_held_while_waiting.append(emma.update_lock.locked())

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    lock_held = _answers(emma, FileNotReadyError("preparing", progress=10), RECORD)

    (alarm,) = await asyncio.wait_for(inverter.get_active_alarms(), timeout=2)

    assert alarm.alarm_id == 4006
    assert lock_held == [True, True]
    assert lock_held_while_waiting == [False]
    assert not emma.update_lock.locked()


async def test_file_not_ready_after_all_retries_raises(
    emma_tree: tuple[EMMADevice, SUN2000Device], sleeps: list[float]
) -> None:
    emma, inverter = emma_tree
    _answers(emma, *[FileNotReadyError("preparing", progress=50)] * 4)

    with pytest.raises(FileNotReadyError) as err:
        await inverter.get_active_alarms(retries=3)

    assert err.value.progress == 50
    assert _get_file(emma).await_count == 4
    assert sleeps == [FILE_PREPARE_RETRY_INTERVAL] * 3


async def test_no_retry_when_retries_is_zero(emma_tree: tuple[EMMADevice, SUN2000Device], sleeps: list[float]) -> None:
    emma, _ = emma_tree
    _answers(emma, FileNotReadyError("preparing", progress=0))

    with pytest.raises(FileNotReadyError):
        await emma.read_file(0xA1, b"\xe0\x02\xff\x00", retries=0)

    assert sleeps == []


@pytest.mark.parametrize("code", [0x06, 0xB0])
async def test_busy_device_is_asked_again_after_10_s(
    emma_tree: tuple[EMMADevice, SUN2000Device], sleeps: list[float], code: int
) -> None:
    emma, _ = emma_tree
    _answers(emma, ReadException("busy", modbus_exception_code=code), RECORD)

    assert await emma.read_file(0xA1) == RECORD
    assert sleeps == [FILE_BUSY_RETRY_INTERVAL]


async def test_busy_after_all_retries_raises(emma_tree: tuple[EMMADevice, SUN2000Device], sleeps: list[float]) -> None:
    emma, _ = emma_tree
    _answers(emma, *[ReadException("busy", modbus_exception_code=0xB0)] * 2)

    with pytest.raises(ReadException) as err:
        await emma.read_file(0xA1)

    assert err.value.modbus_exception_code == 0xB0
    assert sleeps == [FILE_BUSY_RETRY_INTERVAL]


async def test_other_errors_are_not_retried(emma_tree: tuple[EMMADevice, SUN2000Device], sleeps: list[float]) -> None:
    emma, _ = emma_tree
    _answers(emma, ReadException("illegal data address", modbus_exception_code=0x02))

    with pytest.raises(ReadException):
        await emma.read_file(0xA1, retries=5)

    assert sleeps == []
    assert _get_file(emma).await_count == 1


async def test_permission_denied_logs_in_again_and_retries() -> None:
    """get_file passes "permission denied" on as PermissionDeniedError: log in again and read once more."""
    inverter = SUN2000Device(client=_client(1), model_name="SUN2000-12K-MAP0")
    inverter._HuaweiSolarDeviceWithLogin__username = "installer"  # type: ignore[attr-defined]
    inverter._HuaweiSolarDeviceWithLogin__password = "secret"  # type: ignore[attr-defined]  # noqa: S105
    login = cast("AsyncMock", inverter.client.login)
    login.return_value = True
    _answers(inverter, PermissionDeniedError(0x41), RECORD)

    try:
        assert await inverter.read_file(0xA1) == RECORD
    finally:
        inverter.stop_heartbeat()

    login.assert_awaited()
    assert _get_file(inverter).await_count == 2
