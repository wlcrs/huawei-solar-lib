"""Huawei SCharger device support."""

from huawei_solar import register_names as rn

from .base import HuaweiSolarDevice


class SChargerDevice(HuaweiSolarDevice):
    """An SCharger device."""

    software_version: str

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        return model_name.startswith("FusionCharge")

    async def _populate_additional_fields(self) -> None:
        (
            serial_number_result,
            software_version_result,
        ) = await self.client.get_multiple(
            [
                rn.CHARGER_ESN,
                rn.CHARGER_SOFTWARE_VERSION,
            ],
        )
        self.serial_number = serial_number_result.value
        self.software_version = software_version_result.value

        self.model_name = (await self.client.get(rn.CHARGER_MODEL)).value
