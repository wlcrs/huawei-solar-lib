"""Huawei SCharger device support."""

from contextlib import suppress

from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.exceptions import ReadException

from .base import HuaweiSolarDevice


class SChargerDevice(HuaweiSolarDevice):
    """An SCharger device."""

    software_version: str
    supports_random_delay: bool = True
    """False only when feature mask 4 is readable and does not offer random-delay charging (40200 / 40202)."""

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

        # The FusionSolar app only shows random-delay charging when bit 2 of feature mask 4 is set. An unreadable mask
        # keeps the settings, as before this check existed.
        with suppress(ReadException, TimeoutError):
            feature_mask_4 = (await self.client.get(rn.CHARGER_FEATURE_MASK_4)).value
            if isinstance(feature_mask_4, int):
                self.supports_random_delay = bool(feature_mask_4 & rv.ChargerFeatureMask4.RANDOM_DELAY_AND_UNDERVOLTAGE)
