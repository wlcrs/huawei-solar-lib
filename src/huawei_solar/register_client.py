"""A Modbus client that knows about registers as defined in this library."""

import logging
import struct
from typing import TYPE_CHECKING, Any

from tmodbus.client import AsyncModbusClient
from tmodbus.exceptions import IllegalDataAddressError, ModbusConnectionError, ModbusResponseError, TModbusError

from huawei_solar import register_names as rn
from huawei_solar.const import MAX_BATCHED_REGISTERS_COUNT
from huawei_solar.exceptions import (
    ConnectionInterruptedException,
    ReadException,
    WriteException,
)
from huawei_solar.modbus_pdu import PermissionDeniedError
from huawei_solar.registers import REGISTERS

if TYPE_CHECKING:
    from huawei_solar.register_definitions import RegisterDefinition, Result


LOGGER = logging.getLogger(__name__)


class RegisterAwareModbusClient(AsyncModbusClient):
    """A Modbus client that knows about registers."""

    def _get_register_definitions(self, names: list[rn.RegisterName]) -> "list[RegisterDefinition[Any]]":
        """Get register definitions by name."""
        unknown_register_names = set(names) - REGISTERS.keys()
        if unknown_register_names:
            msg = f"Did not recognize register names: {', '.join(unknown_register_names)}"
            raise ValueError(msg)

        return [REGISTERS[name] for name in names]

    def _validate_registers_readable(
        self,
        names: list[rn.RegisterName],
        registers: "list[RegisterDefinition[Any]]",
    ) -> None:
        """Validate whether the requested registers are readable."""
        unreadable_register_names = [
            register_name for register, register_name in zip(registers, names, strict=False) if not register.readable
        ]
        if unreadable_register_names:
            msg = f"Trying to read unreadable registers: {', '.join(unreadable_register_names)}"
            raise ValueError(msg)

    def _construct_struct_format(self, registers: "list[RegisterDefinition[Any]]") -> str:
        """Construct a struct format to interpret the registers content with."""
        struct_format = f">{registers[0].format}"
        for idx in range(1, len(registers)):
            register_distance = registers[idx].register - (registers[idx - 1].register + registers[idx - 1].length)
            if register_distance < 0:
                msg = (
                    f"Requested registers must be in monotonically increasing order, "
                    f"but {registers[idx - 1].register} + {registers[idx - 1].length} > {registers[idx].register}!"
                )
                raise ValueError(msg)

            if register_distance > MAX_BATCHED_REGISTERS_COUNT:
                msg = "Gap between requested registers is too large. Split it in two requests"
                raise ValueError(msg)

            struct_format += f"{'x' * 2 * register_distance}{registers[idx].format}"

        return struct_format

    def _decode_response_tuple(
        self,
        registers: "list[RegisterDefinition[Any]]",
        response: tuple[Any, ...],
    ) -> "list[Result[Any]]":
        """Decode response tuple."""
        result = []
        tuple_idx = 0
        for register in registers:
            register_values = register.decode(response[tuple_idx : tuple_idx + register.format_size])
            result.append(register_values)
            tuple_idx += register.format_size

        return result

    async def get_multiple(self, names: list[rn.RegisterName]) -> "list[Result[Any]]":
        """Read multiple registers at the same time.

        This is only possible if the registers are consecutively available in the
        inverters' memory.
        """
        if len(names) == 0:
            msg = "Expected at least one register name"
            raise ValueError(msg)

        registers = self._get_register_definitions(names)
        self._validate_registers_readable(names, registers)

        start_address = registers[0].register
        struct_format = self._construct_struct_format(registers)
        try:
            response_tuple = await self.read_struct_format(start_address, format_struct=struct_format)
        except ModbusResponseError as err:
            msg = f"Failed to read registers {', '.join(names)}: received {type(err).__name__}"
            raise ReadException(msg, modbus_exception_code=err.error_code) from err
        except ModbusConnectionError as err:
            LOGGER.exception("Connection error while reading registers %s", names)
            msg = f"Connection failed when trying to read registers {', '.join(names)}"
            raise ConnectionInterruptedException(msg) from err
        except TModbusError as err:
            msg = f"Failed to read registers {', '.join(names)}: {err}"
            raise ReadException(msg) from err
        else:
            return self._decode_response_tuple(registers, response_tuple)

    async def get_multiple_as_dict(self, names: list[rn.RegisterName]) -> "dict[rn.RegisterName, Result[Any]]":
        """Read multiple registers and return them as a dictionary.

        This is only possible if the registers are consecutively available in the
        inverters' memory.
        """
        return dict(
            zip(
                names,
                await self.get_multiple(names),
                strict=True,
            ),
        )

    async def get(self, name: rn.RegisterName) -> "Result[Any]":
        """Get named register from device."""
        return (await self.get_multiple([name]))[0]

    async def set(
        self,
        name: rn.RegisterName,
        value: Any,  # noqa: ANN401
    ) -> bool:
        """Set named register on device."""
        try:
            reg = REGISTERS[name]
        except KeyError as err:
            msg = "Invalid Register Name"
            raise ValueError(msg) from err

        if not reg.writeable:
            msg = "Register is not writable"
            raise WriteException(msg)

        return await self._write_registers(reg, reg.encode(value))

    def _validate_data_to_write(self, register: "RegisterDefinition[Any]", values: tuple[Any, ...]) -> None:
        """Validate if the data to write is valid."""
        encoded_value_to_write = struct.pack(f">{register.format}", *values)
        if len(encoded_value_to_write) != register.length * 2:  # 2 bytes per register
            msg = "Wrong number of registers to write"
            raise WriteException(msg)

    async def _write_registers(
        self,
        register: "RegisterDefinition[Any]",
        values: tuple[Any, ...],
    ) -> bool:
        """Async write register to device."""
        self._validate_data_to_write(register, values)
        try:
            if register.length == 1:
                LOGGER.debug(
                    "Writing to %d: single value '%s' on server %d",
                    register.register,
                    values[0],
                    self.unit_id,
                )

                response = await self.write_single_register(register.register, values[0])

                success: bool = response == values[0]
            else:
                LOGGER.debug(
                    "Writing to %d: values '%s' on server %d",
                    register.register,
                    values,
                    self.unit_id,
                )

                registers_written = await self.write_struct_format(
                    register.register,
                    values,
                    format_struct=f">{register.format}",
                )

                success = registers_written == register.length

        except PermissionDeniedError:
            raise
        except IllegalDataAddressError as e:
            msg = (
                f"Failed to write value {values} to register {register} due to IllegalDataAddress. "
                "Assuming permission problem."
            )
            raise PermissionDeniedError(PermissionDeniedError.error_code, e.function_code) from e
        except ModbusResponseError as e:
            msg = f"Failed to write value {values} to register {register}: {e.error_code:02x}"
            raise WriteException(msg, modbus_exception_code=e.error_code) from e
        except ModbusConnectionError as err:
            LOGGER.exception("Connection error while writing to register %s", register)
            raise ConnectionInterruptedException(err) from err
        return success
