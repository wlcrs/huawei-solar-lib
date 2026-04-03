"""Definitions of the devices supported by this library."""

from logging import getLogger

from tmodbus.exceptions import IllegalDataAddressError

from huawei_solar import register_names as rn
from huawei_solar.exceptions import DeviceDetectionError
from huawei_solar.modbus_client import AsyncHuaweiSolarClient

from .base import HuaweiSolarDevice, HuaweiSolarDeviceWithLogin
from .emma import EMMADevice
from .scharger import SChargerDevice
from .sdongle import SDongleDevice
from .smartlogger import SmartLoggerDevice
from .sun2000 import SUN2000Device

_LOGGER = getLogger(__name__)

DEFAULT_SDONGLE_UNIT_ID = 100


def get_device_class_for_model(model_name: str) -> type[HuaweiSolarDevice]:
    """Get the device class for the given model name."""
    for candidate_bridge_class in [SUN2000Device, EMMADevice, SChargerDevice, SDongleDevice, SmartLoggerDevice]:
        if candidate_bridge_class.supports_device(model_name):
            return candidate_bridge_class

    _LOGGER.warning("Unknown product model '%s'. Defaulting to a SUN2000 device.", model_name)

    # Default to SUN2000Bridge if no specific match is found
    return SUN2000Device


async def detect_device_type(client: AsyncHuaweiSolarClient) -> tuple[type[HuaweiSolarDevice], str]:
    """Detect the type of the connected device."""

    async def _detect_sdongle() -> bool:
        try:
            device_search_status = (await client.get(rn.SDONGLE_DEVICE_SEARCH_STATUS)).value
        except IllegalDataAddressError:
            _LOGGER.warning("Failed to detect device type for unit ID %d.", DEFAULT_SDONGLE_UNIT_ID)
            return False
        else:
            _LOGGER.debug(
                "Successfully retrieved SDongle 'device search status' register for unit ID %d: %s",
                DEFAULT_SDONGLE_UNIT_ID,
                device_search_status,
            )
            return True

    # Unit ID 100 is typically used by an SDongle. Fast track checking for that.
    if client.unit_id == DEFAULT_SDONGLE_UNIT_ID and await _detect_sdongle():
        return SDongleDevice, "SDongle"

    try:
        model_name: str = (await client.get(rn.MODEL_NAME)).value
    except IllegalDataAddressError:
        _LOGGER.info("MODEL_NAME is an illegal data address for unit ID %d.", client.unit_id)
    else:
        return get_device_class_for_model(model_name), model_name

    try:
        # The SmartLogger does not have a MODEL_NAME register, so we need to detect it differently
        smartlogger_device_name: str = (await client.get(rn.SMARTLOGGER_DEVICE_NAME)).value
    except IllegalDataAddressError:
        _LOGGER.info("SMARTLOGGER_DEVICE_NAME is an illegal data address for unit ID %d.", client.unit_id)
    else:
        return get_device_class_for_model(smartlogger_device_name), smartlogger_device_name

    if await _detect_sdongle():
        return SDongleDevice, "SDongle"

    # If we reach here, we couldn't detect the device type
    _LOGGER.warning("Failed to detect device type.")
    msg = "Unable to detect the device type. The device may not be supported or may not be responding correctly."
    raise DeviceDetectionError(msg)


async def create_device_instance(client: AsyncHuaweiSolarClient) -> HuaweiSolarDevice:
    """Detect the connected device and create the appropriate instance."""
    device_type, model_name = await detect_device_type(client)
    return await device_type.create(
        client,
        model_name=model_name,
        primary_device=None,  # we are creating the primary device!
    )


async def create_sub_device_instance(
    primary_device: HuaweiSolarDevice,
    unit_id: int,
) -> HuaweiSolarDevice:
    """Create a HuaweiSolarDevice instance for extra servers accessible as subdevices via an existing device."""
    if primary_device.client.unit_id == unit_id:
        msg = "The unit_id for the sub-device must be different from the primary device's unit_id."
        raise ValueError(msg)

    sub_client = primary_device.client.for_unit_id(unit_id)
    device_type, model_name = await detect_device_type(sub_client)
    return await device_type.create(
        sub_client,
        model_name=model_name,
        primary_device=primary_device,
    )


__all__ = [
    "EMMADevice",
    "HuaweiSolarDevice",
    "HuaweiSolarDeviceWithLogin",
    "SChargerDevice",
    "SDongleDevice",
    "SUN2000Device",
    "SmartLoggerDevice",
    "create_device_instance",
    "create_sub_device_instance",
]
