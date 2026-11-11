"""Tests for IPv4Register."""

from ipaddress import IPv4Address

import pytest
from huawei_solar.exceptions import WriteException

from huawei_solar.register_definitions import IPv4Register


def test_ipv4_register_decode() -> None:
    """Test decoding 32-bit big-endian integer into IPv4Address."""
    reg = IPv4Register(40012)

    # 192.168.1.100 -> 3232235876
    result = reg.decode((3232235876,))
    assert result.value == IPv4Address("192.168.1.100")
    assert str(result.value) == "192.168.1.100"
    assert result.unit is None

    # Subnet mask: 255.255.255.0 -> 4294967040
    result_mask = reg.decode((4294967040,))
    assert result_mask.value == IPv4Address("255.255.255.0")
    assert str(result_mask.value) == "255.255.255.0"

    # Invalid value: 2**32 - 1 -> None
    assert reg.decode((2**32 - 1,)).value is None


def test_ipv4_register_encode() -> None:
    """Test encoding IPv4Address or str into 32-bit integer."""
    reg = IPv4Register(40012, writeable=True)

    # From string
    assert reg.encode("192.168.1.100") == (3232235876,)
    assert reg.encode("255.255.255.0") == (4294967040,)

    # From IPv4Address object
    assert reg.encode(IPv4Address("192.168.1.100")) == (3232235876,)

    # None
    assert reg.encode(None) == (2**32 - 1,)

    # Invalid type
    with pytest.raises(WriteException, match="Expected IPv4Address"):
        reg.encode(12345)  # type: ignore[arg-type]
