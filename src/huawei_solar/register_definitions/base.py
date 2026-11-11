"""Base for Register implementations."""

import struct
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from enum import Flag, auto
from typing import Any, TypeVar, cast

from huawei_solar.exceptions import DecodeError

T = TypeVar("T")

UnitType = None | str | dict[Any, T] | Callable[..., T]


class TargetDevice(Flag):
    """Target device for a register."""

    SUN2000 = auto()
    EMMA = auto()
    SCHARGER = auto()
    SDONGLE = auto()
    SMARTLOGGER = auto()
    SMART_AC_GUN = auto()


@dataclass(frozen=True, slots=True)
class Result[T]:
    """Modbus register value."""

    value: T
    unit: str | None


class RegisterDefinition[T](ABC):
    """Base class for register definitions."""

    format: str
    format_size: int = 1
    """Number of values returned by the struct format."""
    length: int

    unit: UnitType[T] = None

    def __init__(
        self,
        register: int,
        *,
        writeable: bool = False,
        readable: bool = True,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ) -> None:
        """Create RegisterDefinition."""
        self.register = register
        self.writeable = writeable
        self.readable = readable
        self.target_device = target_device

    def __post_init__(self) -> None:
        """Validate register configuration."""
        assert struct.calcsize(f">{self.format}") == self.length * 2

    def encode(self, data: T) -> tuple[Any, ...]:
        """Encode register to bytes."""
        assert self.format_size == 1
        return (data,)

    def decode(self, values: tuple[Any, ...]) -> Result[T]:
        """Decode register to value."""
        assert self.format_size == len(values) == 1

        value = cast("T", values[0])

        if callable(self.unit):
            try:
                return Result(self.unit(value), None)
            except Exception as e:
                msg = f"Failed to decode value of register {self.register}: {e}"
                raise DecodeError(msg) from e
        if isinstance(self.unit, dict):
            try:
                return Result(self.unit[value], None)
            except KeyError as e:
                msg = f"Failed to decode value of register {self.register}: {e}"
                raise DecodeError(msg) from e
        return Result(value, self.unit)

    def _validate(self, data: T) -> None:
        """Validate data type."""
        raise NotImplementedError
