"""Device group mixin for gateway devices (SDongle, SmartLogger, EMMA)."""

import logging
from collections.abc import Sequence
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any

from huawei_solar import register_names as rn
from huawei_solar.exceptions import HuaweiSolarException
from huawei_solar.registers import REGISTERS

if TYPE_CHECKING:
    from huawei_solar.device.base import HuaweiSolarDevice
    from huawei_solar.modbus_client import AsyncHuaweiSolarClient
    from huawei_solar.register_definitions import Result

_LOGGER = logging.getLogger(__name__)


class DeviceGroupMixin:
    """Mixin for gateway devices (SDongle, SmartLogger, EMMA) that support multi-slave Modbus reads."""

    supports_custom_multi_device_read: bool = True

    if TYPE_CHECKING:
        client: AsyncHuaweiSolarClient

    async def group_get(
        self,
        name: rn.RegisterName,
        devices: Sequence["HuaweiSolarDevice"],
    ) -> "dict[HuaweiSolarDevice, Result[Any]]":
        """Read a single register across multiple slave devices in a single request.

        Uses Huawei custom Modbus PDU 0x41 0x37 via this gateway device. If unsupported,
        automatically falls back to querying each device individually.

        Args:
            name: The :class:`~huawei_solar.register_names.RegisterName` to query.
            devices: Sequence of :class:`~huawei_solar.device.base.HuaweiSolarDevice` instances.

        Returns:
            Dictionary mapping each :class:`~huawei_solar.device.base.HuaweiSolarDevice` to its
            decoded :class:`~huawei_solar.register_definitions.Result`.

        """
        batch_mapping = {dev: [name] for dev in devices}
        batch_results = await self.group_batch_update(batch_mapping)
        return {dev: batch_results[dev][name] for dev in devices if dev in batch_results and name in batch_results[dev]}

    async def group_batch_update_all(
        self,
        register_names: list[rn.RegisterName],
        devices: Sequence["HuaweiSolarDevice"],
    ) -> "dict[HuaweiSolarDevice, dict[rn.RegisterName, Result[Any]]]":
        """Query the same list of registers across multiple slave devices in a single request.

        Args:
            register_names: List of register names to query.
            devices: Sequence of :class:`~huawei_solar.device.base.HuaweiSolarDevice` instances.

        Returns:
            Dictionary mapping each :class:`~huawei_solar.device.base.HuaweiSolarDevice` to its
            dictionary of decoded results ``{RegisterName: Result}``.

        """
        batch_mapping = dict.fromkeys(devices, register_names)
        return await self.group_batch_update(batch_mapping)

    async def _filter_device_registers(
        self,
        device_registers: "dict[HuaweiSolarDevice, list[rn.RegisterName]]",
    ) -> "dict[HuaweiSolarDevice, list[rn.RegisterName]]":
        """Filter register names per device to valid and accessible registers."""
        filtered_by_device: dict[HuaweiSolarDevice, list[rn.RegisterName]] = {}
        for dev, names in device_registers.items():
            if unknown := {rn for rn in names if rn not in REGISTERS}:
                _LOGGER.warning(
                    "Unknown register names passed for device %s (unit %d): %s",
                    type(dev).__name__,
                    dev.unit_id,
                    ", ".join(str(r) for r in unknown),
                )
            valid_names = [r for r in names if r in REGISTERS]
            filtered = await dev._filter_registers(valid_names)  # noqa: SLF001
            filtered_by_device[dev] = filtered
        return filtered_by_device

    def _apply_device_results(
        self,
        target_devices: "Sequence[HuaweiSolarDevice]",
        raw_results_by_unit: "dict[int, dict[rn.RegisterName, Result[Any]]]",
    ) -> "dict[HuaweiSolarDevice, dict[rn.RegisterName, Result[Any]]]":
        """Apply state changes and transformations to raw multi-device results."""
        final_results: dict[HuaweiSolarDevice, dict[rn.RegisterName, Result[Any]]] = {}
        for dev in target_devices:
            dev_results = dict(raw_results_by_unit.get(dev.unit_id, {}))
            dev._detect_state_changes(dev_results)  # noqa: SLF001
            for key, val in dev_results.items():
                dev_results[key] = dev._transform_register_values(key, val)  # noqa: SLF001
            final_results[dev] = dev_results
        return final_results

    async def _fallback_per_device_batch_update(
        self,
        device_registers: "dict[HuaweiSolarDevice, list[rn.RegisterName]]",
    ) -> "dict[HuaweiSolarDevice, dict[rn.RegisterName, Result[Any]]]":
        """Fallback to executing standard per-device batch_update on each device."""
        fallback_results: dict[HuaweiSolarDevice, dict[rn.RegisterName, Result[Any]]] = {}
        for dev, names in device_registers.items():
            fallback_results[dev] = await dev.batch_update(names)
        return fallback_results

    async def group_batch_update(
        self,
        device_registers: "dict[HuaweiSolarDevice, list[rn.RegisterName]]",
    ) -> "dict[HuaweiSolarDevice, dict[rn.RegisterName, Result[Any]]]":
        """Perform a multi-device batch update across slave devices using custom PDU 0x41 0x37.

        Coalesces contiguous registers per slave ID, stays within Modbus PDU limits,
        and coordinates locks, filtering, state changes, and transformations for all
        involved devices.

        If the custom multi-device command fails (e.g. unsupported on third-party gateways
        or older firmware), it automatically disables custom reads for future queries and
        falls back to executing standard per-device
        :meth:`~huawei_solar.device.base.HuaweiSolarDevice.batch_update` on each device.

        Args:
            device_registers: Dictionary mapping each :class:`~huawei_solar.device.base.HuaweiSolarDevice`
                to its list of register names to query.

        Returns:
            Dictionary mapping each :class:`~huawei_solar.device.base.HuaweiSolarDevice` to its
            dictionary of decoded results ``{RegisterName: Result}``.

        """
        if not device_registers:
            return {}

        if not getattr(self, "supports_custom_multi_device_read", True):
            return await self._fallback_per_device_batch_update(device_registers)

        filtered_by_device = await self._filter_device_registers(device_registers)
        target_devices = [dev for dev, names in filtered_by_device.items() if names]
        if not target_devices:
            return {dev: {} for dev in device_registers}

        raw_results_by_unit: dict[int, dict[rn.RegisterName, Result[Any]]] = {}
        fallback_needed = False

        unique_locks = {dev.update_lock for dev in target_devices}
        if hasattr(self, "update_lock"):
            unique_locks.add(self.update_lock)

        async with AsyncExitStack() as stack:
            for lock in unique_locks:
                await stack.enter_async_context(lock)

            unit_id_mapping = {dev.unit_id: filtered_by_device[dev] for dev in target_devices}
            _LOGGER.debug("Multi-device batch update (0x41 0x37) across units %s", list(unit_id_mapping.keys()))

            try:
                raw_results_by_unit = await self.client.get_multi_device_scattered(unit_id_mapping)
            except HuaweiSolarException as exc:
                _LOGGER.info(
                    "Multi-device batch update (0x41 0x37) failed on gateway %s (unit %d) with %s; "
                    "disabling for this gateway",
                    type(self).__name__,
                    getattr(self, "unit_id", 0),
                    exc,
                )
                self.supports_custom_multi_device_read = False
                fallback_needed = True

        if fallback_needed:
            return await self._fallback_per_device_batch_update(device_registers)

        return self._apply_device_results(list(device_registers.keys()), raw_results_by_unit)
