"""Huawei EMMA (SmartHEMS) device support."""

import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.exceptions import ReadException
from huawei_solar.register_definitions import Result

from .base import HuaweiSolarDevice

_LOGGER = logging.getLogger(__name__)


class EMMADevice(HuaweiSolarDevice):
    """A Huawei EMMA device.

    Also called 'SmartHEMS' by Huawei.
    """

    software_version: str
    battery_type: rv.StorageProductModel = rv.StorageProductModel.NONE
    has_battery: bool = False
    supports_capacity_control: bool = False
    supports_power_limited_grid_connection: bool = True
    supports_di_scheduling: bool = True
    supports_charge_from_ac: bool = False
    supports_off_grid_backup_power_soc: bool = False
    supports_seamless_switch: bool = False
    supports_insufficient_backup_time_reminder: bool = False
    _utc_offset: timedelta | None = None

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        return model_name.startswith(("SmartHEMS", "SmartAssistant", "SA4H"))

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
                rn.EMMA_SOFTWARE_VERSION,
            ],
        )
        self.serial_number = serial_number_result.value
        self.software_version = software_version_result.value

        self.model_name = (await self.client.get(rn.EMMA_MODEL)).value

        with suppress(ReadException):
            local_time_result = await self.client.get(rn.EMMA_LOCAL_TIME)
            system_time_result = await self.client.get(rn.EMMA_SYSTEM_TIME)
            if local_time_result.value is not None and system_time_result.value is not None:
                diff_minutes = round((local_time_result.value - system_time_result.value).total_seconds() / 60)
                self._utc_offset = timedelta(minutes=diff_minutes)
                self._adopt_matching_host_timezone(self._utc_offset)

        await self._populate_feature_support()

    async def _probe_battery_presence(self, *, model_supported: bool) -> bool:
        """Fall back to EMMA ESS telemetry registers when 30706 reports NONE or is unsupported."""
        ess_supported = False
        try:
            rated_capacity = (await self.client.get(rn.RATED_ESS_CAPACITY)).value
            ess_supported = True
            if rated_capacity is not None and rated_capacity > 0:
                return True
        except ReadException:
            _LOGGER.debug("EMMA rated ESS capacity not supported by device %d", self.client.unit_id)

        try:
            soc = (await self.client.get(rn.STATE_OF_CAPACITY)).value
            ess_supported = True
            if soc is not None:
                return True
        except ReadException:
            _LOGGER.debug("EMMA state of capacity not supported by device %d", self.client.unit_id)

        # If neither 30706 nor the ESS telemetry registers are supported, assume a battery may be present
        # to preserve backwards compatibility with older firmware.
        return not model_supported and not ess_supported

    async def _read_feature_mask[T](self, register: rn.RegisterName) -> T | None:
        """Read an optional EMMA feature mask register, returning None if unsupported."""
        try:
            return (await self.client.get(register)).value  # type: ignore[no-any-return]
        except ReadException:
            _LOGGER.debug("EMMA feature mask %s not supported by device %d", register, self.client.unit_id)
            return None

    async def _populate_feature_support(self) -> None:
        """Check site battery model and feature flags to determine supported capabilities."""
        model_supported = True
        try:
            battery_type = (await self.client.get(rn.EMMA_BATTERY_PRODUCT_MODEL)).value
            self.battery_type = battery_type if battery_type is not None else rv.StorageProductModel.NONE
        except ReadException:
            _LOGGER.debug("EMMA battery product model not supported by device %d", self.client.unit_id)
            self.battery_type = rv.StorageProductModel.NONE
            model_supported = False

        if self.battery_type != rv.StorageProductModel.NONE:
            self.has_battery = True
        else:
            self.has_battery = await self._probe_battery_presence(model_supported=model_supported)

        feature_mask_30122: rv.EmmaFeatureMask30122 | None = await self._read_feature_mask(rn.EMMA_FEATURE_MASK_30122)
        feature_mask_30124: rv.EmmaFeatureMask30124 | None = await self._read_feature_mask(rn.EMMA_FEATURE_MASK_30124)
        feature_mask_30164: rv.EmmaFeatureMask30164 | None = await self._read_feature_mask(rn.EMMA_FEATURE_MASK_30164)
        feature_mask_30172: rv.EmmaFeatureMask30172 | None = await self._read_feature_mask(rn.EMMA_FEATURE_MASK_30172)

        self.supports_charge_from_ac = (
            self.has_battery
            and feature_mask_30124 is not None
            and bool(feature_mask_30124 & rv.EmmaFeatureMask30124.CHARGE_FROM_AC)
        )
        self.supports_off_grid_backup_power_soc = feature_mask_30172 is not None and bool(
            feature_mask_30172 & rv.EmmaFeatureMask30172.OFF_GRID_BACKUP_POWER_SOC
        )
        self.supports_seamless_switch = feature_mask_30122 is not None and bool(
            feature_mask_30122 & rv.EmmaFeatureMask30122.BACKUP_SEAMLESS_SWITCH
        )
        self.supports_insufficient_backup_time_reminder = self.supports_seamless_switch or (
            feature_mask_30172 is not None
            and bool(feature_mask_30172 & rv.EmmaFeatureMask30172.INSUFFICIENT_BACKUP_TIME_REMINDER)
        )

        if feature_mask_30164 is not None:
            # Register 30164 is an inverted (hide/disable) bitmask: bit == 1 disables the feature.
            self.supports_power_limited_grid_connection = not bool(
                feature_mask_30164 & rv.EmmaFeatureMask30164.POWER_LIMITED_GRID_CONNECTION
            )
            self.supports_di_scheduling = not bool(feature_mask_30164 & rv.EmmaFeatureMask30164.DI_SCHEDULING)
        else:
            self.supports_power_limited_grid_connection = True
            self.supports_di_scheduling = True

        if not self.has_battery or self.battery_type == rv.StorageProductModel.LG_RESU:
            self.supports_capacity_control = False
            return

        if feature_mask_30164 is not None:
            self.supports_capacity_control = not bool(feature_mask_30164 & rv.EmmaFeatureMask30164.CAPACITY_CONTROL)
            return

        # Older EMMA firmware may not expose register 30164 (or may return 0xFFFFFFFF);
        # fall back to probing register 40200 directly.
        try:
            await self.client.get(rn.EMMA_CAPACITY_CONTROL_MODE)
            self.supports_capacity_control = True
        except ReadException:
            _LOGGER.debug("EMMA capacity control not supported by device %d", self.client.unit_id)
            self.supports_capacity_control = False

    def _transform_datetime(self, value: datetime) -> datetime:
        if self._use_host_timezone:
            return super()._transform_datetime(value)
        if self._utc_offset:
            value -= self._utc_offset

        return value.astimezone(tz=UTC)

    def _transform_register_values(self, register_name: rn.RegisterName, result: Result[Any]) -> Result[Any]:
        # EMMA_SYSTEM_TIME (40470) is already in true UTC; only EMMA_LOCAL_TIME (31003) holds local wall-clock time.
        if register_name == rn.EMMA_LOCAL_TIME and result.value is not None:
            assert isinstance(result.value, datetime)
            return Result(self._transform_datetime(result.value), result.unit)

        return result
