"""Definitions of the devices supported by this library."""

from logging import getLogger

from huawei_solar import register_names as rn
from huawei_solar.device_discovery import get_device_identifiers
from huawei_solar.exceptions import HuaweiSolarException, ReadException
from huawei_solar.modbus_client import AsyncHuaweiSolarClient

from .base import HuaweiSolarDevice, HuaweiSolarDeviceWithLogin
from .emma import EMMADevice
from .scharger import SChargerDevice
from .sdongle import SDongleDevice
from .smartlogger import SmartLoggerDevice
from .sun2000 import SUN2000Device

_LOGGER = getLogger(__name__)

_SMARTLOGGER_VERSION_PREFIX_MAP = {
    "V300": "SmartLogger3000",
    "V200": "SmartLogger2000",
    "V100": "SmartLogger1000",
}


def _derive_smartlogger_model_name(main_revision_version: str) -> str:
    """Derive the SmartLogger model name from the MEI main revision version string."""
    for prefix, model_name in _SMARTLOGGER_VERSION_PREFIX_MAP.items():
        if main_revision_version.startswith(prefix):
            return model_name

    _LOGGER.warning(
        "Unknown SmartLogger version prefix in '%s'. Defaulting to SmartLogger3000.",
        main_revision_version,
    )
    return "SmartLogger3000"


def get_device_class_for_model(model_name: str) -> type[HuaweiSolarDevice]:
    """Get the device class for the given model name."""
    for candidate_bridge_class in [SUN2000Device, EMMADevice, SChargerDevice, SDongleDevice, SmartLoggerDevice]:
        if candidate_bridge_class.supports_device(model_name):
            return candidate_bridge_class

    _LOGGER.warning("Unknown product model '%s'. Defaulting to a SUN2000 device.", model_name)

    # Default to SUN2000Bridge if no specific match is found
    return SUN2000Device


async def _read_model_name_with_fallback(client: AsyncHuaweiSolarClient) -> tuple[str, str | None]:
    """Read MODEL_NAME, falling back to MEI device identification for SmartLogger.

    Returns a tuple of (model_name, software_version). software_version is only
    set when the model name was derived from MEI identification.
    """
    try:
        model_name: str = (await client.get(rn.MODEL_NAME)).value
        return model_name, None
    except ReadException as exc:
        if exc.modbus_exception_code is not None and exc.modbus_exception_code != 0x03:
            _LOGGER.debug(
                "MODEL_NAME read failed with modbus exception code %#x on unit %d; re-raising",
                exc.modbus_exception_code,
                client.unit_id,
            )
            raise
        _LOGGER.debug(
            "MODEL_NAME register not available on unit %d (modbus_exception_code=%s), "
            "trying MEI device identification",
            client.unit_id,
            hex(exc.modbus_exception_code) if exc.modbus_exception_code is not None else "N/A",
        )
        try:
            device_id = await get_device_identifiers(client)
        except HuaweiSolarException as mei_exc:
            raise ReadException(
                f"Could not identify device at unit {client.unit_id}",
            ) from mei_exc

        if "Smart Logger" not in device_id.product_code:
            msg = (
                f"MODEL_NAME register not available and device is not a SmartLogger "
                f"(product_code={device_id.product_code!r})"
            )
            raise ReadException(msg) from None

        model_name = _derive_smartlogger_model_name(device_id.main_revision_version)
        _LOGGER.info(
            "Identified SmartLogger via MEI: product_code=%r, version=%r -> model_name=%s",
            device_id.product_code,
            device_id.main_revision_version,
            model_name,
        )
        return model_name, device_id.main_revision_version


async def create_device_instance(client: AsyncHuaweiSolarClient) -> HuaweiSolarDevice:
    """Detect the connected device and create the appropriate instance."""
    model_name, software_version = await _read_model_name_with_fallback(client)
    device_class = get_device_class_for_model(model_name)
    device = await device_class.create(
        client,
        model_name=model_name,
        primary_device=None,  # we are creating the primary device!
    )
    if software_version is not None and isinstance(device, SmartLoggerDevice):
        device.software_version = software_version
    return device


async def create_sub_device_instance(
    primary_device: HuaweiSolarDevice,
    unit_id: int,
) -> HuaweiSolarDevice:
    """Create a HuaweiSolarDevice instance for extra servers accessible as subdevices via an existing device."""
    if primary_device.client.unit_id == unit_id:
        msg = "The unit_id for the sub-device must be different from the primary device's unit_id."
        raise ValueError(msg)

    sub_client = primary_device.client.for_unit_id(unit_id)
    model_name, software_version = await _read_model_name_with_fallback(sub_client)
    device_class = get_device_class_for_model(model_name)
    device = await device_class.create(
        sub_client,
        model_name=model_name,
        primary_device=primary_device,
    )
    if software_version is not None and isinstance(device, SmartLoggerDevice):
        device.software_version = software_version
    return device


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
