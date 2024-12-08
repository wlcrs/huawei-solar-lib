# ruff: noqa: T201

"""Test file for HuaweiSolarBridge."""

import asyncio
import logging

from huawei_solar import HuaweiSUN2000Bridge, create_tcp_bridge
from huawei_solar import register_names as rn

loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.DEBUG)


async def test():
    """Run test."""
    bridge = await create_tcp_bridge(host="192.168.1.1", port=503)
    assert isinstance(bridge, HuaweiSUN2000Bridge)
    # print(await bridge.has_write_permission())
    await bridge.login("installer", "00000a")
    await bridge.batch_update(
        [
            rn.ACTIVE_POWER_FIXED_VALUE_DERATING,
            rn.ACTIVE_POWER_PERCENTAGE_DERATING,
            rn.STORAGE_CAPACITY_CONTROL_MODE,
            rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING,
            rn.STORAGE_CAPACITY_CONTROL_PERIODS,
        ],
    )
    print(await bridge.client.get(rn.ACTIVE_POWER_FIXED_VALUE_DERATING))
    print(await bridge.client.get(rn.ACTIVE_POWER_PERCENTAGE_DERATING))

    print(await bridge.client.get(rn.STORAGE_CAPACITY_CONTROL_MODE))
    print(await bridge.client.get(rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING))
    print(await bridge.client.get(rn.STORAGE_CAPACITY_CONTROL_PERIODS))

    # i = 0
    # while i < 100:

    #     try:
    #         print(await bridge.update())
    #     except Exception as e:
    #         print("Updating failed: ", e)

    #     await asyncio.sleep(2.5)
    #     i = i+1
    print(await bridge.get_optimizer_system_information_data())
    print(await bridge.get_latest_optimizer_history_data())

    await bridge.stop()


loop.run_until_complete(test())
