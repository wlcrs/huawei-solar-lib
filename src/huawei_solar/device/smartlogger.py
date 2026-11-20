"""Huawei SmartLogger device support."""

from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from huawei_solar import register_names as rn
from huawei_solar.exceptions import ReadException
from huawei_solar.register_definitions import Result

from .base import HuaweiSolarDevice


class SmartLoggerDevice(HuaweiSolarDevice):
    """A SmartLogger device."""

    software_version: str | None = None
    _time_zone: int | None = None
    _dst_state: int | None = None
    _dst_offset: int | None = None

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        return model_name.startswith("SmartLogger")

    async def _populate_additional_fields(self) -> None:
        esn_result = await self.client.get(rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN)
        self.serial_number = esn_result.value
        # model_name is already set by create_device_instance() via constructor

        with suppress(ReadException):
            self._time_zone = (await self.client.get(rn.SMARTLOGGER_TIME_ZONE)).value
        with suppress(ReadException):
            self._dst_state = (await self.client.get(rn.SMARTLOGGER_DST_STATE)).value
        with suppress(ReadException):
            self._dst_offset = (await self.client.get(rn.SMARTLOGGER_DST_OFFSET)).value
        self._update_matched_timezone()

    def _update_matched_timezone(self) -> None:
        if self._time_zone is None:
            return
        offset = timedelta(seconds=self._time_zone) + (
            timedelta(minutes=self._dst_offset or 0) if self._dst_state else timedelta(0)
        )
        device_dst = bool(self._dst_state) if self._dst_state is not None else None
        self._adopt_matching_host_timezone(offset, device_dst=device_dst)

    def _detect_state_changes(self, new_values: dict[rn.RegisterName, Result[Any]]) -> None:
        if (
            rn.SMARTLOGGER_TIME_ZONE in new_values
            or rn.SMARTLOGGER_DST_STATE in new_values
            or rn.SMARTLOGGER_DST_OFFSET in new_values
        ):
            if rn.SMARTLOGGER_TIME_ZONE in new_values:
                self._time_zone = new_values[rn.SMARTLOGGER_TIME_ZONE].value
            if rn.SMARTLOGGER_DST_STATE in new_values:
                self._dst_state = new_values[rn.SMARTLOGGER_DST_STATE].value
            if rn.SMARTLOGGER_DST_OFFSET in new_values:
                self._dst_offset = new_values[rn.SMARTLOGGER_DST_OFFSET].value
            self._update_matched_timezone()

    def _transform_datetime(self, value: datetime) -> datetime:
        if self._use_host_timezone:
            return super()._transform_datetime(value)
        if self._time_zone:
            value -= timedelta(seconds=self._time_zone)
        if self._dst_state and self._dst_offset:
            value -= timedelta(minutes=self._dst_offset)

        return value.astimezone(tz=UTC)

    def _transform_register_values(self, register_name: rn.RegisterName, result: Result[Any]) -> Result[Any]:
        # SMARTLOGGER_DATE_TIME (40000) is UTC; only SMARTLOGGER_LOCAL_TIME (40009) is local wall-clock time.
        if register_name == rn.SMARTLOGGER_LOCAL_TIME and result.value is not None:
            assert isinstance(result.value, datetime)
            return Result(self._transform_datetime(result.value), result.unit)

        return result
