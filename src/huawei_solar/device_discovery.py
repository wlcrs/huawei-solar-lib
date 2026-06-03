"""Device discovery for Huawei inverters."""

import logging
import struct
from dataclasses import dataclass
from typing import Literal

from tmodbus.client import AsyncModbusClient
from tmodbus.exceptions import (
    ModbusConnectionError,
    ModbusResponseError,
    ServerDeviceBusyError,
    ServerDeviceFailureError,
    TModbusError,
)

from huawei_solar.exceptions import ConnectionInterruptedException, ReadException
from huawei_solar.modbus_pdu import PermissionDeniedError

_LOGGER = logging.getLogger(__name__)


DEVICE_INFOS_START_OBJECT_ID = 0x87


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Device information."""

    model: str | None
    software_version: str | None
    interface_protocol_version: str | None
    esn: str | None
    device_id: int | None
    feature_version: str | None
    unknown_field: str | None
    product_type: str | None


@dataclass(frozen=True, slots=True)
class DeviceIdentifier:
    """Device identifier information."""

    vendor: str
    product_code: str
    main_revision_version: str
    other_data: dict[int, bytes]


async def get_device_identifiers(client: AsyncModbusClient) -> DeviceIdentifier:
    """Read the device identifiers from the inverter."""
    objects = await _read_device_identifier_objects(client, 0x01, 0x00)

    return DeviceIdentifier(
        vendor=objects.pop(0x00).decode("ascii"),
        product_code=objects.pop(0x01).decode("ascii"),
        main_revision_version=objects.pop(0x02).decode("ascii"),
        other_data=objects,
    )


async def get_device_infos(client: AsyncModbusClient) -> list[DeviceInfo]:
    """Read the device infos from the inverter."""
    objects = await _read_device_identifier_objects(client, 0x03, DEVICE_INFOS_START_OBJECT_ID)

    def _parse_device_entry(device_info_str: str) -> DeviceInfo:
        raw_device_info: dict[int, str] = {}
        for entry in device_info_str.split(";"):
            key, value = entry.split("=")
            raw_device_info[int(key)] = value

        return DeviceInfo(
            model=raw_device_info.get(1),
            software_version=raw_device_info.get(2),
            interface_protocol_version=raw_device_info.get(3),
            esn=raw_device_info.get(4),
            device_id=int(raw_device_info[5]) if 5 in raw_device_info else None,  # noqa: PLR2004
            feature_version=raw_device_info.get(6),
            unknown_field=raw_device_info.get(7),
            product_type=raw_device_info.get(8),
        )

    if DEVICE_INFOS_START_OBJECT_ID in objects:
        (number_of_devices,) = struct.unpack(">B", objects.pop(DEVICE_INFOS_START_OBJECT_ID))
    else:
        _LOGGER.warning("No 0x87 entry with number of devices found in objects. Ignoring")
        number_of_devices = -1

    device_infos = [_parse_device_entry(device_info_bytes.decode("ascii")) for device_info_bytes in objects.values()]

    if number_of_devices >= 0 and len(device_infos) != number_of_devices:
        _LOGGER.warning(
            "Number of device infos does not match the number of devices: %d != %d",
            len(device_infos),
            number_of_devices,
        )

    return device_infos


async def _read_device_identifier_objects(
    client: AsyncModbusClient,
    read_dev_id_code: Literal[0x01, 0x03],
    object_id: int,
) -> dict[int, bytes]:
    """Read all the objects of a certain ReadDevId code."""
    try:
        return await client.read_device_identification(
            device_code=read_dev_id_code,
            object_id=object_id,
        )
    except (ServerDeviceBusyError, ServerDeviceFailureError, PermissionDeniedError) as err:
        _LOGGER.debug(
            "Got a %s while reading device identification from server %d",
            type(err).__name__,
            client.unit_id,
        )
        msg = (
            "Exception occurred while trying to read device infos "
            f"{hex(err.error_code) if err.error_code else 'no exception code'}"
        )
        raise ReadException(msg, modbus_exception_code=err.error_code) from err
    except ModbusResponseError as e:
        msg = (
            f"Exception occurred while trying to read device infos "
            f"{hex(e.error_code) if e.error_code else 'no exception code'}"
        )
        raise ReadException(msg, modbus_exception_code=e.error_code) from e
    except ModbusConnectionError as err:
        msg = "Connection failed when trying to read device infos"
        raise ConnectionInterruptedException(msg) from err
    except TModbusError as err:
        msg = f"Failed to read device infos: {err}"
        raise ReadException(msg) from err
