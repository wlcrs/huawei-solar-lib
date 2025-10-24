"""Higher-level access to Huawei Solar inverters."""

import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.exceptions import (
    HuaweiSolarException,
    ReadException,
)
from huawei_solar.files import (
    OptimizerRealTimeData,
    OptimizerRealTimeDataFile,
    OptimizerSystemInformation,
    OptimizerSystemInformationDataFile,
)
from huawei_solar.register_definitions import Result, TimestampRegister
from huawei_solar.registers import METER_REGISTERS, REGISTERS

from .base import HuaweiSolarDeviceWithLogin
from .emma import EMMADevice
from .smartlogger import SmartLoggerDevice

_LOGGER = logging.getLogger(__name__)

MAX_NUMBER_OF_PV_STRINGS = 24


class SUN2000Device(HuaweiSolarDeviceWithLogin):
    """A Huawei SUN2000 device."""

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
                "SUN",
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
        )
        self.serial_number = serial_number_result.value
        self.product_number = pn_result.value
        self.firmware_version = firmware_version_result.value
        self.software_version = software_version_result.value

        self.pv_string_count = (await self.get(rn.NB_PV_STRINGS)).value
        self._pv_registers = _compute_pv_registers(self.pv_string_count)

        # some inverters throw an IllegalAddress exception when accessing this address
        with suppress(ReadException):
            self.has_optimizers = (await self.get(rn.NB_OPTIMIZERS)).value

        with suppress(ReadException):
            self.battery_1_type = (await self.get(rn.STORAGE_UNIT_1_PRODUCT_MODEL)).value

        with suppress(ReadException):
            self.battery_2_type = (await self.get(rn.STORAGE_UNIT_2_PRODUCT_MODEL)).value

        if (
            self.battery_1_type is not rv.StorageProductModel.NONE
            and self.battery_2_type is not rv.StorageProductModel.NONE
            and self.battery_1_type != self.battery_2_type
        ):
            _LOGGER.warning(
                "Detected two batteries of a different type. This can lead to unexpected behavior",
            )

        if self.battery_type != rv.StorageProductModel.NONE and (
            self.primary_device is None or not isinstance(self.primary_device, (EMMADevice, SmartLoggerDevice))
        ):
            try:
                await self.get(rn.STORAGE_CAPACITY_CONTROL_MODE)
                self.supports_capacity_control = True
            except ReadException:
                _LOGGER.debug("Storage capacity control as it is not supported by device %d", self.client.unit_id)
                self.supports_capacity_control = False

        with suppress(ReadException):
            self.power_meter_online = (await self.get(rn.METER_STATUS)).value == rv.MeterStatus.NORMAL

        # Caveat: if the inverter is in offline mode, and the power meter is thus offline,
        # we will incorrectly detect that no power meter is present.
        if self.power_meter_online:
            self.power_meter_type = (await self.get(rn.METER_TYPE)).value

        self._dst = (await self.get(rn.DAYLIGHT_SAVING_TIME)).value
        self._time_zone = (await self.get(rn.TIME_ZONE)).value

    def _handle_batch_read_error(
        self,
        queried_register_names: list[rn.RegisterName],
        exc: HuaweiSolarException,
    ) -> None:
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

    def _detect_state_changes(self, new_values: dict[rn.RegisterName, Result[Any]]) -> None:
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

    async def _filter_registers(self, register_names: list[rn.RegisterName]) -> list[rn.RegisterName]:
        result = register_names

        # Filter out power meter registers if the power meter is offline
        power_meter_register_names = {rn for rn in register_names if rn in METER_REGISTERS}
        if power_meter_register_names:
            # Do a check of the METER_STATUS register only if the power meter is marked offline
            if not self.power_meter_online:
                power_meter_online_register = await self.get(rn.METER_STATUS)
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

    def _transform_register_values(self, register_name: rn.RegisterName, result: Result[Any]) -> Result[Any]:
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
        if self.primary_device and isinstance(self.primary_device, EMMADevice):
            # Inverters don't return their own system time when connected via EMMA.
            # Instead, we need to read the system time from the EMMA device.

            return (await self.primary_device.get(rn.EMMA_SYSTEM_TIME)).value  # type: ignore[no-any-return]

        return (await self.get(rn.SYSTEM_TIME_RAW)).value  # type: ignore[no-any-return]

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

        file_data = await self.read_file(
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
        file_data = await self.read_file(OptimizerSystemInformationDataFile.FILE_TYPE)
        system_information_data = OptimizerSystemInformationDataFile(file_data)

        return {opt.optimizer_address: opt for opt in system_information_data.optimizers}

    @property
    def battery_type(self) -> rv.StorageProductModel:
        """The battery type present on this inverter."""
        if self.battery_1_type != rv.StorageProductModel.NONE:
            return self.battery_1_type
        return self.battery_2_type


def _compute_pv_registers(pv_string_count: int) -> list[str]:
    """Get the registers for the PV strings which were detected from the inverter."""
    assert 1 <= pv_string_count <= MAX_NUMBER_OF_PV_STRINGS

    pv_registers = []
    for idx in range(1, pv_string_count + 1):
        pv_registers.extend(
            [
                getattr(rn, f"PV_{idx:02}_VOLTAGE"),
                getattr(rn, f"PV_{idx:02}_CURRENT"),
            ],
        )
    return pv_registers
