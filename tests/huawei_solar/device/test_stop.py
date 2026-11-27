"""Tests for HuaweiSolarDevice.stop()."""

import asyncio
import contextlib
from typing import Any
from unittest.mock import patch

from huawei_solar.device.base import HuaweiSolarDevice, HuaweiSolarDeviceWithLogin

from huawei_solar import register_names as rn
from huawei_solar.device import base as device_base
from huawei_solar.register_definitions import Result


class _FakeClient:
    """Client whose reads take a while and that records the order of reads and the disconnect."""

    def __init__(self, read_delay: float = 0.05) -> None:
        self.read_delay = read_delay
        self.connected = True
        self.events: list[str] = []
        self.reads_while_disconnected = 0
        self.unit_id = 0
        self.lock: asyncio.Lock | None = None  # the update lock, to record whether disconnect() runs under it

    async def get_multiple_as_dict(self, names: list[rn.RegisterName]) -> dict[rn.RegisterName, Result[Any]]:
        self.events.append("read-start")
        if not self.connected:
            self.reads_while_disconnected += 1
        await asyncio.sleep(self.read_delay)
        self.events.append("read-end")
        return {name: Result(0, None) for name in names}

    async def disconnect(self) -> None:
        self.events.append("disconnect" if self.lock is None or self.lock.locked() else "disconnect-unlocked")
        self.connected = False


class _Device(HuaweiSolarDevice):
    async def _populate_additional_fields(self) -> None:
        pass

    @classmethod
    def supports_device(cls, model_name: str) -> bool:  # noqa: ARG003
        return True


class _LoginDevice(HuaweiSolarDeviceWithLogin):
    async def _populate_additional_fields(self) -> None:
        pass

    @classmethod
    def supports_device(cls, model_name: str) -> bool:  # noqa: ARG003
        return True


# Two registers far apart, so batch_update sends two requests while holding the update lock.
_TWO_BATCHES = [rn.MODEL_NAME, rn.STORAGE_STATE_OF_CAPACITY]


async def test_stop_waits_for_the_running_batch_update() -> None:
    """stop() on the primary device closes the connection only after the running batch_update is done."""
    client = _FakeClient()
    device = _Device(client, "test")  # type: ignore[arg-type]
    client.lock = device.update_lock

    update = asyncio.create_task(device.batch_update(_TWO_BATCHES))
    await asyncio.sleep(0.01)  # the first request is in flight
    assert device.update_lock.locked()

    assert await asyncio.wait_for(device.stop(), timeout=1)

    result = await update
    assert set(result) == set(_TWO_BATCHES)
    assert client.events == ["read-start", "read-end", "read-start", "read-end", "disconnect"]
    assert client.reads_while_disconnected == 0
    assert not device.update_lock.locked()


async def test_stop_without_running_update_disconnects_at_once() -> None:
    """With no update running, stop() closes the connection right away and leaves the lock free."""
    client = _FakeClient()
    device = _Device(client, "test")  # type: ignore[arg-type]

    assert await asyncio.wait_for(device.stop(), timeout=1)

    assert client.events == ["disconnect"]
    assert not device.update_lock.locked()


async def test_stop_disconnects_anyway_after_the_wait_timeout() -> None:
    """If the update lock is not released in time, stop() still closes the connection."""
    client = _FakeClient()
    device = _Device(client, "test")  # type: ignore[arg-type]

    await device.update_lock.acquire()  # e.g. a read that hangs
    with patch.object(device_base, "STOP_WAIT_FOR_UPDATE_TIMEOUT", 0.05):
        assert await asyncio.wait_for(device.stop(), timeout=1)

    assert client.events == ["disconnect"]
    assert device.update_lock.locked()  # stop() does not release a lock it does not hold
    device.update_lock.release()


async def test_sub_device_stop_neither_waits_nor_disconnects() -> None:
    """A sub-device shares the primary device's connection: its stop() leaves the connection and the lock alone."""
    client = _FakeClient()
    primary = _Device(client, "primary")  # type: ignore[arg-type]
    sub_device = _Device(client, "sub", primary_device=primary)  # type: ignore[arg-type]
    assert sub_device.update_lock is primary.update_lock

    await primary.update_lock.acquire()  # the primary device is busy
    try:
        assert await asyncio.wait_for(sub_device.stop(), timeout=1)
    finally:
        primary.update_lock.release()

    assert client.events == []


async def test_stop_of_sub_devices_then_primary_like_the_integration_unload() -> None:
    """The integration stops the sub-devices first, then the primary device, while an update may be running."""
    client = _FakeClient()
    primary = _Device(client, "primary")  # type: ignore[arg-type]
    sub_device = _Device(client, "sub", primary_device=primary)  # type: ignore[arg-type]

    update = asyncio.create_task(sub_device.batch_update(_TWO_BATCHES))
    await asyncio.sleep(0.01)

    for device in (sub_device, primary):
        assert await asyncio.wait_for(device.stop(), timeout=1)

    await update
    assert client.events[-1] == "disconnect"
    assert client.reads_while_disconnected == 0


async def test_login_device_stop_stops_the_heartbeat_and_waits() -> None:
    """The login subclass stops its heartbeat, then waits for the running update like the base class."""
    client = _FakeClient()
    device = _LoginDevice(client, "test")  # type: ignore[arg-type]
    client.lock = device.update_lock

    update = asyncio.create_task(device.batch_update(_TWO_BATCHES))
    await asyncio.sleep(0.01)

    original_stop_heartbeat = device.stop_heartbeat

    def stop_heartbeat() -> None:
        client.events.append("stop-heartbeat")
        original_stop_heartbeat()

    with patch.object(device, "stop_heartbeat", stop_heartbeat):
        assert await asyncio.wait_for(device.stop(), timeout=1)

    await update
    assert client.events == ["read-start", "stop-heartbeat", "read-end", "read-start", "read-end", "disconnect"]


async def test_cancelled_stop_still_disconnects() -> None:
    """If stop() is cancelled while it waits for the running update, the connection is still closed."""
    client = _FakeClient(read_delay=0.2)
    device = _Device(client, "test")  # type: ignore[arg-type]

    update = asyncio.create_task(device.batch_update(_TWO_BATCHES))
    await asyncio.sleep(0.01)
    stop = asyncio.create_task(device.stop())
    await asyncio.sleep(0.01)
    stop.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await stop

    assert "disconnect" in client.events or "disconnect-unlocked" in client.events
    update.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await update


async def test_stop_cancelled_during_disconnect_still_closes() -> None:
    """Cancelling stop() while it disconnects does not abort the disconnect."""
    client = _FakeClient()
    device = _Device(client, "test")  # type: ignore[arg-type]
    closing = asyncio.Event()
    finish_close = asyncio.Event()

    async def slow_disconnect() -> None:
        closing.set()
        await finish_close.wait()
        client.events.append("disconnect")

    client.disconnect = slow_disconnect  # type: ignore[method-assign]
    stop = asyncio.create_task(device.stop())
    await closing.wait()
    stop.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await stop
    finish_close.set()
    await asyncio.sleep(0)

    assert client.events == ["disconnect"]
