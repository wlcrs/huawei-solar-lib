"""Higher-level access to Huawei Solar inverters."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from . import register_names as rn
from . import register_values as rv
from .const import MAX_BATCHED_REGISTERS_COUNT, MAX_BATCHED_REGISTERS_GAP, MAX_NUMBER_OF_PV_STRINGS
from .exceptions import HuaweiSolarException, InvalidCredentials, PermissionDenied, ReadException
from .files import (
    OptimizerRealTimeData,
    OptimizerRealTimeDataFile,
    OptimizerSystemInformation,
    OptimizerSystemInformationDataFile,
)
from .huawei_solar import DEFAULT_BAUDRATE, DEFAULT_SLAVE, DEFAULT_TCP_PORT, AsyncHuaweiSolar, Result
from .registers import METER_REGISTERS, REGISTERS

_LOGGER = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15


class HuaweiSolarBridge:
    """A higher-level interface making it easier to interact with a Huawei Solar inverter."""

    model_name: str
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

    __login_lock = asyncio.Lock()
    __heartbeat_enabled = False
    __heartbeat_task: asyncio.Task | None = None

    __username: str | None = None
    __password: str | None = None

    _previous_device_status: int | None = None

    def __init__(
        self,
        client: AsyncHuaweiSolar,
        update_lock: asyncio.Lock,
        primary: bool,
        slave_id: int | None = None,
    ):
        """DO NOT USE THIS CONSTRUCTOR DIRECTLY. Use HuaweiSolarBridge.create() instead."""
        self.client = client
        self.update_lock = update_lock

        self._primary = primary
        self.slave_id = slave_id or 0

    @classmethod
    async def create(
        cls,
        host: str,
        port: int = DEFAULT_TCP_PORT,
        slave_id: int = DEFAULT_SLAVE,
    ) -> HuaweiSolarBridge:
        """Create a HuaweiSolarBridge instance for the inverter hosting the modbus interface."""
        client = await AsyncHuaweiSolar.create(host, port, slave_id)
        update_lock = asyncio.Lock()
        bridge = cls(client, update_lock, primary=True)
        await HuaweiSolarBridge.__populate_fields(bridge)

        return bridge

    @classmethod
    async def create_rtu(
        cls,
        port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        slave_id: int = DEFAULT_SLAVE,
    ) -> HuaweiSolarBridge:
        """Create a HuaweiSolarBridge instance for the inverter hosting the modbus interface."""
        client = await AsyncHuaweiSolar.create_rtu(port, baudrate, slave_id)
        update_lock = asyncio.Lock()
        bridge = cls(client, update_lock, primary=True)
        await HuaweiSolarBridge.__populate_fields(bridge)

        return bridge

    @classmethod
    async def create_extra_slave(
        cls,
        primary_bridge: HuaweiSolarBridge,
        slave_id: int,
    ) -> HuaweiSolarBridge:
        """Create a HuaweiSolarBridge instance for extra slaves accessible via the given AsyncHuaweiSolar instance."""
        assert primary_bridge.slave_id != slave_id

        await primary_bridge.client.determine_battery_type(slave_id)

        bridge = cls(
            primary_bridge.client,
            primary_bridge.update_lock,
            primary=False,
            slave_id=slave_id,
        )
        await HuaweiSolarBridge.__populate_fields(bridge)
        return bridge

    @staticmethod
    async def __populate_fields(bridge: HuaweiSolarBridge):
        """Compute all the fields that should be returned on each update-call."""
        (
            model_name_result,
            serial_number_result,
            pn_result,
            firmware_version_result,
            software_version_result,
        ) = await bridge.client.get_multiple(
            [
                rn.MODEL_NAME,
                rn.SERIAL_NUMBER,
                rn.PN,
                rn.FIRMWARE_VERSION,
                rn.SOFTWARE_VERSION,
            ],
            bridge.slave_id,
        )

        bridge.model_name = model_name_result.value
        bridge.serial_number = serial_number_result.value
        bridge.product_number = pn_result.value
        bridge.firmware_version = firmware_version_result.value
        bridge.software_version = software_version_result.value

        bridge.pv_string_count = (await bridge.client.get(rn.NB_PV_STRINGS, bridge.slave_id)).value
        bridge._pv_registers = bridge._compute_pv_registers()

        with suppress(
            ReadException,  # some inverters throw an IllegalAddress exception when accessing this address
        ):
            bridge.has_optimizers = (await bridge.client.get(rn.NB_OPTIMIZERS, bridge.slave_id)).value

        with suppress(ReadException):
            bridge.battery_1_type = (
                await bridge.client.get(
                    rn.STORAGE_UNIT_1_PRODUCT_MODEL,
                    bridge.slave_id,
                )
            ).value

        with suppress(ReadException):
            bridge.battery_2_type = (
                await bridge.client.get(
                    rn.STORAGE_UNIT_2_PRODUCT_MODEL,
                    bridge.slave_id,
                )
            ).value

        if bridge.battery_2_type not in (
            rv.StorageProductModel.NONE,
            bridge.battery_1_type,
        ):
            _LOGGER.warning(
                "Detected two batteries of a different type. This can lead to unexpected behavior.",
            )

        if bridge.battery_type != rv.StorageProductModel.NONE:
            try:
                await bridge.client.get(
                    rn.STORAGE_CAPACITY_CONTROL_MODE,
                    bridge.slave_id,
                )
                bridge.supports_capacity_control = True
            except ReadException:
                pass

        with suppress(ReadException):
            bridge.power_meter_online = (
                await bridge.client.get(rn.METER_STATUS, bridge.slave_id)
            ).value == rv.MeterStatus.NORMAL

        # Caveat: if the inverter is in offline mode, and the power meter is thus offline,
        # we will incorrectly detect that no power meter is present.
        if bridge.power_meter_online:
            bridge.power_meter_type = (await bridge.client.get(rn.METER_TYPE, bridge.slave_id)).value

    async def _get_multiple_to_dict(self, names: list[str]) -> dict[str, Result]:
        return dict(
            zip(
                names,
                await self.client.get_multiple(names, self.slave_id),
                strict=False,
            ),
        )

    def _detect_state_changes(self, new_values: dict[str, Result]) -> None:
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
        if len(power_meter_register_names):
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
                    "Removing power meter registers as the power meter is offline.",
                )
                result = list(
                    filter(
                        lambda regname: regname == rn.METER_STATUS or rn not in power_meter_register_names,
                        register_names,
                    ),
                )

        return result

    async def batch_update(self, register_names: list[str]) -> dict[str, Result]:
        """Efficiently retrieve the values of all the registers passed in register_names."""

        class _Register:
            name: str
            register_start: int
            register_end: int

            def __init__(self, regname: str):
                self.name = regname

                reg = REGISTERS[regname]
                self.register_start = reg.register
                self.register_end = reg.register + reg.length - 1

        registers = [_Register(rn) for rn in register_names]

        if None in registers:
            _LOGGER.warning("Unknown register name passed to batch_update")

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
                    values = await self._get_multiple_to_dict(register_names_to_query)
                except HuaweiSolarException as exc:
                    if any(regname in METER_REGISTERS for regname in register_names_to_query):
                        _LOGGER.info(
                            "Fetching power meter registers failed. "
                            "We'll assume that this is due to the power meter going offline and the registers "
                            "becoming invalid as a result.",
                            exc_info=exc,
                        )
                        self.power_meter_online = False
                    raise

                self._detect_state_changes(values)
                result.update(values)

                first_idx = last_idx + 1
                last_idx = first_idx

            return result

    async def _read_file(self, file_type, customized_data=None) -> bytes:
        """Wrap `get_file` from `AsyncHuaweiSolar` in a retry-logic for when the login-sequence needs to be repeated."""
        logged_in = await self.ensure_logged_in()

        if not logged_in:
            _LOGGER.warning(
                "Could not login, reading file %x will probably fail.",
                file_type,
            )

        try:
            return await self.client.get_file(file_type, customized_data, self.slave_id)
        except PermissionDenied:
            if self.__username:
                logged_in = self.ensure_logged_in(force=True)

                if not logged_in:
                    _LOGGER.exception("Could not login to read file %x .", file_type)
                    raise

                return await self.client.get_file(
                    file_type,
                    customized_data,
                    self.slave_id,
                )

            # we have no login-credentials available, pass on permission error
            raise

    async def get_latest_optimizer_history_data(
        self,
    ) -> dict[int, OptimizerRealTimeData]:
        """Read the latest Optimizer History Data File from the inverter."""
        # emulates behavior from FusionSolar app when current status of optimizers is queried
        end_time = (await self.client.get(rn.SYSTEM_TIME_RAW, self.slave_id)).value
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

    async def stop(self) -> bool:
        """Stop the bridge."""
        self.stop_heartbeat()

        if self._primary:
            return await self.client.stop()

        return True

    ############################
    # Everything write-related #
    ############################

    async def has_write_permission(self) -> bool | None:
        """Test write permission by getting the time zone and trying to write that same value back to the inverter."""
        try:
            time_zone = await self.client.get(rn.TIME_ZONE, self.slave_id)

            await self.client.set(rn.TIME_ZONE, time_zone.value, self.slave_id)
        except ReadException:
            # A ReadException can occur when connecting via a SmartLogger 3000A.
            # In that case, we do not support writing values at all.
            return None
        except PermissionDenied:
            return False
        else:
            return True

    async def ensure_logged_in(self, *, force=False) -> bool:
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

        async def heartbeat():
            while self.__heartbeat_enabled:
                try:
                    self.__heartbeat_enabled = await self.client.heartbeat(
                        self.slave_id,
                    )
                    await asyncio.sleep(HEARTBEAT_INTERVAL)
                except HuaweiSolarException as err:  # noqa: PERF203
                    _LOGGER.warning("Heartbeat stopped because of, %s", err)
                    self.__heartbeat_enabled = False

        self.__heartbeat_enabled = True
        self.__heartbeat_task = asyncio.create_task(heartbeat())

    async def set(self, name: str, value) -> bool:
        """Set a register to a certain value."""
        logged_in = await self.ensure_logged_in()  # we must login again before trying to set the value

        if not logged_in:
            _LOGGER.warning("Could not login, setting, %s will probably fail.", name)

        if self.__heartbeat_enabled:
            try:
                await self.client.heartbeat(self.slave_id)
            except HuaweiSolarException:
                _LOGGER.warning("Failed to perform heartbeat before write")

        try:
            return await self.client.set(name, value, slave=self.slave_id)
        except PermissionDenied:
            if self.__username:
                logged_in = await self.ensure_logged_in(force=True)

                if not logged_in:
                    _LOGGER.exception("Could not login to set %s .", name)
                    raise

                # Force a heartbeat first when connected with username/password credentials
                await self.client.heartbeat(self.slave_id)

                return await self.client.set(name, value, slave=self.slave_id)

            # we have no login-credentials available, pass on permission error
            raise

    @property
    def battery_type(self) -> rv.StorageProductModel:
        """The battery type present on this inverter."""
        if self.battery_1_type != rv.StorageProductModel.NONE:
            return self.battery_1_type
        return self.battery_2_type
