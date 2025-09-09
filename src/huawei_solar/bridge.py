"""Higher-level access to Huawei Solar inverters."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Self

from . import register_names as rn
from . import register_values as rv
from .const import (
    MAX_BATCHED_REGISTERS_COUNT,
    MAX_BATCHED_REGISTERS_GAP,
    MAX_NUMBER_OF_PV_STRINGS,
)
from .exceptions import (
    HuaweiSolarException,
    InvalidCredentials,
    PermissionDenied,
    ReadException,
)
from .files import (
    OptimizerRealTimeData,
    OptimizerRealTimeDataFile,
    OptimizerSystemInformation,
    OptimizerSystemInformationDataFile,
)
from .huawei_solar import (
    DEFAULT_BAUDRATE,
    DEFAULT_SLAVE_ID,
    DEFAULT_TCP_PORT,
    AsyncHuaweiSolar,
    Result,
)
from .register_values import StorageProductModel
from .registers import METER_REGISTERS, REGISTERS, TimestampRegister

_LOGGER = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15


class HuaweiSolarBridge(ABC):
    """A higher-level interface making it easier to interact with a Huawei Solar inverter."""

    model_name: str

    __login_lock = asyncio.Lock()
    __heartbeat_enabled = False
    __heartbeat_task: asyncio.Task | None = None

    __username: str | None = None
    __password: str | None = None

    _write_test_register = rn.TIME_ZONE

    def __init__(
        self,
        client: AsyncHuaweiSolar,
        slave_id: int,
        model_name: str,
        update_lock: asyncio.Lock | None = None,
        *,
        connected_via_emma: bool = False,
    ) -> None:
        """DO NOT USE THIS CONSTRUCTOR DIRECTLY. Use create() method instead."""
        self.client = client
        self.slave_id = slave_id
        self.model_name = model_name
        self.update_lock = update_lock or asyncio.Lock()
        self.connected_via_emma = connected_via_emma

        self._primary = slave_id == client.slave_id

    @classmethod
    async def create(
        cls,
        client: AsyncHuaweiSolar,
        slave_id: int,
        model_name: str,
        update_lock: asyncio.Lock | None,
        *,
        connected_via_emma: bool = False,
    ) -> Self:
        """Create instance with the necessary information."""
        bridge = cls(
            client,
            slave_id,
            model_name,
            update_lock,
            connected_via_emma=connected_via_emma,
        )

        await bridge._populate_additional_fields()

        return bridge

    @abstractmethod
    async def _populate_additional_fields(self) -> None:
        """Allow subclass to populate additional fields with information."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        raise NotImplementedError

    async def _get_multiple_to_dict(self, names: list[str]) -> dict[str, Result]:
        return dict(
            zip(
                names,
                await self.client.get_multiple(names, self.slave_id),
                strict=False,
            ),
        )

    def _handle_batch_read_error(self, _queried_register_names: list[str], exc: HuaweiSolarException) -> None:
        """Handle read errors in get."""
        raise exc

    def _detect_state_changes(self, new_values: dict[str, Result]) -> None:  # noqa: B027
        """Update state based on result of batch_update query.

        Used by subclasses to detect important changes.
        """

    async def _filter_registers(self, register_names: list[str]) -> list[str]:
        """Filter registers being requested in batch_update.

        Used by subclasses to prevent read-errors in certain cases.
        """
        return register_names

    def _transform_register_values(
        self,
        register_name: str,  # noqa: ARG002
        result: Result,
    ) -> Result:
        """Optionally Transform the value of a register before returning it."""
        return result

    async def batch_update(self, register_names: list[str]) -> dict[str, Result]:
        """Efficiently retrieve the values of all the registers passed in register_names."""
        if any(register_name not in REGISTERS for register_name in register_names):
            _LOGGER.warning("Unknown register name passed to batch_update")

        class _Register:
            name: str
            register_start: int
            register_end: int

            def __init__(self, regname: str) -> None:
                self.name = regname

                reg = REGISTERS[regname]
                self.register_start = reg.register
                self.register_end = reg.register + reg.length - 1

        registers = [_Register(rn) for rn in register_names]

        registers.sort(key=lambda rd: rd.register_start)

        async with self.update_lock:
            result: dict[str, Result] = {}
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
                    values = await self._get_multiple_to_dict(register_names_to_query)
                except HuaweiSolarException as exc:
                    self._handle_batch_read_error(register_names_to_query, exc)
                    values = {}

                self._detect_state_changes(values)
                result.update(values)

                first_idx = last_idx + 1
                last_idx = first_idx

            for key, value in result.items():
                result[key] = self._transform_register_values(key, value)

            return result

    async def _read_file(self, file_type: int, customized_data: bytes | None = None) -> bytes:
        """Wrap `get_file` from `AsyncHuaweiSolar` in a retry-logic for when the login-sequence needs to be repeated."""
        logged_in = await self.ensure_logged_in()

        if not logged_in:
            _LOGGER.warning(
                "Could not login, reading file %x will probably fail",
                file_type,
            )

        try:
            return await self.client.get_file(file_type, customized_data, self.slave_id)
        except PermissionDenied:
            if self.__username:
                logged_in = await self.ensure_logged_in(force=True)

                if not logged_in:
                    _LOGGER.exception("Could not login to read file %x", file_type)
                    raise

                return await self.client.get_file(
                    file_type,
                    customized_data,
                    self.slave_id,
                )

            # we have no login-credentials available, pass on permission error
            raise

    async def stop(self) -> bool:
        """Stop the bridge."""
        self.stop_heartbeat()

        if self._primary:
            await self.client.stop()

        return True

    ############################
    # Everything write-related #
    ############################

    async def has_write_permission(self) -> bool:
        """Test write permission by getting the time zone and trying to write that same value back to the inverter."""
        try:
            result = await self.client.get(self._write_test_register, self.slave_id)

            await self.client.set(self._write_test_register, result.value, self.slave_id)
        except PermissionDenied:
            return False
        else:
            return True

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
                assert self.__password
                if not await self.client.login(self.__username, self.__password):
                    raise InvalidCredentials

                self.start_heartbeat()

        return True

    async def login(self, username: str, password: str) -> bool:
        """Perform the login-sequence with the provided username/password."""
        async with self.__login_lock:
            if not await self.client.login(username, password, self.slave_id):
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
        assert self.__login_lock.locked(), "Should only be called from within the login_lock!"

        if self.__heartbeat_task:
            self.stop_heartbeat()

        async def heartbeat() -> None:
            while self.__heartbeat_enabled:
                try:
                    self.__heartbeat_enabled = await self.client.heartbeat(
                        self.slave_id,
                    )
                    await asyncio.sleep(HEARTBEAT_INTERVAL)
                except HuaweiSolarException as err:
                    _LOGGER.warning("Heartbeat stopped because of, %s", err)
                    self.__heartbeat_enabled = False

        self.__heartbeat_enabled = True
        self.__heartbeat_task = asyncio.create_task(heartbeat())

    async def set(self, name: str, value: Any) -> bool:  # noqa: ANN401
        """Set a register to a certain value."""
        logged_in = await self.ensure_logged_in()  # we must login again before trying to set the value

        if not logged_in:
            _LOGGER.warning("Could not login, setting, %s will probably fail", name)

        if self.__heartbeat_enabled:
            try:
                await self.client.heartbeat(self.slave_id)
            except HuaweiSolarException:
                _LOGGER.warning("Failed to perform heartbeat before write")

        try:
            return await self.client.set(name, value, slave_id=self.slave_id)
        except PermissionDenied:
            if self.__username:
                logged_in = await self.ensure_logged_in(force=True)

                if not logged_in:
                    _LOGGER.exception("Could not login to set %s", name)
                    raise

                # Force a heartbeat first when connected with username/password credentials
                await self.client.heartbeat(self.slave_id)

                return await self.client.set(name, value, slave_id=self.slave_id)

            # we have no login-credentials available, pass on permission error
            raise


class HuaweiSUN2000Bridge(HuaweiSolarBridge):
    """Bridge for Huawei SUN2000 devices."""

    serial_number: str
    product_number: str
    firmware_version: str
    software_version: str

    pv_string_count: int = 0
    has_optimizers: bool = False

    battery_1_type: rv.StorageProductModel = rv.StorageProductModel.NONE
    battery_2_type: rv.StorageProductModel = rv.StorageProductModel.NONE
    supports_capacity_control = False
    power_meter_online = False
    power_meter_type: rv.MeterType | None = None

    _pv_registers: list[str]

    _time_zone: int | None = None
    _dst: bool | None = None

    _previous_device_status: str | None = None

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        return model_name.startswith(
            (
                "SUN2000",
                "EDF ESS",
                "Powershifter",
                "SWI300",
            ),
        )

    async def _populate_additional_fields(self) -> None:
        (
            serial_number_result,
            pn_result,
            firmware_version_result,
            software_version_result,
        ) = await self.client.get_multiple(
            [
                rn.SERIAL_NUMBER,
                rn.PN,
                rn.FIRMWARE_VERSION,
                rn.SOFTWARE_VERSION,
            ],
            self.slave_id,
        )
        self.serial_number = serial_number_result.value
        self.product_number = pn_result.value
        self.firmware_version = firmware_version_result.value
        self.software_version = software_version_result.value

        self.pv_string_count = (await self.client.get(rn.NB_PV_STRINGS, self.slave_id)).value
        self._pv_registers = self._compute_pv_registers()

        with suppress(
            ReadException,  # some inverters throw an IllegalAddress exception when accessing this address
        ):
            self.has_optimizers = (await self.client.get(rn.NB_OPTIMIZERS, self.slave_id)).value

        with suppress(ReadException):
            self.battery_1_type = (
                await self.client.get(
                    rn.STORAGE_UNIT_1_PRODUCT_MODEL,
                    self.slave_id,
                )
            ).value

        with suppress(ReadException):
            self.battery_2_type = (
                await self.client.get(
                    rn.STORAGE_UNIT_2_PRODUCT_MODEL,
                    self.slave_id,
                )
            ).value

        if (
            self.battery_1_type is not StorageProductModel.NONE
            and self.battery_2_type is not StorageProductModel.NONE
            and self.battery_1_type != self.battery_2_type
        ):
            _LOGGER.warning(
                "Detected two batteries of a different type. This can lead to unexpected behavior",
            )

        if self.battery_type != rv.StorageProductModel.NONE:
            try:
                await self.client.get(
                    rn.STORAGE_CAPACITY_CONTROL_MODE,
                    self.slave_id,
                )
                self.supports_capacity_control = True
            except ReadException:
                _LOGGER.debug("Storage capacity control as it is not supported by device %d", self.slave_id)
                self.supports_capacity_control = False

        with suppress(ReadException):
            self.power_meter_online = (
                await self.client.get(rn.METER_STATUS, self.slave_id)
            ).value == rv.MeterStatus.NORMAL

        # Caveat: if the inverter is in offline mode, and the power meter is thus offline,
        # we will incorrectly detect that no power meter is present.
        if self.power_meter_online:
            self.power_meter_type = (await self.client.get(rn.METER_TYPE, self.slave_id)).value

        self._dst = (await self.client.get(rn.DAYLIGHT_SAVING_TIME, self.slave_id)).value
        self._time_zone = (await self.client.get(rn.TIME_ZONE, self.slave_id)).value

    def _handle_batch_read_error(self, queried_register_names: list[str], exc: HuaweiSolarException) -> None:
        """Handle read errors in batch_update."""
        if any(regname in METER_REGISTERS for regname in queried_register_names):
            _LOGGER.info(
                "Fetching power meter registers failed. "
                "We'll assume that this is due to the power meter going offline and the registers "
                "becoming invalid as a result",
                exc_info=exc,
            )
            self.power_meter_online = False

        raise exc

    def _detect_state_changes(self, new_values: dict[str, Result]) -> None:
        """Update state based on result of batch_update query.

        Used by subclasses to detect important changes.
        """
        # When there is a power outage, but the installation stays online with a backup box installed,
        # then the power meter goes offline. If we still try to query it, the inverter will close the connection.
        # To prevent this, we always check if the power meter is still online when the device status changes.
        #
        # cfr. https://gitlab.com/Emilv2/huawei-solar/-/merge_requests/9#note_1281471842

        if rn.DEVICE_STATUS in new_values:
            new_device_status = new_values[rn.DEVICE_STATUS].value
            if self._previous_device_status != new_device_status:
                _LOGGER.debug(
                    "Detected a device state change from %s to %s : resetting power meter online status",
                    self._previous_device_status,
                    new_device_status,
                )
                self.power_meter_online = False

            self._previous_device_status = new_device_status

    async def _filter_registers(self, register_names: list[str]) -> list[str]:
        result = register_names

        # Filter out power meter registers if the power meter is offline
        power_meter_register_names = {rn for rn in register_names if rn in METER_REGISTERS}
        if power_meter_register_names:
            # Do a check of the METER_STATUS register only if the power meter is marked offline
            if not self.power_meter_online:
                power_meter_online_register = await self.client.get(
                    rn.METER_STATUS,
                    self.slave_id,
                )
                self.power_meter_online = power_meter_online_register.value

                _LOGGER.debug("Power meter online: %s", self.power_meter_online)

            # If it is still offline after the check then filter out all power meter registers
            if not self.power_meter_online:
                _LOGGER.debug(
                    "Removing power meter registers as the power meter is offline",
                )
                result = list(
                    filter(
                        lambda regname: regname == rn.METER_STATUS or rn not in power_meter_register_names,
                        register_names,
                    ),
                )

        return result

    def _transform_register_values(self, register_name: str, result: Result) -> Result:
        if isinstance(REGISTERS[register_name], TimestampRegister) and result.value is not None:
            assert isinstance(result.value, datetime)
            value = result.value
            if self._time_zone:
                value -= timedelta(minutes=self._time_zone)
            # if DST is in effect, we need to shift another hour.
            if self._dst:
                value -= timedelta(hours=1)

            return Result(value.astimezone(tz=UTC), result.unit)

        return result

    async def _get_system_time(self) -> int | None:
        """Get the system time from the inverter."""
        if self.connected_via_emma:
            # Inverters don't return their own system time when connected via EMMA.
            # Instead, we need to read the system time from the EMMA device.

            return (await self.client.get(rn.EMMA_SYSTEM_TIME, self.client.slave_id)).value

        return (await self.client.get(rn.SYSTEM_TIME_RAW, self.slave_id)).value

    async def get_latest_optimizer_history_data(
        self,
    ) -> dict[int, OptimizerRealTimeData]:
        """Read the latest Optimizer History Data File from the inverter."""
        # emulates behavior from FusionSolar app when current status of optimizers is queried
        end_time = await self._get_system_time()
        if end_time is None:
            msg = "Could not retrieve system time. Cannot proceed with reading optimizer data."
            raise ReadException(msg)
        start_time = end_time - 600

        file_data = await self._read_file(
            OptimizerRealTimeDataFile.FILE_TYPE,
            OptimizerRealTimeDataFile.query_within_timespan(start_time, end_time),
        )
        real_time_data = OptimizerRealTimeDataFile(file_data)

        if len(real_time_data.data_units) == 0:
            return {}

        # we only expect one element, but if more would be present,
        # then only the latest one is of interest (list is sorted time descending)
        latest_unit = real_time_data.data_units[0]

        return {opt.optimizer_address: opt for opt in latest_unit.optimizers}

    async def get_optimizer_system_information_data(
        self,
    ) -> dict[int, OptimizerSystemInformation]:
        """Read the Optimizer System Information Data File from the inverter."""
        file_data = await self._read_file(OptimizerSystemInformationDataFile.FILE_TYPE)
        system_information_data = OptimizerSystemInformationDataFile(file_data)

        return {opt.optimizer_address: opt for opt in system_information_data.optimizers}

    def _compute_pv_registers(self) -> list[str]:
        """Get the registers for the PV strings which were detected from the inverter."""
        assert 1 <= self.pv_string_count <= MAX_NUMBER_OF_PV_STRINGS

        pv_registers = []
        for idx in range(1, self.pv_string_count + 1):
            pv_registers.extend(
                [
                    getattr(rn, f"PV_{idx:02}_VOLTAGE"),
                    getattr(rn, f"PV_{idx:02}_CURRENT"),
                ],
            )
        return pv_registers

    @property
    def battery_type(self) -> rv.StorageProductModel:
        """The battery type present on this inverter."""
        if self.battery_1_type != rv.StorageProductModel.NONE:
            return self.battery_1_type
        return self.battery_2_type


class HuaweiEMMABridge(HuaweiSolarBridge):
    """Bridge for Huawei EMMA devices.

    Also called 'SmartHEMS' by Huawei.
    """

    serial_number: str
    software_version: str
    model: str

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        return model_name.startswith("SmartHEMS")

    async def has_write_permission(self) -> bool:
        """EMMA always gives write access."""
        return True

    async def _populate_additional_fields(self) -> None:
        (
            serial_number_result,
            software_version_result,
        ) = await self.client.get_multiple(
            [
                rn.SERIAL_NUMBER,
                rn.SOFTWARE_VERSION,
            ],
            self.slave_id,
        )
        self.serial_number = serial_number_result.value
        self.software_version = software_version_result.value

        self.model = (await self.client.get(rn.EMMA_MODEL, self.slave_id)).value


class HuaweiChargerBridge(HuaweiSolarBridge):
    """Bridge for Huawei SCharger devices."""

    serial_number: str
    software_version: str
    model: str

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        return model_name.startswith("FusionCharge")

    async def _populate_additional_fields(self) -> None:
        (
            serial_number_result,
            software_version_result,
        ) = await self.client.get_multiple(
            [
                rn.CHARGER_ESN,
                rn.CHARGER_SOFTWARE_VERSION,
            ],
            self.slave_id,
        )
        self.serial_number = serial_number_result.value
        self.software_version = software_version_result.value

        self.model = (await self.client.get(rn.CHARGER_MODEL, self.slave_id)).value


BRIDGE_CLASSES: list[type[HuaweiSolarBridge]] = [HuaweiSUN2000Bridge, HuaweiEMMABridge, HuaweiChargerBridge]


async def create_tcp_bridge(
    host: str,
    port: int = DEFAULT_TCP_PORT,
    slave_id: int = DEFAULT_SLAVE_ID,
) -> HuaweiSolarBridge:
    """Connect to the device via Modbus TCP and create the appropriate bridge."""
    return await _create(await AsyncHuaweiSolar.create(host, port, slave_id), slave_id)


async def create_rtu_bridge(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    slave_id: int = DEFAULT_SLAVE_ID,
) -> HuaweiSolarBridge:
    """Connect to the device via Modbus RTU and create the appropriate bridge."""
    return await _create(await AsyncHuaweiSolar.create_rtu(port, baudrate, slave_id), slave_id)


async def create_sub_bridge(
    primary_bridge: HuaweiSolarBridge,
    slave_id: int,
) -> HuaweiSolarBridge:
    """Create a HuaweiSolarBridge instance for extra servers accessible as subdevices via an existing Bridge."""
    assert primary_bridge.slave_id != slave_id
    return await _create(
        primary_bridge.client,
        slave_id,
        primary_bridge.update_lock,
        connected_via_emma=isinstance(primary_bridge, HuaweiEMMABridge),
    )


async def _create(
    client: AsyncHuaweiSolar,
    slave_id: int,
    update_lock: asyncio.Lock | None = None,
    *,
    connected_via_emma: bool = False,
) -> HuaweiSolarBridge:
    model_name_result = await client.get(rn.MODEL_NAME, slave_id)
    model_name = model_name_result.value

    for candidate_bridge_class in BRIDGE_CLASSES:
        if candidate_bridge_class.supports_device(model_name):
            return await candidate_bridge_class.create(
                client,
                slave_id,
                model_name,
                update_lock,
                connected_via_emma=connected_via_emma,
            )

    _LOGGER.warning("Unknown product model '%s'. Defaulting to a SUN2000 device.", model_name)
    return await HuaweiSUN2000Bridge.create(
        client,
        slave_id,
        model_name,
        update_lock,
    )
