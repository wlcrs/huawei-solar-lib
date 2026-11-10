"""Huawei SmartGuard device support."""

from .base import HuaweiSolarDevice


class SmartGuardDevice(HuaweiSolarDevice):
    """A Huawei SmartGuard device (whole-home backup switch)."""

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class supports the given device."""
        return model_name.startswith("SmartGuard")

    async def _populate_additional_fields(self) -> None:
        if not getattr(self, "serial_number", None):
            parent_sn = self.primary_device.serial_number if self.primary_device else "unknown"
            self.serial_number = f"{parent_sn}_smartguard_{self.client.unit_id}"
