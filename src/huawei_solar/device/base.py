"""Base for classes that represent a single Huawei Solar device."""

import asyncio
import logging
import time
import warnings
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Self

from huawei_solar import register_names as rn
from huawei_solar.const import MAX_BATCHED_REGISTERS_COUNT, MAX_BATCHED_REGISTERS_GAP
from huawei_solar.exceptions import (
    FileNotReadyError,
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
    InverterPerformanceDataFile,
    PerformanceDataPoint,
    PerformanceRequestType,
)
from huawei_solar.modbus_client import (
    FILE_BUSY_EXCEPTION_CODES,
    FILE_BUSY_RETRY_INTERVAL,
    FILE_PREPARE_RETRY_INTERVAL,
    FILE_READ_RETRIES,
)
from huawei_solar.modbus_pdu import PermissionDeniedError
from huawei_solar.registers import REGISTERS

if TYPE_CHECKING:
    from huawei_solar.modbus_client import AsyncHuaweiSolarClient
    from huawei_solar.register_definitions import Result

_LOGGER = logging.getLogger(__name__)


HEARTBEAT_INTERVAL = 15


def _retries_kwarg(retries: int | None) -> dict[str, int]:
    """Pass `retries` to read_file only when given, so overrides with the older signature keep working."""
    return {} if retries is None else {"retries": retries}


WRITE_TEST_REGISTER = rn.TIME_ZONE


class HuaweiSolarDevice(ABC):
    """A higher-level interface making it easier to interact with a Huawei Solar inverter."""

    model_name: str
    serial_number: str
    update_lock: asyncio.Lock
    primary_device: "HuaweiSolarDevice | None" = None
    _use_host_timezone: bool = False

    # FusionSolar treats an EMMA or a SmartLogger, and the devices behind it, as "mounted" devices: it queries their
    # history alarm files with tag 0x24 instead of the 0x20 used for a directly connected inverter or SDongle.
    _is_alarm_mount_master: ClassVar[bool] = False
    # ... and reads their active alarm files through the master on unit 0 with custom data E0 02 <address> 00.
    _routes_mounted_alarms: ClassVar[bool] = False

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
        serial_number: str | None = None,
    ) -> Self:
        """Create instance with the necessary information."""
        device = cls(
            client,
            model_name,
            primary_device=primary_device,
        )
        if serial_number is not None:
            device.serial_number = serial_number

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

    def _adopt_matching_host_timezone(
        self,
        device_offset: timedelta,
        *,
        device_dst: bool | None = None,
    ) -> None:
        """Adopt the host's local timezone if its current offset and DST state match the device."""
        self._use_host_timezone = False
        now_local = datetime.now().astimezone()
        if now_local.utcoffset() != device_offset:
            return
        if device_dst is not None:
            tm_isdst = time.localtime().tm_isdst
            if tm_isdst >= 0 and bool(tm_isdst) != device_dst:
                return

        self._use_host_timezone = True

    def _transform_datetime(self, value: datetime) -> datetime:
        """Optionally transform a decoded UTC datetime before returning it."""
        if self._use_host_timezone:
            return value.replace(tzinfo=None).astimezone(tz=UTC)
        return value

    def _transform_register_values(
        self,
        register_name: rn.RegisterName,  # noqa: ARG002
        result: "Result[Any]",
    ) -> "Result[Any]":
        """Optionally transform the value of a register before returning it."""
        return result

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
                for key, value in values.items():
                    values[key] = self._transform_register_values(key, value)
                result.update(values)

                first_idx = last_idx + 1
                last_idx = first_idx

            return result

    async def stop(self) -> bool:
        """Stop the device connection."""
        if not self.primary_device:
            # if primary_device is None, we are the primary device, so we should also stop the client
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
        return self._transform_register_values(name, await self.client.get(name))

    async def read_file(
        self,
        file_type: int,
        customized_data: bytes | None = None,
        *,
        retries: int = FILE_READ_RETRIES,
    ) -> bytes:
        """Wrap `get_file` from `AsyncHuaweiSolarClient`.

        When the device answers that it is still preparing the file (FileNotReadyError) or that it is busy (exception
        0x06 after the transport's own retries, or Huawei's 0xB0), wait 3 s or 10 s and try again, at most `retries`
        times; then the error is raised. The update lock, which all devices behind one connection share, is only held
        during each attempt, not while waiting. The default suits periodic polling: a file that is not ready yet is
        read on a later poll. Pass `retries=0` to fail at once.
        """
        attempt = 0
        while True:
            try:
                return await self._read_file_once(file_type, customized_data)
            except FileNotReadyError as err:
                if attempt >= retries:
                    raise
                delay: float = FILE_PREPARE_RETRY_INTERVAL
                _LOGGER.debug("File %#x is being prepared (%s%%), asking again in %ss", file_type, err.progress, delay)
            except ReadException as err:
                if err.modbus_exception_code not in FILE_BUSY_EXCEPTION_CODES or attempt >= retries:
                    raise
                delay = FILE_BUSY_RETRY_INTERVAL
                _LOGGER.debug(
                    "Device busy (%#04x) reading file %#x, trying again in %ss",
                    err.modbus_exception_code,
                    file_type,
                    delay,
                )
            attempt += 1
            await asyncio.sleep(delay)

    async def _read_file_once(self, file_type: int, customized_data: bytes | None) -> bytes:
        """Read a file once, holding the update lock."""
        async with self.update_lock:
            return await self.client.get_file(file_type, customized_data)

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

    def _alarm_mount_master(self) -> "HuaweiSolarDevice | None":
        """Return the EMMA or SmartLogger that manages this device's alarm files (possibly itself), if any."""
        if self._is_alarm_mount_master:
            return self
        primary = self.primary_device
        if primary is not None and primary._is_alarm_mount_master:  # noqa: SLF001 (same class hierarchy)
            return primary
        return None

    def _alarm_router(self) -> "HuaweiSolarDevice | None":
        """Return the EMMA through which this device's active alarm file is read (possibly itself), if any."""
        master = self._alarm_mount_master()
        if master is not None and master._routes_mounted_alarms:  # noqa: SLF001 (same class hierarchy)
            return master
        return None

    def _alarm_clock(self) -> tuple[Callable[[datetime], datetime], Callable[[datetime | int], int]]:
        """Return the (decode, encode) conversions between UTC and the timestamps in this device's alarm files.

        Behind an EMMA the EMMA's UTC offset is used, as long as the EMMA knows it: SmartGuard and SCharger have no
        time zone of their own, and an inverter's own time registers are not reliable behind an EMMA.
        """
        router = self._alarm_router()
        clock = router if router is not None and router._has_utc_reference() else self  # noqa: SLF001
        return clock._transform_datetime, clock._to_device_epoch  # noqa: SLF001 (same class hierarchy)

    async def _refresh_alarm_clock(self) -> None:
        """Let the EMMA re-read its UTC offset before it is applied to alarm times, so DST changes are followed."""
        router = self._alarm_router()
        if router is not None:
            async with self.update_lock:
                await router._refresh_utc_offset()  # noqa: SLF001 (same class hierarchy)

    def _has_utc_reference(self) -> bool:
        """Return True when this device knows how its local wall-clock time relates to UTC."""
        return self._use_host_timezone

    async def _refresh_utc_offset(self) -> None:  # noqa: B027
        """Re-read the device's UTC offset, if it has one; called with the update lock held."""

    def _to_device_epoch(self, value: datetime | int) -> int:
        """Convert a point in time to the device-local wall-clock epoch used in file queries.

        This is the inverse of `_transform_datetime`. An int is taken to be a device epoch already and returned
        unchanged. A naive datetime is taken to be in the host's local time, like `datetime.timestamp()` does.
        """
        if isinstance(value, int):
            return value
        if value.tzinfo is None:
            value = value.astimezone()
        if self._use_host_timezone:
            return int(value.astimezone().replace(tzinfo=UTC).timestamp())
        # Every other transform subtracts a fixed offset (time zone, DST, the EMMA's UTC offset): add it back.
        offset = value - self._transform_datetime(value)
        return int((value + offset).timestamp())

    async def get_active_alarms(
        self,
        equip_id: int = 0,
        *,
        direct: bool = False,
        retries: int | None = None,
    ) -> list[ActiveAlarm]:
        """Read the active alarms of this device from the active alarms file (0xA1).

        Like FusionSolar, the active alarms of an EMMA and of the devices behind it are read through the EMMA's
        unit with custom data `E0 02 <address> 00`: the device's unit id, or 0xFF for the EMMA itself. Other
        devices are read on their own unit with custom data `11 04 00000000`. `direct=True` forces the latter for
        a device behind an EMMA.

        Occurrence times are converted from the device's local wall-clock time to UTC; behind an EMMA with the
        EMMA's offset, which is read again first. A file that the device is still preparing is asked for again
        `retries` times (default: see `read_file`), then FileNotReadyError is raised; it is never reported as
        "no alarms".

        `equip_id` is deprecated and ignored: the value of the 0x11 query is not a device selector, FusionSolar
        always sends 0. Call this method on the device whose alarms are wanted instead.
        """
        if equip_id:
            warnings.warn(
                "The equip_id argument of get_active_alarms is ignored: call it on the device to query instead.",
                FutureWarning,
                stacklevel=2,
            )

        await self._refresh_alarm_clock()
        router = None if direct else self._alarm_router()
        if router is not None:
            target = None if router is self else self.client.unit_id
            # read_file takes the update lock, which is shared with the EMMA: take it only there.
            file_data = await router.read_file(
                ActiveAlarmsDataFile.FILE_TYPE,
                ActiveAlarmsDataFile.query_mounted_active_alarms(target),
                **_retries_kwarg(retries),
            )
            active_alarms_file = ActiveAlarmsDataFile(file_data, hems_layout=True)
        else:
            file_data = await self.read_file(
                ActiveAlarmsDataFile.FILE_TYPE,
                ActiveAlarmsDataFile.query_active_alarms(),
                **_retries_kwarg(retries),
            )
            # FusionSolar decodes every file read in an EMMA session with the EMMA flag layout
            active_alarms_file = ActiveAlarmsDataFile(file_data, hems_layout=self._routes_mounted_alarms)

        to_utc, _ = self._alarm_clock()
        return [replace(alarm, occur_time=to_utc(alarm.occur_time)) for alarm in active_alarms_file.alarms]

    async def get_history_alarms(
        self,
        start_time: datetime | int,
        end_time: datetime | int,
        *,
        retries: int | None = None,
    ) -> list[HistoryAlarm]:
        """Read History Alarms Data File from the device.

        Targets: SUN2000 inverters, SmartLogger, EMMA, and other Huawei Solar devices supporting Modbus file upload.

        The window is given as datetimes, which are converted to the device's local wall-clock epoch, or as ints,
        which are taken to be device epochs already. Like FusionSolar, an EMMA or SmartLogger and the devices
        behind it are queried with tag 0x24 (alarms recovered within the window), a directly connected inverter or
        SDongle with tag 0x20 (alarms that occurred within the window). The file is read on the device's own unit.
        Unlike FusionSolar, a SmartLogger V5 also gets little-endian times with tag 0x24: the library cannot tell it
        apart (see `HistoryAlarmsDataFile.query_within_timespan`).
        """
        await self._refresh_alarm_clock()
        to_utc, to_device_epoch = self._alarm_clock()
        tag = (
            HistoryAlarmsDataFile.TAG_MOUNTED_RECOVER_TIME
            if self._alarm_mount_master() is not None
            else HistoryAlarmsDataFile.TAG_OCCUR_TIME
        )

        file_data = await self.read_file(
            HistoryAlarmsDataFile.FILE_TYPE,
            HistoryAlarmsDataFile.query_within_timespan(
                to_device_epoch(start_time),
                to_device_epoch(end_time),
                tag=tag,
            ),
            **_retries_kwarg(retries),
        )
        history_alarms_file = HistoryAlarmsDataFile(file_data)
        return [
            replace(
                alarm,
                occur_time=to_utc(alarm.occur_time),
                recover_time=to_utc(alarm.recover_time),
            )
            for alarm in history_alarms_file.alarms
        ]

    async def get_performance_data(
        self,
        request_type: PerformanceRequestType | int,
        start_time: datetime | int,
        end_time: datetime | int,
        cycle: int | None = None,
    ) -> list[PerformanceDataPoint]:
        """Read Historical Performance / Energy Data from the device.

        Targets: SUN2000 inverters, SmartLogger, EMMA (covering inverter yield,
        battery storage, and power meter telemetry).
        """
        start_epoch = int(start_time.timestamp()) if isinstance(start_time, datetime) else start_time
        end_epoch = int(end_time.timestamp()) if isinstance(end_time, datetime) else end_time

        file_data = await self.read_file(
            InverterPerformanceDataFile.FILE_TYPE,
            InverterPerformanceDataFile.query_within_timespan(request_type, start_epoch, end_epoch),
        )
        performance_file = InverterPerformanceDataFile(file_data, request_type=request_type, cycle=cycle)
        return [replace(point, time=self._transform_datetime(point.time)) for point in performance_file.data_points]


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
                except asyncio.CancelledError:
                    self.__heartbeat_enabled = False
                    break
                except (HuaweiSolarException, TimeoutError) as err:
                    _LOGGER.warning("Heartbeat stopped because of: %s", err)
                    self.__heartbeat_enabled = False
                    break
                except Exception:
                    _LOGGER.exception("Heartbeat unexpectedly crashed")
                    self.__heartbeat_enabled = False
                    break

        self.__heartbeat_enabled = True
        self.__heartbeat_task = asyncio.create_task(heartbeat())

    async def stop(self) -> bool:
        """Stop the device."""
        self.stop_heartbeat()

        return await super().stop()

    async def _read_file_once(self, file_type: int, customized_data: bytes | None) -> bytes:
        """Read a file once, holding the update lock, and log in again when the device answers "permission denied"."""
        async with self.update_lock:
            logged_in = await self.ensure_logged_in()

            if not logged_in:
                _LOGGER.warning(
                    "Could not login, reading file %x will probably fail",
                    file_type,
                )

            try:
                return await self.client.get_file(file_type, customized_data)
            except PermissionDeniedError:
                if self.__username:
                    logged_in = await self.ensure_logged_in(force=True)

                    if not logged_in:
                        _LOGGER.exception("Could not login to read file %x", file_type)
                        raise

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
