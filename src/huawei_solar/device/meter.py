"""Huawei power meter device support."""

from .base import HuaweiSolarDevice


class MeterDevice(HuaweiSolarDevice):
    """A power meter device exposed through a Huawei SmartLogger.

    The Huawei SmartLogger ModBus Interface Definitions (Issue 35) document only
    standardises telemetry registers for connected meters (see Table 2-5, register
    block starting at 32260). There is no standard register for model name or
    serial number on the meter itself; both fields are reported by the SmartLogger
    via the proprietary device-discovery command (Modbus FC 0x2B with object id
    0x87, see ``huawei_solar.device_discovery.get_device_infos``).
    """

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class supports the given device.

        Huawei SmartLoggers report a meter under more than one model string
        depending on the firmware and the read path:

        - ``get_device_infos`` (FC 0x2B) returns ``"PowerMeter"`` as the generic type.
        - The MODEL_NAME register (30000) read at the meter slave returns the
          SmartLogger device-list label, of the form ``"Meter(COM<port>-<addr>)"``.

        Both prefixes identify a power meter for our purposes.
        """
        return model_name.startswith(("PowerMeter", "Meter"))

    async def _populate_additional_fields(self) -> None:
        # No standard registers are defined to read additional metadata from the
        # meter itself. Identifying information (ESN, software version) is only
        # available through the SmartLogger's device-discovery response.
        self.serial_number = ""
