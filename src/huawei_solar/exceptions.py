"""Exceptions from the Huawei Solar library."""


class HuaweiSolarException(Exception):  # pylint: disable=too-few-public-methods
    """Base class for Huawei Solar exceptions."""


class DecodeError(HuaweiSolarException):  # pylint: disable=too-few-public-methods
    """Decoding failed."""


class ConnectionException(
    HuaweiSolarException
):  # pylint: disable=too-few-public-methods
    """Exception connecting to device"""


class ReadException(HuaweiSolarException):  # pylint: disable=too-few-public-methods
    """Exception reading register from device"""
