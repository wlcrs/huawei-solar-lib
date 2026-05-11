"""Definitions of the devices supported by this library."""

from logging import getLogger
from typing import Any

from tmodbus.exceptions import IllegalDataAddressError, IllegalDataValueError

from huawei_solar import register_names as rn
from huawei_solar.exceptions import DeviceDetectionError, ReadException
from huawei_solar.modbus_client import AsyncHuaweiSolarClient

from .base import HuaweiSolarDevice, HuaweiSolarDeviceWithLogin
from .emma import EMMADevice
from .meter import MeterDevice
from .scharger import SChargerDevice
from .sdongle import SDongleDevice
from .smartlogger import SmartLoggerDevice
from .sun2000 import SUN2000Device

_LOGGER = getLogger(__name__)

DEFAULT_SDONGLE_UNIT_ID = 100


async def _try_read_register(client: AsyncHuaweiSolarClient, register: rn.RegisterName) -> Any | None:  # noqa: ANN401
    """Read a register, returning ``None`` if the device reports it as inaccessible.

    Re-raises any other modbus or transport error so genuine failures still surface.
    """
    try:
        return (await client.get(register)).value
    except ReadException as err:
        # Modbus exception codes returned by devices when a register simply isn't
        # accessible. Different firmwares pick one or the other for the same condition,
        # so probing logic has to treat both as "fall through to the next probe".
        if err.modbus_exception_code in {IllegalDataValueError.error_code, IllegalDataAddressError.error_code}:
            return None

        # re-raise any other exception that occurred
        raise


def get_device_class_for_model(model_name: str) -> type[HuaweiSolarDevice]:
    """Get the device class for the given model name."""
    for candidate_bridge_class in [
        SUN2000Device,
        EMMADevice,
        SChargerDevice,
        SDongleDevice,
        SmartLoggerDevice,
        MeterDevice,
    ]:
        if candidate_bridge_class.supports_device(model_name):
            return candidate_bridge_class

    _LOGGER.warning("Unknown product model '%s'. Defaulting to a SUN2000 device.", model_name)

    # Default to SUN2000Bridge if no specific match is found
    return SUN2000Device


async def detect_device_type(client: AsyncHuaweiSolarClient) -> tuple[type[HuaweiSolarDevice], str]:
    """Detect the type of the connected device."""

    async def _detect_sdongle() -> bool:
        device_search_status = await _try_read_register(client, rn.SDONGLE_DEVICE_SEARCH_STATUS)
        if device_search_status is None:
            _LOGGER.warning("Failed to detect device type for unit ID %d.", DEFAULT_SDONGLE_UNIT_ID)
            return False
        _LOGGER.debug(
            "Successfully retrieved SDongle 'device search status' register for unit ID %d: %s",
            DEFAULT_SDONGLE_UNIT_ID,
            device_search_status,
        )
        return True

    # Unit ID 100 is typically used by an SDongle. Fast track checking for that.
    if client.unit_id == DEFAULT_SDONGLE_UNIT_ID and await _detect_sdongle():
        return SDongleDevice, "SDongle"

    model_name = await _try_read_register(client, rn.MODEL_NAME)
    if model_name is not None:
        return get_device_class_for_model(model_name), model_name
    _LOGGER.info("MODEL_NAME is an illegal data address for unit ID %d.", client.unit_id)

    # The SmartLogger does not have a MODEL_NAME register, so we need to detect it differently.
    #
    # Some SmartLogger firmwares (e.g. SmartLogger3000A) expose neither MODEL_NAME nor
    # SMARTLOGGER_DEVICE_NAME, but still respond to the equipment serial number register.
    # A successful read there is a strong enough signal to identify the device as a
    # SmartLogger; SmartLoggerDevice.supports_device() accepts any name that starts
    # with "SmartLogger", so the generic model string keeps the contract.
    if (await _try_read_register(client, rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN)) is not None:
        _LOGGER.info("Detected SmartLogger via ESN register for unit ID %d.", client.unit_id)

        # fallback for when SMARTLOGGER_DEVICE_NAME is not available
        smartlogger_device_name = (await _try_read_register(client, rn.SMARTLOGGER_DEVICE_NAME)) or "SmartLogger"

        return SmartLoggerDevice, smartlogger_device_name
    _LOGGER.info("SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN unavailable for unit ID %d.", client.unit_id)

    # Power meters connected to a SmartLogger do not expose any of the identifying
    # registers above, but they do answer the meter-telemetry block (see Huawei
    # SmartLogger ModBus Interface Definitions, Issue 35, Table 2-5). Active power
    # at register 32278 is a reliable probe: SUN2000 inverters do not define it,
    # and the SmartLogger itself does not aggregate meter data at its own slave.
    if await _try_read_register(client, rn.SMARTLOGGER_EXTERNAL_METER_ACTIVE_POWER) is not None:
        _LOGGER.info("Detected power meter via meter telemetry probe for unit ID %d.", client.unit_id)
        return MeterDevice, "PowerMeter"
    _LOGGER.info("Meter telemetry probe unavailable for unit ID %d.", client.unit_id)

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
    "MeterDevice",
    "SChargerDevice",
    "SDongleDevice",
    "SUN2000Device",
    "SmartLoggerDevice",
    "create_device_instance",
    "create_sub_device_instance",
]
