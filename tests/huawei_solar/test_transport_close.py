"""The transport does not reopen a connection that was closed on request."""

import asyncio
from typing import Any

import pytest
from huawei_solar.modbus_client import TimeoutAwareSmartTransport
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_none
from tmodbus.exceptions import ModbusConnectionError
from tmodbus.transport.async_base import AsyncBaseTransport


class _FakeBaseTransport(AsyncBaseTransport):
    """In-memory connection that records opens, closes and requests."""

    def __init__(self) -> None:
        super().__init__()
        self.opened = False
        self.events: list[str] = []
        self.release_request = asyncio.Event()
        self.release_request.set()

    async def open(self) -> None:
        self.events.append("open")
        self.opened = True

    async def close(self) -> None:
        self.events.append("close")
        self.opened = False

    def is_open(self) -> bool:
        return self.opened

    async def send_and_receive(self, unit_id: int, pdu: Any) -> Any:  # noqa: ANN401, ARG002
        if not self.opened:
            msg = "Not connected."
            raise ModbusConnectionError(msg)
        self.events.append(f"request {pdu}")
        await self.release_request.wait()
        return pdu


def _transport(base: _FakeBaseTransport) -> TimeoutAwareSmartTransport:
    no_wait = AsyncRetrying(wait=wait_none(), stop=stop_after_attempt(3), reraise=True)
    return TimeoutAwareSmartTransport(
        base,
        auto_reconnect=AsyncRetrying(
            wait=wait_none(), stop=stop_after_attempt(2), retry=retry_if_exception_type(ModbusConnectionError)
        ),
        response_retry_strategy=no_wait.copy(retry=retry_if_exception_type(TimeoutError)),
    )


async def test_request_after_close_does_not_reconnect() -> None:
    """After close(), a request fails instead of opening a new connection."""
    base = _FakeBaseTransport()
    transport = _transport(base)
    await transport.open()
    assert await transport.send_and_receive(1, "a") == "a"

    await transport.close()

    with pytest.raises(ModbusConnectionError):
        await transport.send_and_receive(1, "b")
    assert base.events == ["open", "request a", "close"]
    assert not transport.is_open()


async def test_request_queued_during_close_does_not_reconnect() -> None:
    """A request waiting behind the one in flight while close() runs does not reopen the connection."""
    base = _FakeBaseTransport()
    transport = _transport(base)
    await transport.open()

    base.release_request.clear()
    first = asyncio.create_task(transport.send_and_receive(1, "first"))
    await asyncio.sleep(0)
    close = asyncio.create_task(transport.close())
    second = asyncio.create_task(transport.send_and_receive(1, "second"))
    await asyncio.sleep(0)
    base.release_request.set()

    assert await first == "first"
    await close
    with pytest.raises(ModbusConnectionError):
        await second
    assert base.events == ["open", "request first", "close"]


async def test_open_after_close_enables_requests_again() -> None:
    """An explicit open() (client.connect()) after close() works as before."""
    base = _FakeBaseTransport()
    transport = _transport(base)
    await transport.open()
    await transport.close()

    await transport.open()

    assert await transport.send_and_receive(1, "c") == "c"
    assert base.events == ["open", "close", "open", "request c"]


async def test_lost_connection_still_reconnects() -> None:
    """A connection lost without close() is still reopened by auto-reconnect."""
    base = _FakeBaseTransport()
    transport = _transport(base)
    await transport.open()
    base.opened = False  # dropped by the device

    assert await transport.send_and_receive(1, "d") == "d"
    assert base.events == ["open", "open", "request d"]


async def test_open_after_a_rejected_request_does_not_reconnect_again() -> None:
    """A request rejected after close() leaves no pending reconnect behind for the next open()."""
    base = _FakeBaseTransport()
    transport = _transport(base)
    await transport.open()

    base.release_request.clear()
    first = asyncio.create_task(transport.send_and_receive(1, "first"))
    await asyncio.sleep(0)
    close = asyncio.create_task(transport.close())
    queued = asyncio.create_task(transport.send_and_receive(1, "queued"))
    await asyncio.sleep(0)
    base.release_request.set()
    await first
    await close
    with pytest.raises(ModbusConnectionError):
        await queued

    await transport.open()
    assert await transport.send_and_receive(1, "after") == "after"
    assert base.events == ["open", "request first", "close", "open", "request after"]


async def test_request_queued_before_open_does_not_reconnect() -> None:
    """open() clears the closed state only once it holds the transport, after requests queued before it."""
    base = _FakeBaseTransport()
    transport = _transport(base)
    await transport.open()

    base.release_request.clear()
    first = asyncio.create_task(transport.send_and_receive(1, "first"))
    await asyncio.sleep(0)
    close = asyncio.create_task(transport.close())
    queued = asyncio.create_task(transport.send_and_receive(1, "queued"))
    reopen = asyncio.create_task(transport.open())
    await asyncio.sleep(0)
    base.release_request.set()

    await first
    await close
    with pytest.raises(ModbusConnectionError):
        await queued
    await reopen
    assert base.events == ["open", "request first", "close", "open"]
