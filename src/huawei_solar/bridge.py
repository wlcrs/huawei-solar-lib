"""Higher-level access to Huawei Solar inverters."""
from __future__ import annotations

import asyncio
import logging
from threading import Thread
import time

import huawei_solar.register_names as rn
import huawei_solar.register_values as rv
from huawei_solar.exceptions import (
    HuaweiSolarException,
    InvalidCredentials,
    PermissionDenied,
    ReadException,
)
from huawei_solar.huawei_solar import AsyncHuaweiSolar, Result

_LOGGER = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15


class HuaweiSolarBridge:
    """The HuaweiSolarBridge exposes a higher-level interface than AsyncHuaweiSolar,
    making it easier to interact with a Huawei Solar inverter."""

    def __init__(
        self,
        client: AsyncHuaweiSolar,
        primary: bool,
        slave_id: int | None = None,
        username: str | None = None,
        password: str | None = None,
        loop=None,
    ):

        self.client = client
        self._primary = primary
        self.slave_id = slave_id or 0

        self.username = username
        self.password = password
        self.has_write_access = (
            username and password
        )  # setup will have failed if username and password are not correct

        self.model_name: str | None = None
        self.serial_number: str | None = None
        self.pv_string_count: int = 0

        self.has_optimizers = False
        self.battery_1_type: rv.StorageProductModel = rv.StorageProductModel.NONE
        self.battery_2_type: rv.StorageProductModel = rv.StorageProductModel.NONE
        self.power_meter_type: rv.MeterType | None = None

        self._pv_registers = None

        self._loop = loop or asyncio.get_running_loop()
        self.__enable_heartbeat = False
        self.__heartbeat_thread: Thread | None = None

    @classmethod
    async def create(
        cls,
        host: str,
        port: int = 502,
        slave_id: int = 0,
        username: str | None = None,
        password: str | None = None,
        loop=None,
    ):
        """Creates a HuaweiSolarBridge instance for the inverter hosting the modbus interface."""
        client = await AsyncHuaweiSolar.create(host, port, slave_id, loop=loop)

        start_heartbeat = False
        if username and password:
            await client.login(username, password)
            start_heartbeat = True

        bridge = cls(
            client, primary=True, username=username, password=password, loop=loop
        )
        await HuaweiSolarBridge.__populate_fields(bridge)

        if start_heartbeat:
            bridge.start_heartbeat()
        return bridge

    @classmethod
    async def create_extra_slave(cls, client: AsyncHuaweiSolar, slave_id: int):
        """Creates a HuaweiSolarBridge instance for extra slaves accessible via the given AsyncHuaweiSolar instance."""
        assert client.slave != slave_id

        bridge = cls(client, primary=False, slave_id=slave_id)
        await HuaweiSolarBridge.__populate_fields(bridge)
        return bridge

    @staticmethod
    async def __populate_fields(bridge: "HuaweiSolarBridge"):

        model_name_result, serial_number_result = await bridge.client.get_multiple(
            [rn.MODEL_NAME, rn.SERIAL_NUMBER], bridge.slave_id
        )
        bridge.model_name = model_name_result.value
        bridge.serial_number = serial_number_result.value

        bridge.pv_string_count = (
            await bridge.client.get(rn.NB_PV_STRINGS, bridge.slave_id)
        ).value
        bridge._compute_pv_registers()  # pylint: disable=protected-access

        try:
            bridge.has_optimizers = (
                await bridge.client.get(rn.NB_OPTIMIZERS, bridge.slave_id)
            ).value
        except ReadException:  # some inverters throw an IllegalAddress exception when accessing this address
            pass

        try:
            has_power_meter = (
                await bridge.client.get(rn.METER_STATUS, bridge.slave_id)
            ).value == rv.MeterStatus.NORMAL
            if has_power_meter:
                bridge.power_meter_type = (
                    await bridge.client.get(rn.METER_TYPE, bridge.slave_id)
                ).value
        except ReadException:
            pass

        try:
            bridge.battery_1_type = (
                await bridge.client.get(
                    rn.STORAGE_UNIT_1_PRODUCT_MODEL, bridge.slave_id
                )
            ).value
        except ReadException:
            pass
        try:
            bridge.battery_2_type = (
                await bridge.client.get(
                    rn.STORAGE_UNIT_2_PRODUCT_MODEL, bridge.slave_id
                )
            ).value
        except ReadException:
            pass

        if (
            bridge.battery_1_type != rv.StorageProductModel.NONE
            and bridge.battery_2_type != rv.StorageProductModel.NONE
            and bridge.battery_1_type != bridge.battery_2_type
        ):
            _LOGGER.warning(
                "Detected two batteries of a different type. This can lead to unexpected behavior"
            )

    async def update(self) -> dict[str, Result]:
        """Receive an update for all (interesting) available registers"""

        async def _get_multiple_to_dict(names: list[str]) -> dict[str, Result]:
            return dict(
                zip(names, await self.client.get_multiple(names, self.slave_id))
            )

        result = await _get_multiple_to_dict(INVERTER_REGISTERS)

        result.update(await _get_multiple_to_dict(self._pv_registers))

        if self.has_optimizers:
            result.update(await _get_multiple_to_dict(OPTIMIZER_REGISTERS))

        if self.power_meter_type is not None:
            result.update(await _get_multiple_to_dict(POWER_METER_REGISTERS))

        if self.battery_1_type is not None or self.battery_2_type is not None:
            result.update(await _get_multiple_to_dict(ENERGY_STORAGE_REGISTERS))

        return result

    def _compute_pv_registers(self):
        assert 1 <= self.pv_string_count <= 24

        self._pv_registers = []
        for idx in range(1, self.pv_string_count + 1):
            self._pv_registers.extend(
                [
                    getattr(rn, f"PV_{idx:02}_VOLTAGE"),
                    getattr(rn, f"PV_{idx:02}_CURRENT"),
                ]
            )

    def __heartbeat(self):

        while self.__enable_heartbeat:
            try:
                heartbeat_future = asyncio.run_coroutine_threadsafe(
                    self.client.heartbeat(self.slave_id), loop=self._loop
                )
                self.__enable_heartbeat = heartbeat_future.result()

                time.sleep(HEARTBEAT_INTERVAL)
            except HuaweiSolarException as err:
                _LOGGER.warning("Heartbeat stopped because of, %s", err)
                self.__enable_heartbeat = False
                raise err

    def start_heartbeat(self):
        """Start the heartbeat thread to stay logged in."""
        if self.__heartbeat_thread is not None and self.__heartbeat_thread.is_alive():
            raise HuaweiSolarException("Cannot start heartbeat as it's still running!")

        self.__enable_heartbeat = True

        self.__heartbeat_thread = Thread(
            name=f"{self.serial_number}-heartbeat", target=self.__heartbeat
        )
        self.__heartbeat_thread.start()

    async def set(self, name: str, value):
        """Sets a register to a certain value."""

        try:
            return await self.client.set(name, value, slave=self.slave_id)
        except PermissionDenied:
            # check if we can login, and try again

            if self.username and self.password:
                if not self.client.login():
                    raise InvalidCredentials(  # pylint: disable=raise-missing-from
                        f"Could not login with '{self.username}'"
                    )

                return await self.client.set(name, value, slave=self.slave_id)

    async def stop(self):
        """Stop the bridge."""
        self.__enable_heartbeat = False

        if self._primary:
            return await self.client.stop()

        return True


# Registers which should always be read
INVERTER_REGISTERS = [
    rn.INPUT_POWER,
    rn.LINE_VOLTAGE_A_B,
    rn.LINE_VOLTAGE_B_C,
    rn.LINE_VOLTAGE_C_A,
    rn.PHASE_A_VOLTAGE,
    rn.PHASE_B_VOLTAGE,
    rn.PHASE_C_VOLTAGE,
    rn.PHASE_A_CURRENT,
    rn.PHASE_B_CURRENT,
    rn.PHASE_C_CURRENT,
    rn.DAY_ACTIVE_POWER_PEAK,
    rn.ACTIVE_POWER,
    rn.REACTIVE_POWER,
    rn.POWER_FACTOR,
    rn.GRID_FREQUENCY,
    rn.EFFICIENCY,
    rn.INTERNAL_TEMPERATURE,
    rn.INSULATION_RESISTANCE,
    rn.DEVICE_STATUS,
    rn.FAULT_CODE,
    rn.STARTUP_TIME,
    rn.SHUTDOWN_TIME,
    rn.ACCUMULATED_YIELD_ENERGY,
    rn.DAILY_YIELD_ENERGY,
]

# Registers that should be read if optimizers are present
OPTIMIZER_REGISTERS = [rn.NB_ONLINE_OPTIMIZERS]

# Registers that should be read if a power meter is present
POWER_METER_REGISTERS = [
    rn.GRID_A_VOLTAGE,
    rn.GRID_B_VOLTAGE,
    rn.GRID_C_VOLTAGE,
    rn.ACTIVE_GRID_A_CURRENT,
    rn.ACTIVE_GRID_B_CURRENT,
    rn.ACTIVE_GRID_C_CURRENT,
    rn.POWER_METER_ACTIVE_POWER,
    rn.POWER_METER_REACTIVE_POWER,
    rn.ACTIVE_GRID_POWER_FACTOR,
    rn.ACTIVE_GRID_FREQUENCY,
    rn.GRID_EXPORTED_ENERGY,
    rn.GRID_ACCUMULATED_ENERGY,
    rn.GRID_ACCUMULATED_REACTIVE_POWER,
    rn.METER_TYPE,
    rn.ACTIVE_GRID_A_B_VOLTAGE,
    rn.ACTIVE_GRID_B_C_VOLTAGE,
    rn.ACTIVE_GRID_C_A_VOLTAGE,
    rn.ACTIVE_GRID_A_POWER,
    rn.ACTIVE_GRID_B_POWER,
    rn.ACTIVE_GRID_C_POWER,
]

# Registers that should be read if a battery is present
ENERGY_STORAGE_REGISTERS = [
    rn.STORAGE_STATE_OF_CAPACITY,
    rn.STORAGE_RUNNING_STATUS,
    rn.STORAGE_BUS_VOLTAGE,
    rn.STORAGE_BUS_CURRENT,
    rn.STORAGE_CHARGE_DISCHARGE_POWER,
    rn.STORAGE_TOTAL_CHARGE,
    rn.STORAGE_TOTAL_DISCHARGE,
    rn.STORAGE_CURRENT_DAY_CHARGE_CAPACITY,
    rn.STORAGE_CURRENT_DAY_DISCHARGE_CAPACITY,
]
