"""Huawei EMMA (SmartHEMS) device support."""

from huawei_solar import register_names as rn

from .base import HuaweiSolarDevice
from .group import DeviceGroupMixin


class EMMADevice(HuaweiSolarDevice, DeviceGroupMixin):
    """A Huawei EMMA device.

    Also called 'SmartHEMS' by Huawei.
    """

    software_version: str

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
