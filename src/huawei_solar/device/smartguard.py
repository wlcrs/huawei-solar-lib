"""Huawei SmartGuard device support."""

from contextlib import suppress

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.exceptions import ReadException

from .base import HuaweiSolarDevice


class SmartGuardDevice(HuaweiSolarDevice):
    """A Huawei SmartGuard device (whole-home backup switch)."""

    software_version: str | None = None
    phase_type: rv.SmartGuardPhaseType | None = None
    supports_grid_switchover: bool = False

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class supports the given device."""
        return model_name.startswith("SmartGuard")

    async def _populate_additional_fields(self) -> None:
        if not getattr(self, "serial_number", None):
            parent_sn = self.primary_device.serial_number if self.primary_device else "unknown"
            self.serial_number = f"{parent_sn}_smartguard_{self.client.unit_id}"

        # Modbus error responses, decode errors and timeouts are tolerated here: older SmartGuards may not have
        # these registers. A dropped connection must propagate so that the setup is retried instead of creating
        # a SmartGuard without its voltage sensors and switchover.
        with suppress(ReadException, TimeoutError):
            self.software_version = (await self.client.get(rn.SMARTGUARD_SOFTWARE_VERSION)).value or None
        with suppress(ReadException, TimeoutError):
            self.phase_type = (await self.client.get(rn.SMARTGUARD_PHASE_TYPE)).value
        with suppress(ReadException, TimeoutError):
            feature_mask = (await self.client.get(rn.SMARTGUARD_FEATURE_MASK)).value
            self.supports_grid_switchover = feature_mask is not None and bool(feature_mask & 1)
