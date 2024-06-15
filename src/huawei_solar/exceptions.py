"""Exceptions from the Huawei Solar library."""


class HuaweiSolarException(Exception):
    """Base class for Huawei Solar exceptions."""


class DecodeError(HuaweiSolarException):
    """Decoding failed."""


class EncodeError(HuaweiSolarException):
    """Encoding failed."""


class TimeOfUsePeriodsException(HuaweiSolarException):
    """Validation of TOU periods failed."""


class PeakPeriodsValidationError(Exception):
    """Validation of Peak Periods failed."""


class ConnectionException(HuaweiSolarException):
    """Exception connecting to device."""


class ReadException(HuaweiSolarException):
    """Exception reading register from device."""

    def __init__(self, *args, modbus_exception_code: int | None = None, **kwargs):
        """Create ReadException."""
        super().__init__(*args, **kwargs)
        self.modbus_exception_code = modbus_exception_code


class ConnectionInterruptedException(HuaweiSolarException):
    """Connection to the inverter was interrupted."""


class SlaveBusyException(HuaweiSolarException):
    """Non-fatal exception while trying to read from device."""


class SlaveFailureException(HuaweiSolarException):
    """Possibly fatal exception while trying to read from device."""


class WriteException(HuaweiSolarException):
    """Exception writing register to device."""

    def __init__(self, *args, modbus_exception_code: int | None = None, **kwargs):
        """Create WriteException."""
        super().__init__(*args, **kwargs)
        self.modbus_exception_code = modbus_exception_code


class PermissionDenied(HuaweiSolarException):
    """The inverter returned an error indicating that you don't have permission for this action."""


class InvalidCredentials(HuaweiSolarException):
    """Logging in on the inverter failed."""
