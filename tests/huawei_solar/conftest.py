"""Pytest configuration and fixtures for huawei-solar tests."""

import struct

import pytest
from huawei_solar.modbus_client import AsyncHuaweiSolarClient
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

    async def send_and_receive(self, unit_id: int, pdu: BaseClientPDU[RT]) -> RT:  # noqa: ARG002
        """Mock send and receive."""
        if isinstance(pdu, RawReadHoldingRegistersPDU):
            key = (pdu.start_address, pdu.quantity)
            if mock_register := MOCK_REGISTERS.get(key):
                return struct.pack(f">{'H' * pdu.quantity}", *mock_register)  # type: ignore[return-value]
            msg = f"MockTransport: No mock data for {key}"
            raise ValueError(msg)
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

    sun2000_device.battery_1_type = StorageProductModel.HUAWEI_LUNA2000

    return sun2000_device
