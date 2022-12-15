import asyncio
import logging

from huawei_solar import HuaweiSolarBridge, register_names as rn

loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.DEBUG)


async def test():

    bridge = await HuaweiSolarBridge.create(host="192.168.200.1", port=6607)
    print(await bridge.has_write_permission())
    await bridge.login("installer", "00000a")
    print(await bridge.client.get(rn.STORAGE_MAXIMUM_DISCHARGING_POWER))

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

    print(await bridge.get_latest_optimizer_history_data())

    await bridge.stop()


loop.run_until_complete(test())
