"""Tests for TimestampRegister."""

from datetime import UTC, datetime

from huawei_solar.register_definitions.number import TimestampRegister


def test_timestamp_register_decode() -> None:
    """Test decoding a valid timestamp into a UTC datetime."""
    reg = TimestampRegister(40000)

    # 1700000000 -> 2023-11-14 22:13:20 UTC
    result = reg.decode((1700000000,))
    assert result.value == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert result.value.tzinfo == UTC
    assert result.unit is None


def test_timestamp_register_decode_invalid() -> None:
    """Test decoding an invalid timestamp returns None."""
    reg = TimestampRegister(40000)

    # Invalid value is U32 max (0xFFFFFFFF = 4294967295)
    result = reg.decode((reg.invalid_value,))
    assert result.value is None
