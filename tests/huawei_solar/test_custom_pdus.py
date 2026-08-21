"""Tests for custom Huawei Modbus PDUs."""

import struct
from unittest.mock import AsyncMock, patch

import huawei_solar.register_names as rn
from huawei_solar.device_discovery import get_device_logic_addresses
from huawei_solar.exceptions import ReadException
from huawei_solar.modbus_client import AsyncHuaweiSolarClient
from huawei_solar.modbus_pdu import (
    MultiDeviceRegisterReadPDU,
    MultiRegisterReadPDU,
    QueryDeviceLogicAddressListPDU,
)

from huawei_solar.device import SUN2000Device


def test_multi_register_read_pdu_encoding() -> None:
    """Test encoding of MultiRegisterReadPDU."""
    pdu = MultiRegisterReadPDU(registers=[(30000, 15), (32000, 1), (37200, 2)], frame_no=1)
    encoded = pdu.encode_request()

    expected_len = 3 * 3 + 2
    assert encoded[0] == 0x41
    assert encoded[1] == 0x33
    assert encoded[2] == expected_len
    assert encoded[3] == 1  # frame_no
    assert encoded[4] == 3  # count

    # First register: 30000 (0x7530), len: 15
    assert struct.unpack(">HB", encoded[5:8]) == (30000, 15)
    # Second register: 32000 (0x7D00), len: 1
    assert struct.unpack(">HB", encoded[8:11]) == (32000, 1)
    # Third register: 37200 (0x9150), len: 2
    assert struct.unpack(">HB", encoded[11:14]) == (37200, 2)


def test_multi_register_read_pdu_decoding() -> None:
    """Test decoding of MultiRegisterReadPDU response."""
    pdu = MultiRegisterReadPDU(registers=[(30070, 1), (32000, 1)])

    reg1_val = struct.pack(">H", 348)
    reg2_val = struct.pack(">H", 1)

    # Build response: 0x41 0x33 data_len frame_no count (reg_addr, reg_len, val)...
    content = bytes(
        [
            0,
            2,
            *struct.pack(">HB", 30070, 1),
            *reg1_val,
            *struct.pack(">HB", 32000, 1),
            *reg2_val,
        ],
    )
    response = bytes([0x41, 0x33, len(content), *content])

    decoded = pdu.decode_response(response)
    assert decoded == {
        30070: reg1_val,
        32000: reg2_val,
    }


def test_multi_device_register_read_pdu_encoding() -> None:
    """Test encoding of MultiDeviceRegisterReadPDU."""
    pdu = MultiDeviceRegisterReadPDU(
        items=[(1, 30000, 15), (2, 32000, 1)],
        frame_no=5,
    )
    encoded = pdu.encode_request()

    expected_len = 2 * 4 + 2
    assert encoded[0] == 0x41
    assert encoded[1] == 0x37
    assert encoded[2] == expected_len
    assert encoded[3] == 5  # frame_no
    assert encoded[4] == 2  # item count

    assert struct.unpack(">BHB", encoded[5:9]) == (1, 30000, 15)
    assert struct.unpack(">BHB", encoded[9:13]) == (2, 32000, 1)


def test_multi_device_register_read_pdu_decoding() -> None:
    """Test decoding of MultiDeviceRegisterReadPDU response."""
    pdu = MultiDeviceRegisterReadPDU(items=[(1, 30070, 1), (2, 32000, 1)])

    reg1_val = struct.pack(">H", 348)
    reg2_val = struct.pack(">H", 1)

    content = bytes(
        [
            0,
            2,
            *struct.pack(">BHB", 1, 30070, 1),
            *reg1_val,
            *struct.pack(">BHB", 2, 32000, 1),
            *reg2_val,
        ],
    )
    response = bytes([0x41, 0x37, len(content), *content])

    decoded = pdu.decode_response(response)
    assert decoded == {
        (1, 30070): reg1_val,
        (2, 32000): reg2_val,
    }


def test_query_device_logic_address_list_pdu_encoding_decoding() -> None:
    """Test encoding and decoding of QueryDeviceLogicAddressListPDU."""
    pdu = QueryDeviceLogicAddressListPDU()
    encoded = pdu.encode_request()
    assert encoded == bytes([0x41, 0x38, 0x01, 0x00])

    content = bytes([0x00, 0x03, 0x01, 0x02, 0x10])  # frame_no=0, count=3, addresses=[1, 2, 16]
    response = bytes([0x41, 0x38, len(content)]) + content

    decoded = pdu.decode_response(response)
    assert decoded == [1, 2, 16]


async def test_client_multi_register_read_convenience(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """Test multi_register_read on client."""
    mock_dict = {30070: struct.pack(">H", 348), 32000: struct.pack(">H", 1)}
    with patch.object(huawei_solar, "execute", AsyncMock(return_value=mock_dict)):
        res = await huawei_solar.multi_register_read([(30070, 1), (32000, 1)])
        assert res == mock_dict


async def test_client_get_multiple_scattered(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """Test get_multiple_scattered on client."""
    # MODEL_ID (30070, 1 word: 348), DEVICE_STATUS (32089, 1 word: 40960 / 'Standby: no irradiation')
    results = await huawei_solar.get_multiple_scattered([rn.MODEL_ID, rn.DEVICE_STATUS])
    assert len(results) == 2
    assert results[0].value == 348
    assert results[1].value == "Standby: no irradiation"

    dict_results = await huawei_solar.get_multiple_scattered_as_dict([rn.MODEL_ID, rn.DEVICE_STATUS])
    assert dict_results[rn.MODEL_ID].value == 348
    assert dict_results[rn.DEVICE_STATUS].value == "Standby: no irradiation"


async def test_client_multi_device_register_read(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """Test multi_device_register_read on client."""
    res = await huawei_solar.multi_device_register_read([(1, 30070, 1), (2, 32000, 1)])
    assert res == {
        (1, 30070): struct.pack(">H", 348),
        (2, 32000): struct.pack(">H", 1),
    }


async def test_client_query_device_logic_address_list(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """Test query_device_logic_address_list on client and discovery."""
    res = await huawei_solar.query_device_logic_address_list()
    assert res == [1, 2]

    discovery_res = await get_device_logic_addresses(huawei_solar)
    assert discovery_res == [1, 2]


async def test_device_batch_update_multi_register_success(sun2000_device: SUN2000Device) -> None:
    """Test batch_update_multi_register success path."""
    res = await sun2000_device.batch_update_multi_register([rn.MODEL_ID, rn.DEVICE_STATUS])
    assert res[rn.MODEL_ID].value == 348
    assert res[rn.DEVICE_STATUS].value == "Standby: no irradiation"


async def test_device_batch_update_hauwei_custom_alias(sun2000_device: SUN2000Device) -> None:
    """Test batch_update_hauwei_custom alias."""
    res = await sun2000_device.batch_update_hauwei_custom([rn.MODEL_ID, rn.DEVICE_STATUS])
    assert res[rn.MODEL_ID].value == 348


async def test_device_batch_update_multi_register_fallback(sun2000_device: SUN2000Device) -> None:
    """Test batch_update_multi_register fallback to standard batch_update and permanent disable on error."""
    assert sun2000_device.supports_custom_multi_register_read is True
    mock_custom = AsyncMock(side_effect=ReadException("Custom 0x41 0x33 not supported"))

    with patch.object(sun2000_device.client, "get_multiple_scattered_as_dict", mock_custom):
        res = await sun2000_device.batch_update_multi_register([rn.MODEL_ID, rn.DEVICE_STATUS])
        assert res[rn.MODEL_ID].value == 348
        assert res[rn.DEVICE_STATUS].value == "Standby: no irradiation"
        assert mock_custom.call_count == 1
        assert sun2000_device.supports_custom_multi_register_read is False

        # Subsequent call skips custom read
        res2 = await sun2000_device.batch_update_multi_register([rn.MODEL_ID])
        assert res2[rn.MODEL_ID].value == 348
        assert mock_custom.call_count == 1


async def test_multi_register_read_chunking(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """Test that multi_register_read splits large queries into multiple requests."""
    # 80 registers of length 2 words = each item request 3 bytes, response 7 bytes
    # 80 items would exceed 253 bytes response, requiring multiple chunks
    registers = [(30000 + i, 2) for i in range(80)]
    execute_calls: list[MultiRegisterReadPDU] = []

    async def mock_execute(pdu: MultiRegisterReadPDU) -> dict[int, bytes]:
        execute_calls.append(pdu)
        return {addr: b"\x00\x00\x00\x00" for addr, _ in pdu.registers}

    with patch.object(huawei_solar, "execute", side_effect=mock_execute):
        results = await huawei_solar.multi_register_read(registers)
        assert len(results) == 80
        assert len(execute_calls) > 1
        # Check frame_no increment
        assert execute_calls[0].frame_no == 0
        assert execute_calls[1].frame_no == 1


async def test_multi_device_register_read_chunking(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """Test that multi_device_register_read splits large queries into multiple requests."""
    items = [(1, 30000 + i, 2) for i in range(80)]
    execute_calls: list[MultiDeviceRegisterReadPDU] = []

    async def mock_execute(pdu: MultiDeviceRegisterReadPDU) -> dict[tuple[int, int], bytes]:
        execute_calls.append(pdu)
        return {(u, addr): b"\x00\x00\x00\x00" for u, addr, _ in pdu.items}

    with patch.object(huawei_solar, "execute", side_effect=mock_execute):
        results = await huawei_solar.multi_device_register_read(items, unit_id=huawei_solar.unit_id)
        assert len(results) == 80
        assert len(execute_calls) > 1
        assert execute_calls[0].frame_no == 0
        assert execute_calls[1].frame_no == 1


async def test_get_multiple_scattered_merges_consecutive_registers(huawei_solar: AsyncHuaweiSolarClient) -> None:
    """Test that consecutive registers are merged into a single span in the PDU."""
    # rn.MODEL_ID is 30070 (len 1, val 348), rn.NB_PV_STRINGS is 30071 (len 1, val 2)
    execute_calls: list[MultiRegisterReadPDU] = []
    orig_execute = huawei_solar.execute

    async def spy_execute(pdu: MultiRegisterReadPDU) -> dict[int, bytes]:
        execute_calls.append(pdu)
        return await orig_execute(pdu)

    with patch.object(huawei_solar, "execute", side_effect=spy_execute):
        results = await huawei_solar.get_multiple_scattered([rn.MODEL_ID, rn.NB_PV_STRINGS])
        assert len(results) == 2
        assert results[0].value == 348
        assert results[1].value == 2

        # Verify that execute was called with a single merged span (30070, 2) instead of 2 items
        assert len(execute_calls) == 1
        assert execute_calls[0].registers == [(30070, 2)]
