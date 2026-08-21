"""Base for classes that represent a single Huawei Solar device."""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, Self

from huawei_solar import register_names as rn
from huawei_solar.const import MAX_BATCHED_REGISTERS_COUNT, MAX_BATCHED_REGISTERS_GAP
from huawei_solar.exceptions import (
    HuaweiSolarException,
    InvalidCredentials,
    ReadException,
    WriteException,
)
from huawei_solar.files import (
    ActiveAlarm,
    ActiveAlarmsDataFile,
    HistoryAlarm,
    HistoryAlarmsDataFile,
)
from huawei_solar.modbus_pdu import PermissionDeniedError
from huawei_solar.registers import REGISTERS

if TYPE_CHECKING:
    from huawei_solar.modbus_client import AsyncHuaweiSolarClient
    from huawei_solar.register_definitions import Result

_LOGGER = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15


WRITE_TEST_REGISTER = rn.TIME_ZONE


class HuaweiSolarDevice(ABC):
    """A higher-level interface making it easier to interact with a Huawei Solar inverter."""

    model_name: str
    serial_number: str
    update_lock: asyncio.Lock
    primary_device: "HuaweiSolarDevice | None" = None

    def __init__(
        self,
        client: "AsyncHuaweiSolarClient",
        model_name: str,
        *,
        primary_device: "HuaweiSolarDevice | None" = None,
    ) -> None:
        """DO NOT USE THIS CONSTRUCTOR DIRECTLY. Use create() method instead."""
        self.client = client
        self.model_name = model_name
        self.update_lock = primary_device.update_lock if primary_device else asyncio.Lock()
        self.primary_device = primary_device

    @classmethod
    async def create(
        cls,
        client: "AsyncHuaweiSolarClient",
        *,
        model_name: str,
        primary_device: "HuaweiSolarDevice | None" = None,
    ) -> Self:
        """Create instance with the necessary information."""
        device = cls(
            client,
            model_name,
            primary_device=primary_device,
        )

        await device._populate_additional_fields()

        return device

    @abstractmethod
    async def _populate_additional_fields(self) -> None:
        """Allow subclass to populate additional fields with information."""

    @classmethod
    @abstractmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""

    def _handle_batch_read_error(
        self,
        _queried_register_names: list[rn.RegisterName],
        exc: HuaweiSolarException,
    ) -> None:
        """Handle read errors in get."""
        raise exc

    def _detect_state_changes(self, new_values: "dict[rn.RegisterName, Result[Any]]") -> None:  # noqa: B027
        """Update state based on result of batch_update query.

        Used by subclasses to detect important changes.
        """

    async def _filter_registers(self, register_names: list[rn.RegisterName]) -> list[rn.RegisterName]:
        """Filter registers being requested in batch_update.

        Used by subclasses to prevent read-errors in certain cases.
        """
        return register_names

    async def batch_update(self, register_names: list[rn.RegisterName]) -> "dict[rn.RegisterName, Result[Any]]":
        """Efficiently retrieve the values of all the registers passed in register_names.

        This method adds intelligence on top of read_multiple to only batch together
        registers that are close together in the inverter's memory map.
        """
        if unknown_registers := {register_name for register_name in register_names if register_name not in REGISTERS}:
            _LOGGER.warning(
                "Unknown register name passed to batch_update: %s",
                ", ".join(str(rn) for rn in unknown_registers),
            )

        class _Register:
            name: rn.RegisterName
            register_start: int
            register_end: int

            def __init__(self, regname: rn.RegisterName) -> None:
                self.name = regname

                reg = REGISTERS[regname]
                self.register_start = reg.register
                self.register_end = reg.register + reg.length - 1

        registers = [_Register(rn) for rn in register_names]

        registers.sort(key=lambda rd: rd.register_start)

        async with self.update_lock:
            result = {}
            first_idx = 0
            last_idx = 0

            while first_idx < len(registers):
                # Batch together registers:
                # - as long as the total amount of registers doesn't exceed 64
                # - as long as the gap between registers is not more than 16

                while (
                    last_idx + 1 < len(registers)
                    and registers[last_idx + 1].register_end - registers[first_idx].register_start
                    <= MAX_BATCHED_REGISTERS_COUNT
                    and registers[last_idx + 1].register_start - registers[last_idx].register_end
                    < MAX_BATCHED_REGISTERS_GAP
                ):
                    last_idx += 1

                register_names_to_query = [reg.name for reg in registers[first_idx : last_idx + 1]]
                register_names_to_query = await self._filter_registers(
                    register_names_to_query,
                )
                _LOGGER.debug(
                    "Batch update of the following registers: %s",
                    ", ".join(register_names_to_query),
                )

                try:
                    values = await self.client.get_multiple_as_dict(register_names_to_query)
                except HuaweiSolarException as exc:
                    self._handle_batch_read_error(register_names_to_query, exc)
                    values = {}

                self._detect_state_changes(values)
                result.update(values)

                first_idx = last_idx + 1
                last_idx = first_idx

            return result

    async def stop(self) -> bool:
        """Stop the device connection."""
        if not self.primary_device:
            # we are the primary device, so we should also stop the client
            await self.client.disconnect()

        return True

    async def get(self, name: rn.RegisterName) -> "Result[Any]":
        """Get the value of a certain register."""
        # Public get acquires the device update lock so callers don't need
        # to manage locking. Internal library code that already holds
        # `update_lock` should call `_raw_get` to avoid re-acquiring the
        # lock and deadlocking.
        async with self.update_lock:
            return await self._raw_get(name)

    async def _raw_get(self, name: rn.RegisterName) -> "Result[Any]":
        """Low-level get that does not acquire `update_lock`.

        Use this from internal code when `update_lock` is already held.
        """
        assert self.update_lock.locked(), "update_lock must be held when calling _raw_get"
        return await self.client.get(name)

    async def set(self, name: rn.RegisterName, value: Any) -> bool:  # noqa: ANN401
        """Set a register to a certain value."""
        # Public set acquires the device update lock so callers don't need
        # to manage locking. Internal library code that already holds
        # `update_lock` should call `_raw_set` to avoid re-acquiring the
        # lock and deadlocking.
        async with self.update_lock:
            return await self._raw_set(name, value)

    async def _raw_set(self, name: rn.RegisterName, value: Any) -> bool:  # noqa: ANN401
        """Low-level set that does not acquire `update_lock`.

        Use this from internal code when `update_lock` is already held.
        """
        assert self.update_lock.locked(), "update_lock must be held when calling _raw_set"
        return await self.client.set(name, value)

    async def get_active_alarms(self, equip_id: int = 0) -> list[ActiveAlarm]:
        """Read Active Alarms Data File from the device."""
        file_data = await self.read_file(
            ActiveAlarmsDataFile.FILE_TYPE,
            ActiveAlarmsDataFile.query_active_alarms(equip_id),
        )
        active_alarms_file = ActiveAlarmsDataFile(file_data)
        return active_alarms_file.alarms

    async def get_history_alarms(
        self,
        start_time: datetime | int,
        end_time: datetime | int,
    ) -> list[HistoryAlarm]:
        """Read History Alarms Data File from the device."""
        start_epoch = int(start_time.timestamp()) if isinstance(start_time, datetime) else start_time
        end_epoch = int(end_time.timestamp()) if isinstance(end_time, datetime) else end_time

        file_data = await self.read_file(
            HistoryAlarmsDataFile.FILE_TYPE,
            HistoryAlarmsDataFile.query_within_timespan(start_epoch, end_epoch),
        )
        history_alarms_file = HistoryAlarmsDataFile(file_data)
        return history_alarms_file.alarms


class HuaweiSolarDeviceWithLogin(HuaweiSolarDevice, ABC):
    """A HuaweiSolarDevice that requires login to read any registers."""

    def __init__(
        self,
        client: "AsyncHuaweiSolarClient",
        model_name: str,
        *,
        primary_device: "HuaweiSolarDevice | None" = None,
    ) -> None:
        """Initialize with per-instance lock and login state."""
        super().__init__(client, model_name, primary_device=primary_device)
        self.__login_lock = asyncio.Lock()
        self.__heartbeat_enabled = False
        self.__heartbeat_task: asyncio.Task[None] | None = None
        self.__username: str | None = None
        self.__password: str | None = None

    async def ensure_logged_in(self, *, force: bool = False) -> bool:
        """Check if it is necessary to login and performs the necessary login sequence if needed."""
        async with self.__login_lock:
            if force:
                _LOGGER.debug(
                    "Forcefully stopping any heartbeat task (if any is still running)",
                )
                self.stop_heartbeat()

            if self.__username and not self.__heartbeat_enabled:
                _LOGGER.debug(
                    "Currently not logged in: logging in now and starting heartbeat",
                )
                if not self.__password:
                    msg = "Password must be set before logging in"
                    raise InvalidCredentials(msg)
                if not await self.client.login(self.__username, self.__password):
                    raise InvalidCredentials

                self.start_heartbeat()

        return True

    async def login(self, username: str, password: str) -> bool:
        """Perform the login-sequence with the provided username/password."""
        # Acquire the device-level update lock first to preserve ordering
        # (`update_lock` -> transport). Then perform the login while holding
        # the `__login_lock` to protect heartbeat credential state.
        async with self.update_lock, self.__login_lock:
            if not await self.client.login(username, password):
                raise InvalidCredentials

            # save the correct login credentials
            self.__username = username
            self.__password = password
            self.start_heartbeat()

        return True

    def stop_heartbeat(self) -> None:
        """Stop the running heartbeat task (if any)."""
        self.__heartbeat_enabled = False

        if self.__heartbeat_task:
            self.__heartbeat_task.cancel()

    def start_heartbeat(self) -> None:
        """Start the heartbeat thread to stay logged in."""
        if not self.__login_lock.locked():
            msg = "start_heartbeat should only be called from within the login_lock"
            raise RuntimeError(msg)

        if self.__heartbeat_task:
            self.stop_heartbeat()

        async def heartbeat() -> None:
            while self.__heartbeat_enabled:
                try:
                    # Acquire the device update lock before performing transport
                    # operations in the heartbeat to preserve the global lock
                    # ordering: `update_lock` -> transport. This avoids a
                    # lock-inversion with coordinator reads that hold
                    # `update_lock` and then use the transport.
                    async with self.update_lock:
                        self.__heartbeat_enabled = await self.client.heartbeat()

                    await asyncio.sleep(HEARTBEAT_INTERVAL)
                except HuaweiSolarException as err:
                    _LOGGER.warning("Heartbeat stopped because of, %s", err)
                    self.__heartbeat_enabled = False

        self.__heartbeat_enabled = True
        self.__heartbeat_task = asyncio.create_task(heartbeat())

    async def stop(self) -> bool:
        """Stop the device."""
        self.stop_heartbeat()

        return await super().stop()

    async def read_file(self, file_type: int, customized_data: bytes | None = None) -> bytes:
        """Wrap `get_file` from `AsyncHuaweiSolarClient`.

        This method adds a retry-logic for when the login-sequence needs to be repeated.
        """
        logged_in = await self.ensure_logged_in()

        if not logged_in:
            _LOGGER.warning(
                "Could not login, reading file %x will probably fail",
                file_type,
            )

        try:
            async with self.update_lock:
                return await self.client.get_file(file_type, customized_data)
        except PermissionDeniedError:
            if self.__username:
                logged_in = await self.ensure_logged_in(force=True)

                if not logged_in:
                    _LOGGER.exception("Could not login to read file %x", file_type)
                    raise

                async with self.update_lock:
                    return await self.client.get_file(
                        file_type,
                        customized_data,
                    )

            # we have no login-credentials available, pass on permission error
            raise

    ############################
    # Everything write-related #
    ############################

    async def has_write_permission(self) -> bool:
        """Test write permission.

        If login credentials are provided, verifying login status is sufficient and avoids
        performing unnecessary probe writes to holding registers.
        Otherwise (e.g. unauthenticated Modbus TCP via SDongle), a safe probe register is tested.
        """
        if self.__username:
            try:
                return await self.ensure_logged_in()
            except (InvalidCredentials, PermissionDeniedError):
                return False

        # Acquire the device-level update lock for the entire permission check
        # so we preserve the lock ordering: `update_lock` -> transport. This
        # avoids a lock inversion where a coordinator read holds `update_lock`
        # and waits for the transport while this method holds the transport and
        # waits for `update_lock`.
        try:
            async with self.update_lock:
                result = await self._raw_get(WRITE_TEST_REGISTER)
                # Use the low-level `_raw_set` because we already hold
                # `update_lock` here; calling the public `set` would try to
                # re-acquire the lock and deadlock.
                await self._raw_set(WRITE_TEST_REGISTER, result.value)
        except (PermissionDeniedError, WriteException, ReadException):
            # We catch PermissionDeniedError, WriteException (e.g. ServerDeviceFailure on restricted
            # Modbus TCP connections), and ReadException (if WRITE_TEST_REGISTER is not supported).
            return False
        else:
            return True

    async def set(self, name: rn.RegisterName, value: Any) -> bool:  # noqa: ANN401
        """Set a register to a certain value."""
        # Acquire the device-level update lock before performing any transport
        # operations (login, heartbeat, write). This enforces a consistent lock
        # ordering (device.update_lock -> transport communication lock) and
        # prevents the lock-inversion deadlock between coordinator reads (which
        # acquire `update_lock`) and service writes (which use the transport).
        async with self.update_lock:
            logged_in = await self.ensure_logged_in()  # we must login again before trying to set the value

            if not logged_in:
                _LOGGER.warning("Could not login, setting, %s will probably fail", name)

            if self.__heartbeat_enabled:
                try:
                    await self.client.heartbeat()
                except HuaweiSolarException:
                    _LOGGER.warning("Failed to perform heartbeat before write")

            try:
                return await self._raw_set(name, value)
            except PermissionDeniedError:
                if self.__username:
                    logged_in = await self.ensure_logged_in(force=True)

                    if not logged_in:
                        _LOGGER.exception("Could not login to set %s", name)
                        raise

                    # Force a heartbeat first when connected with username/password credentials
                    await self.client.heartbeat()

                    return await self._raw_set(name, value)

                # we have no login-credentials available, pass on permission error
                raise
