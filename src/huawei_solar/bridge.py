"""Higher-level access to Huawei Solar inverters."""
from __future__ import annotations

import logging

import huawei_solar.register_names as rn
import huawei_solar.register_values as rv
from huawei_solar.exceptions import ReadException
from huawei_solar.huawei_solar import AsyncHuaweiSolar, Result

_LOGGER = logging.getLogger(__name__)


class HuaweiSolarBridge:
    """The HuaweiSolarBridge exposes a higher-level interface than AsyncHuaweiSolar,
    making it easier to interact with a Huawei Solar inverter."""

    def __init__(
        self, client: AsyncHuaweiSolar, primary: bool, slave_id: int | None = None
    ):

        self.client = client
        self._primary = primary
        self.slave_id = slave_id

        self.model_name: str | None = None
        self.serial_number: str | None = None
        self.pv_string_count: int = 0

        self.has_optimizers = False
        self.battery_1_type: rv.StorageProductModel = rv.StorageProductModel.NONE
        self.battery_2_type: rv.StorageProductModel = rv.StorageProductModel.NONE
        self.power_meter_type: rv.MeterType | None = None

        self._pv_registers = None

    @classmethod
    async def create(cls, host: str, port: int = 502, slave_id: int = 0, loop=None):
        """Creates a HuaweiSolarBridge instance for the inverter hosting the modbus interface."""
        client = await AsyncHuaweiSolar.create(host, port, slave_id, loop=loop)

        bridge = cls(client, primary=True)
        await HuaweiSolarBridge.__populate_fields(bridge)
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

    async def stop(self):
        """Stop the bridge."""
        if self._primary:
            return await self.client.stop()

        _LOGGER.debug("Ignoring stop command as this is not the primary bridge.")
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
