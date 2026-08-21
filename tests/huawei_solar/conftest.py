"""Pytest configuration and fixtures for huawei-solar tests."""

import struct

import pytest
from huawei_solar.modbus_client import AsyncHuaweiSolarClient
from huawei_solar.modbus_pdu import (
    MultiDeviceRegisterReadPDU,
    MultiRegisterReadPDU,
    QueryDeviceLogicAddressListPDU,
)
from huawei_solar.register_values import StorageProductModel
from tmodbus.pdu.base import RT, BaseClientPDU
from tmodbus.pdu.holding_registers import RawReadHoldingRegistersPDU
from tmodbus.transport.async_base import AsyncBaseTransport

from huawei_solar.device import SUN2000Device

MOCK_REGISTERS = {
    (30000, 25): [
        21333,
        20018,
        12336,
        12333,
        13131,
        21580,
        11596,
        12544,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        18518,
        13104,
        12849,
        13874,
        12592,
        14389,
        0,
        0,
        0,
        0,
    ],
    (30000, 15): [
        21333,
        20018,
        12336,
        12333,
        13131,
        21580,
        11596,
        12544,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ],
    (30015, 10): [18518, 13104, 12849, 13874, 12592, 14389, 0, 0, 0, 0],
    (30070, 1): [348],
    (30071, 1): [2],
    (30072, 1): [2],
    (30073, 2): [0, 3000],
    (30075, 2): [0, 3300],
    (30077, 2): [0, 3300],
    (30079, 2): [0, 1980],
    (30081, 2): [65535, 63556],
    (32000, 1): [1],
    (32002, 1): [0],
    (32003, 2): [0, 0],
    (32008, 1): [257],
    (32009, 1): [514],
    (32010, 1): [27],
    (32016, 1): [0],
    (32017, 1): [0],
    (32018, 1): [0],
    (32019, 1): [0],
    (32020, 1): [0],
    (32021, 1): [0],
    (32022, 1): [0],
    (32023, 1): [0],
    (32064, 5): [0, 0, 0, 0, 0],
    (32064, 2): [0, 0],
    (32066, 1): [0],
    (32067, 1): [0],
    (32068, 1): [0],
    (32069, 1): [0],
    (32070, 1): [0],
    (32071, 1): [0],
    (32072, 2): [0, 0],
    (32074, 2): [0, 0],
    (32076, 2): [0, 0],
    (32078, 2): [0, 225],
    (32080, 2): [0, 0],
    (32082, 2): [0, 0],
    (32084, 1): [0],
    (32085, 1): [0],
    (32086, 1): [0],
    (32087, 1): [0],
    (32088, 1): [3000],
    (32089, 1): [40960],
    (32090, 1): [0],
    (32091, 2): [25069, 6645],
    (32093, 2): [25069, 35661],
    (32106, 2): [0, 20734],
    (32114, 2): [0, 65],
    (37200, 1): [10],
    (37201, 1): [0],
    (40000, 2): [25069, 53611],
    (42000, 1): [18],
    (43006, 1): [60],
}


class MockTransport(AsyncBaseTransport):
    """Mock transport for testing."""

    async def open(self) -> None:
        """Mock open transport."""
        return

    async def close(self) -> None:
        """Mock close transport."""
        return

    def is_open(self) -> bool:
        """Mock is transport open."""
        return True

    def _resolve_mock_bytes(self, reg_addr: int, reg_len: int) -> bytes:
        if mock_reg := MOCK_REGISTERS.get((reg_addr, reg_len)):
            return struct.pack(f">{'H' * reg_len}", *mock_reg)
        # Reconstruct from contiguous sub-ranges in MOCK_REGISTERS
        words: list[int] = []
        curr = reg_addr
        while curr < reg_addr + reg_len:
            found = False
            for (m_addr, m_len), m_vals in MOCK_REGISTERS.items():
                if m_addr <= curr < m_addr + m_len:
                    offset = curr - m_addr
                    remaining = (reg_addr + reg_len) - curr
                    take = min(m_len - offset, remaining)
                    words.extend(m_vals[offset : offset + take])
                    curr += take
                    found = True
                    break
            if not found:
                msg = f"MockTransport: No mock data for ({reg_addr}, {reg_len})"
                raise ValueError(msg)
        return struct.pack(f">{'H' * reg_len}", *words)

    async def send_and_receive(self, unit_id: int, pdu: BaseClientPDU[RT]) -> RT:  # noqa: ARG002
        """Mock send and receive."""
        if isinstance(pdu, RawReadHoldingRegistersPDU):
            return self._resolve_mock_bytes(pdu.start_address, pdu.quantity)  # type: ignore[return-value]
        if isinstance(pdu, MultiRegisterReadPDU):
            result_dict: dict[int, bytes] = {}
            for reg_addr, reg_len in pdu.registers:
                result_dict[reg_addr] = self._resolve_mock_bytes(reg_addr, reg_len)
            return result_dict  # type: ignore[return-value]
        if isinstance(pdu, MultiDeviceRegisterReadPDU):
            result_dev_dict: dict[tuple[int, int], bytes] = {}
            for u_id, reg_addr, reg_len in pdu.items:
                result_dev_dict[(u_id, reg_addr)] = self._resolve_mock_bytes(reg_addr, reg_len)
            return result_dev_dict  # type: ignore[return-value]
        if isinstance(pdu, QueryDeviceLogicAddressListPDU):
            return [1, 2]  # type: ignore[return-value]
        msg = f"MockTransport: Unsupported PDU type {type(pdu)}"
        raise ValueError(msg)


@pytest.fixture
def huawei_solar() -> AsyncHuaweiSolarClient:
    """Create a mock AsyncHuaweiSolarClient for testing."""
    return AsyncHuaweiSolarClient(transport=MockTransport(), unit_id=1)


@pytest.fixture
def sun2000_device(huawei_solar: AsyncHuaweiSolarClient) -> SUN2000Device:
    """Create a mock SUN2000Device for testing."""
    sun2000_device = SUN2000Device(
        client=huawei_solar,
        model_name="SUN2000-9KTL-123",
        primary_device=None,
    )

    sun2000_device._time_zone = 60
    sun2000_device.battery_1_type = StorageProductModel.HUAWEI_LUNA2000

    return sun2000_device
