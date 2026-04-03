"""Huawei SmartLogger device support."""

from huawei_solar import register_names as rn

from .base import HuaweiSolarDevice


class SmartLoggerDevice(HuaweiSolarDevice):
    """A SmartLogger device."""

    software_version: str | None = None

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        return model_name.startswith("SmartLogger")

    async def _populate_additional_fields(self) -> None:
        esn_result = await self.client.get(rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN)
        self.serial_number = esn_result.value
        # model_name is already set by create_device_instance() via constructor
