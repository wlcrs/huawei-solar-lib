"""Huawei SmartAcGun device support."""

from contextlib import suppress

from huawei_solar import register_names as rn
from huawei_solar.exceptions import HuaweiSolarException, ReadException

from .base import HuaweiSolarDevice


class SmartAcGunDevice(HuaweiSolarDevice):
    """A SmartAcGun device (charging connector)."""

    software_version: str | None = None

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class supports the given device."""
        return model_name.startswith("SmartAcGun")

    async def _populate_additional_fields(self) -> None:
        self.model_name = "SmartAcGun"
        parent_sn = self.primary_device.serial_number if self.primary_device else "unknown"

        gun_num: int | None = None
        with suppress(HuaweiSolarException, ReadException):
            gun_num = (await self.get(rn.CHARGER_GUN_NUMBER)).value

        self.serial_number = f"{parent_sn}_gun_{gun_num or self.client.unit_id}"

        with suppress(HuaweiSolarException, ReadException):
            self.software_version = (await self.get(rn.CHARGER_SOFTWARE_VERSION)).value
