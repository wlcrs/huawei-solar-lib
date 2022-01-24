class HuaweiSolarException(Exception):
    """Base class for Huawei Solar exceptions."""


class DecodeError:
    """Decoding failed."""

class ConnectionException(HuaweiSolarException):
    """Exception connecting to device"""


class ReadException(HuaweiSolarException):
    """Exception reading register from device"""
