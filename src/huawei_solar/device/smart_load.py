"""Huawei SmartLoad device support."""

from contextlib import suppress

from huawei_solar import register_names as rn
from huawei_solar.exceptions import ReadException

from .base import HuaweiSolarDevice


class SmartLoadDevice(HuaweiSolarDevice):
    """A load switched by the EMMA, for example via its DO port."""

    name: str | None = None

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class supports the given device."""
        return model_name.startswith("SmartLoad")

    async def _populate_additional_fields(self) -> None:
        self.model_name = "SmartLoad"

        # Register 30000 holds the name given in the FusionSolar app, not a model name.
        with suppress(ReadException, TimeoutError):
            self.name = (await self.client.get(rn.SMARTLOAD_NAME)).value or None

        if not getattr(self, "serial_number", None):
            with suppress(ReadException, TimeoutError):
                if serial_number := (await self.client.get(rn.SMARTLOAD_SERIAL_NUMBER)).value:
                    self.serial_number = serial_number
        if not getattr(self, "serial_number", None):
            parent_sn = self.primary_device.serial_number if self.primary_device else "unknown"
            self.serial_number = f"{parent_sn}_smartload_{self.client.unit_id}"
