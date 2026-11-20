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
    supports_capacity_control: bool = False
    supports_power_limited_grid_connection: bool = True
    supports_di_scheduling: bool = True
    _utc_offset: timedelta | None = None

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

    async def _populate_feature_support(self) -> None:
        """Check site battery model and feature flags to determine supported capabilities."""
        try:
            battery_type = (await self.client.get(rn.EMMA_BATTERY_PRODUCT_MODEL)).value
            self.battery_type = battery_type if battery_type is not None else rv.StorageProductModel.NONE
        except ReadException:
            _LOGGER.debug("EMMA battery product model not supported by device %d", self.client.unit_id)
            self.battery_type = rv.StorageProductModel.NONE

        feature_mask_30164: rv.EmmaFeatureMask30164 | None = None
        try:
            feature_mask_30164 = (await self.client.get(rn.EMMA_FEATURE_MASK_30164)).value
        except ReadException:
            _LOGGER.debug("EMMA feature mask 30164 not supported by device %d", self.client.unit_id)

        if feature_mask_30164 is not None:
            # Register 30164 is an inverted (hide/disable) bitmask: bit == 1 disables the feature.
            self.supports_power_limited_grid_connection = not bool(
                feature_mask_30164 & rv.EmmaFeatureMask30164.POWER_LIMITED_GRID_CONNECTION
            )
            self.supports_di_scheduling = not bool(feature_mask_30164 & rv.EmmaFeatureMask30164.DI_SCHEDULING)
        else:
            self.supports_power_limited_grid_connection = True
            self.supports_di_scheduling = True

        if self.battery_type != rv.StorageProductModel.HUAWEI_LUNA2000:
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
