"""Interact with Huawei inverters over Modbus."""

from .device import (
    EMMADevice,
    HuaweiSolarDevice,
    HuaweiSolarDeviceWithLogin,
    MeterDevice,
    SChargerDevice,
    SDongleDevice,
    SmartLoggerDevice,
    SUN2000Device,
    create_device_instance,
    create_sub_device_instance,
)
from .device_discovery import DeviceIdentifier, DeviceInfo, get_device_identifiers, get_device_infos
from .exceptions import (
    ConnectionException,
    ConnectionInterruptedException,
    DecodeError,
    EncodeError,
    HuaweiSolarException,
    InvalidCredentials,
    PeakPeriodsValidationError,
    ReadException,
    TimeOfUsePeriodsException,
    WriteException,
)
from .files import (
    OptimizerHistoryRealTimeDataUnit,
    OptimizerOnlineStatus,
    OptimizerRealTimeData,
    OptimizerRunningStatus,
    OptimizerSystemInformation,
)
from .modbus_client import AsyncHuaweiSolarClient, create_rtu_client, create_tcp_client
from .register_definitions import Result
from .register_names import RegisterName

__all__ = [
    "AsyncHuaweiSolarClient",
    "ConnectionException",
    "ConnectionInterruptedException",
    "DecodeError",
    "DeviceIdentifier",
    "DeviceInfo",
    "EMMADevice",
    "EncodeError",
    "HuaweiSolarDevice",
    "HuaweiSolarDeviceWithLogin",
    "HuaweiSolarException",
    "InvalidCredentials",
    "MeterDevice",
    "OptimizerHistoryRealTimeDataUnit",
    "OptimizerOnlineStatus",
    "OptimizerRealTimeData",
    "OptimizerRunningStatus",
    "OptimizerSystemInformation",
    "PeakPeriodsValidationError",
    "ReadException",
    "RegisterName",
    "Result",
    "SChargerDevice",
    "SDongleDevice",
    "SUN2000Device",
    "SmartLoggerDevice",
    "TimeOfUsePeriodsException",
    "WriteException",
    "create_device_instance",
    "create_rtu_client",
    "create_sub_device_instance",
    "create_tcp_client",
    "get_device_identifiers",
    "get_device_infos",
]
