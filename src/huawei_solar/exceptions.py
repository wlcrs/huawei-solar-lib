"""Exceptions from the Huawei Solar library."""


class HuaweiSolarException(Exception):
    """Base class for Huawei Solar exceptions."""


class DecodeError(HuaweiSolarException):
    """Decoding failed."""


class ConnectionException(HuaweiSolarException):
    """Exception connecting to device"""


class ReadException(HuaweiSolarException):
    """Exception reading register from device"""


class SlaveBusyException(HuaweiSolarException):
    """Non-fatal exception while trying to read from device."""


class WriteException(HuaweiSolarException):
    """Exception writing register to device"""


class PermissionDenied(HuaweiSolarException):
    """The inverter returned an error indicating that you don't have permission for this action."""


class InvalidCredentials(HuaweiSolarException):
    """Logging in on the inverter failed"""
