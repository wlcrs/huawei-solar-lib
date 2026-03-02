"""Number registers."""

from datetime import datetime
from enum import IntEnum
from inspect import isclass
from typing import Any

from huawei_solar.exceptions import DecodeError, WriteException

from .base import RegisterDefinition, Result, TargetDevice, UnitType


class NumberRegister[T](RegisterDefinition[T | None]):
    """Base class for number registers."""

    invalid_value: int | None
    length: int

    def __init__(
        self,
        unit: UnitType[Any],
        gain: int,
        register: int,
        *,
        writeable: bool = False,
        readable: bool = True,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ) -> None:
        """Initialize NumberRegister."""
        super().__init__(
            register,
            writeable=writeable,
            readable=readable,
            target_device=target_device,
        )
        self.unit = unit
        self.gain = gain

        if (callable(unit) or isinstance(unit, dict)) and gain != 1:
            msg = "Gain and unit are incompatible."
            raise ValueError(msg)

    def decode(self, values: tuple[Any, ...]) -> Result[T | None]:
        """Decode number register."""
        value = values[0]

        if self.invalid_value is not None and value == self.invalid_value:
            return Result(value=None, unit=None)

        if callable(self.unit):
            try:
                return Result(self.unit(value), None)
            except ValueError as err:
                msg = f"Failed to decode value of register {self.register}: {err}"
                raise DecodeError(msg) from err
        elif isinstance(self.unit, dict):
            try:
                return Result(self.unit[value], None)
            except KeyError as err:
                msg = f"Failed to decode value of register {self.register}: {err}"
                raise DecodeError(msg) from err

        if self.gain != 1:
            value /= self.gain
        return Result(value, self.unit)

    def encode(self, data: T | None) -> tuple[Any, ...]:
        """Encode number register."""
        if isinstance(data, int):
            int_data = data * self.gain
        elif isinstance(data, float):
            int_data = int(data * self.gain)  # it should always be an int!
        elif self.unit is bool:
            assert isinstance(data, bool)
            int_data = int(data)
            assert self.gain == 1
        elif isclass(self.unit) and issubclass(self.unit, IntEnum):
            assert isinstance(data, self.unit)
            int_data = int(data)
            assert self.gain == 1
        elif isclass(self.unit) and not isinstance(data, self.unit):
            msg = f"Expected data of type {self.unit}, but got {type(data)}"
            raise WriteException(
                msg,
            )
        elif data is None:
            if self.invalid_value is None:
                msg = "This register does not support writing None."
                raise WriteException(msg)
            int_data = self.invalid_value
        else:
            msg = f"Unsupported type: {type(data)}."
            raise WriteException(msg)

        return (int_data,)


class U16Register(NumberRegister[int]):
    """Unsigned 16-bit register."""

    format = "H"
    length = 1
    invalid_value: int | None = 2**16 - 1

    def __init__(  # noqa: PLR0913
        self,
        unit: UnitType[Any],
        gain: int,
        register: int,
        *,
        writeable: bool = False,
        readable: bool = True,
        ignore_invalid: bool = False,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ) -> None:
        """Create Unsigned 16-bit register."""
        super().__init__(
            unit=unit,
            gain=gain,
            register=register,
            writeable=writeable,
            readable=readable,
            target_device=target_device,
        )
        if ignore_invalid:
            self.invalid_value = None


class U32Register(NumberRegister[int]):
    """Unsigned 32-bit register."""

    format = "I"
    length = 2
    invalid_value = 2**32 - 1


class U64Register(NumberRegister[int]):
    """Unsigned 64-bit register."""

    format = "Q"
    length = 4
    invalid_value = 2**64 - 1


class I16Register(NumberRegister[int]):
    """Signed 16-bit register."""

    format = "h"
    length = 1
    invalid_value = 2**15 - 1


class I32Register(NumberRegister[int]):
    """Signed 32-bit register."""

    format = "i"
    length = 2
    invalid_value = 2**31 - 1


class I64Register(NumberRegister[int]):
    """Signed 64-bit register."""

    format = "q"
    length = 4
    invalid_value = 2**63 - 1


class I32AbsoluteValueRegister(I32Register):
    """Signed 32-bit register, converted into the equivalent absolute number.

    Use case: for registers of which the value should always be interpreted
     as a positive number, but are (in some cases) being reported as a
     negative number.

    cfr. https://github.com/wlcrs/huawei_solar/issues/54

    """

    def decode(self, values: tuple[Any, ...]) -> Result[int | None]:
        """Decode 32-bit signed integer into absolute value."""
        result = super().decode(values)

        return Result(abs(result.value), result.unit) if result.value is not None else result


class TimestampRegister(NumberRegister[datetime | None]):
    """Timestamp register."""

    format = U32Register.format
    length = U32Register.length
    invalid_value = U32Register.invalid_value

    def __init__(
        self,
        register: int,
        *,
        writeable: bool = False,
        readable: bool = True,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ) -> None:
        """Initialize TimestampRegister."""
        super().__init__(
            unit=None,
            gain=1,
            register=register,
            writeable=writeable,
            readable=readable,
            target_device=target_device,
        )

    def decode(self, values: tuple[Any, ...]) -> Result[datetime | None]:
        """Decode timestamp register."""
        value = values[0]

        timestamp_value = None
        if value != self.invalid_value:
            # I was unable to come up with a good way of determining in which time
            # zone this value is. So we return it without one.
            timestamp_value = datetime.fromtimestamp(value)  # noqa: DTZ006

        return Result(timestamp_value, None)
