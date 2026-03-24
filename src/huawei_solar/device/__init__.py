"""Definitions of the devices supported by this library."""

from logging import getLogger

from huawei_solar import register_names as rn
from huawei_solar.device_discovery import get_device_identifiers
from huawei_solar.exceptions import ReadException
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


async def _identify_endpoint(
    client: AsyncHuaweiSolarClient,
    slave_id: int = 1,
) -> tuple[str, str | None, type[HuaweiSolarDevice], AsyncHuaweiSolarClient]:
    """Identify Huawei Modbus TCP endpoint using proxy-safe register fingerprinting.

    Uses FC 0x03 holding register reads exclusively for identification,
    ensuring compatibility with any Modbus proxy. MEI 0x2B is used only
    as optional enrichment for SmartLogger model/version derivation.

    Probing order:
    1. SmartLogger: reg 65521 at unit_id=0 (device list change number)
    2. EMMA:        reg 30222 at unit_id=0 (model string)
    3. SDongle:     reg 37411 at unit_id=100 (device search status)
    4. Direct:      reg 30000 at slave_id (MODEL_NAME)

    unit_id=0 is only probed for SmartLogger/EMMA (it is the broadcast
    address on SDongle and causes timeouts). unit_id=100 is SDongle's
    documented unicast address.

    Returns (model_name, software_version, device_class, device_client).
    """
    # Step 1: SmartLogger? Read public register 65521 at unit_id=0
    client_0 = client.for_unit_id(0)
    try:
        await client_0.get(rn.SMARTLOGGER_DEVICE_LIST_CHANGE)
    except (ReadException, TimeoutError) as exc:
        _LOGGER.debug("SmartLogger probe failed at unit_id=0: %s: %s", type(exc).__name__, exc)
    else:
        _LOGGER.info("SmartLogger detected via register 65521 at unit_id=0")
        return await _enrich_smartlogger(client_0)

    # Step 2: EMMA? Read model register 30222 at unit_id=0
    try:
        result = await client_0.get(rn.EMMA_MODEL)
    except (ReadException, TimeoutError) as exc:
        _LOGGER.debug("EMMA probe failed at unit_id=0: %s: %s", type(exc).__name__, exc)
    else:
        _LOGGER.info("EMMA detected via register 30222 at unit_id=0: %s", result.value)
        return result.value, None, EMMADevice, client_0

    # Step 3: SDongle? Read device search status 37411 at unit_id=100
    client_100 = client.for_unit_id(100)
    try:
        await client_100.get(rn.SDONGLE_DEVICE_SEARCH_STATUS)
    except (ReadException, TimeoutError) as exc:
        _LOGGER.debug("SDongle probe failed at unit_id=100: %s: %s", type(exc).__name__, exc)
    else:
        _LOGGER.info("SDongle detected via register 37411 at unit_id=100")
        return await _enrich_sdongle(client_100)

    # Step 4: Direct device? Read MODEL_NAME at user-specified slave_id
    client_sid = client.for_unit_id(slave_id)
    try:
        result = await client_sid.get(rn.MODEL_NAME)
    except (ReadException, TimeoutError) as exc:
        msg = (
            f"No Huawei device identified. "
            f"Probed SmartLogger (65521@0), EMMA (30222@0), SDongle (37411@100), "
            f"and MODEL_NAME (30000@{slave_id}). None responded."
        )
        raise ReadException(msg) from exc
    else:
        device_class = get_device_class_for_model(result.value)
        _LOGGER.info("Direct device detected via MODEL_NAME at unit_id=%d: %s", slave_id, result.value)
        return result.value, None, device_class, client_sid


async def _enrich_smartlogger(
    client: AsyncHuaweiSolarClient,
) -> tuple[str, str | None, type[HuaweiSolarDevice], AsyncHuaweiSolarClient]:
    """Enrich SmartLogger identity after positive detection via register 65521."""
    model_name = "SmartLogger"
    software_version = None

    # Try SMARTLOGGER_DEVICE_NAME (65524) — may contain model info
    try:
        name_result = await client.get(rn.SMARTLOGGER_DEVICE_NAME)
        if name_result.value and name_result.value.strip():
            model_name = name_result.value.strip()
    except (ReadException, TimeoutError) as exc:
        _LOGGER.debug("SMARTLOGGER_DEVICE_NAME not available: %s", exc)

    # Optional: MEI 0x2B for precise model derivation (V300→SmartLogger3000)
    # This is the only non-FC03 call; it fails gracefully through proxies
    try:
        device_id = await get_device_identifiers(client)
        if device_id.main_revision_version:
            software_version = device_id.main_revision_version
            model_name = _derive_smartlogger_model_name(software_version)
            _LOGGER.debug(
                "MEI enrichment: version=%s, derived model=%s",
                software_version,
                model_name,
            )
    except Exception:  # noqa: BLE001 — MEI is optional, any failure is acceptable
        _LOGGER.debug(
            "MEI device identification not available (Modbus proxy or unsupported firmware), "
            "using register-based SmartLogger identification only",
        )

    return model_name, software_version, SmartLoggerDevice, client


async def _enrich_sdongle(
    client: AsyncHuaweiSolarClient,
) -> tuple[str, str | None, type[HuaweiSolarDevice], AsyncHuaweiSolarClient]:
    """Enrich SDongle identity after positive detection via register 37411."""
    model_name = "SDongle"

    # Try MODEL_NAME at the SDongle's unit_id (100)
    try:
        result = await client.get(rn.MODEL_NAME)
        if result.value and result.value.strip():
            model_name = result.value.strip()
    except (ReadException, TimeoutError) as exc:
        _LOGGER.debug("SDongle MODEL_NAME not available at unit_id=%d: %s", client.unit_id, exc)

    return model_name, None, SDongleDevice, client


async def create_device_instance(
    client: AsyncHuaweiSolarClient,
    slave_id: int = 1,
) -> HuaweiSolarDevice:
    """Detect the connected device and create the appropriate instance."""
    model_name, software_version, device_class, device_client = await _identify_endpoint(client, slave_id)
    device = await device_class.create(
        device_client,
        model_name=model_name,
        primary_device=None,
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
    result = await sub_client.get(rn.MODEL_NAME)
    model_name = result.value
    device_class = get_device_class_for_model(model_name)
    device = await device_class.create(
        sub_client,
        model_name=model_name,
        primary_device=primary_device,
    )
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
