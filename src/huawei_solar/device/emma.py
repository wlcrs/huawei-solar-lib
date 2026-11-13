"""Huawei EMMA (SmartHEMS) device support."""

from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from huawei_solar import register_names as rn
from huawei_solar.exceptions import ReadException
from huawei_solar.register_definitions import Result

from .base import HuaweiSolarDevice


class EMMADevice(HuaweiSolarDevice):
    """A Huawei EMMA device.

    Also called 'SmartHEMS' by Huawei.
    """

    software_version: str
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

        self.model_name = (await self.get(rn.EMMA_MODEL)).value

        with suppress(ReadException):
            local_time_result, system_time_result = await self.client.get_multiple(
                [rn.EMMA_LOCAL_TIME, rn.EMMA_SYSTEM_TIME],
            )
            if local_time_result.value is not None and system_time_result.value is not None:
                diff_minutes = round((local_time_result.value - system_time_result.value).total_seconds() / 60)
                self._utc_offset = timedelta(minutes=diff_minutes)
                self._adopt_matching_host_timezone(self._utc_offset)

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
