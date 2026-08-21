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
    """Device identifier information read via Modbus MEI (0x2B 0x0E)."""

    vendor: str
    """Device manufacturer name (e.g. 'Huawei'). (MEI Object 0x00)"""
    product_code: str
    """Inverter or device model code (e.g. 'SUN2000-10KTL-M1'). (MEI Object 0x01)"""
    main_revision_version: str
    """Main firmware/software version string. (MEI Object 0x02)"""
    serial_number: str | None = None
    """Equipment Serial Number (ESN). (MEI Object 0x10)"""
    device_id: int | None = None
    """Modbus logical device address. (MEI Object 0x14)"""
    user_manager_version: int | None = None
    """User management authentication protocol version (e.g. 2 or 3). (MEI Object 0x15)"""
    is_installer_password_set: bool | None = None
    """Whether installer password is configured (False = initial password setup required). (MEI Object 0x15)"""
    is_user_password_set: bool | None = None
    """Whether user password is configured (False = initial password setup required). (MEI Object 0x15)"""
    is_level3_password_set: bool | None = None
    """Status of third-level / guest account password. (MEI Object 0x15)"""
    bluetooth_reg_address: int | None = None
    """Bluetooth configuration register address. (MEI Object 0x16)"""
    machine_mask: int | None = None
    """Hardware capabilities bitmask (e.g. HEMS 2-in-1 flag). (MEI Object 0x17)"""
    registration_code: str | None = None
    """Huawei cloud/system registration code. (MEI Object 0x18)"""
    function_code: int | None = None
    """Supported function set indicator. (MEI Object 0x19)"""
    two_in_one_machine_esn: str | None = None
    """ESN for coupled/integrated HEMS devices. (MEI Object 0x1B)"""


def _decode_mei_string(raw: bytes | None) -> str | None:
    if raw is None:
        return None
    return raw.decode("ascii", errors="replace").strip()


def _decode_mei_int(raw: bytes | None) -> int | None:
    if raw is None:
        return None
    return int.from_bytes(raw, byteorder="big")


async def get_device_identifiers(client: AsyncModbusClient) -> DeviceIdentifier:
    """Read the device identifiers from the inverter."""
    objects = await _read_device_identifier_objects(client, 0x01, 0x00)

    vendor = objects.get(0x00, b"").decode("ascii", errors="replace").strip()
    product_code = objects.get(0x01, b"").decode("ascii", errors="replace").strip()
    main_revision_version = objects.get(0x02, b"").decode("ascii", errors="replace").strip()
    serial_number = _decode_mei_string(objects.get(0x10))
    device_id = _decode_mei_int(objects.get(0x14))

    # Object 0x15: User management and password status bitmask
    user_manager_version = None
    is_installer_password_set = None
    is_user_password_set = None
    is_level3_password_set = None

    if 0x15 in objects:
        raw_val = _decode_mei_int(objects[0x15])
        if raw_val is not None:
            user_manager_version = raw_val & 0xFF
            if len(objects[0x15]) >= 2:
                is_installer_password_set = bool((raw_val >> 8) & 1)
                is_user_password_set = bool((raw_val >> 9) & 1)
                is_level3_password_set = bool((raw_val >> 10) & 1)

    bluetooth_reg_address = _decode_mei_int(objects.get(0x16))
    machine_mask = _decode_mei_int(objects.get(0x17))
    registration_code = _decode_mei_string(objects.get(0x18))
    function_code = _decode_mei_int(objects.get(0x19))
    two_in_one_machine_esn = _decode_mei_string(objects.get(0x1B))

    return DeviceIdentifier(
        vendor=vendor,
        product_code=product_code,
        main_revision_version=main_revision_version,
        serial_number=serial_number,
        device_id=device_id,
        user_manager_version=user_manager_version,
        is_installer_password_set=is_installer_password_set,
        is_user_password_set=is_user_password_set,
        is_level3_password_set=is_level3_password_set,
        bluetooth_reg_address=bluetooth_reg_address,
        machine_mask=machine_mask,
        registration_code=registration_code,
        function_code=function_code,
        two_in_one_machine_esn=two_in_one_machine_esn,
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
