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

        Huawei SmartLoggers and EMMAs report a meter under more than one model string
        depending on the firmware and the read path:

        - ``get_device_infos`` (FC 0x2B) returns ``"PowerMeter"`` as the generic type,
          or the specific meter model (e.g. ``"DTSU666_H"``, ``"DDSU666_H"``, ``"YDS60-80"``).
        - The MODEL_NAME register (30000) read at the meter slave returns the
          SmartLogger device-list label, of the form ``"Meter(COM<port>-<addr>)"``.

        All of these prefixes identify a power meter for our purposes.
        """
        return model_name.startswith(("PowerMeter", "Meter", "DTSU", "DDSU", "YDS"))

    async def _populate_additional_fields(self) -> None:
        if not getattr(self, "serial_number", None):
            parent_sn = self.primary_device.serial_number if self.primary_device else "unknown"
            self.serial_number = f"{parent_sn}_meter_{self.client.unit_id}"
