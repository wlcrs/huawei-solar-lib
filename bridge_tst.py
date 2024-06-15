"""Test file for HuaweiSolarBridge."""

# import asyncio
# import logging

# from huawei_solar import HuaweiSolarBridge
# from huawei_solar import register_names as rn

# loop = asyncio.new_event_loop()

# logging.basicConfig(level=logging.DEBUG)


# async def test():
#     bridge = await HuaweiSolarBridge.create(host="192.168.1.1", port=503)
#     # print(await bridge.has_write_permission())
#     await bridge.login("installer", "00000a")
#     print(await bridge.client.get(rn.ACTIVE_POWER_FIXED_VALUE_DERATING))
#     print(await bridge.client.get(rn.ACTIVE_POWER_PERCENTAGE_DERATING))

#     exit(0)
#     print(await bridge.client.get(rn.STORAGE_CAPACITY_CONTROL_MODE))
#     print(await bridge.client.get(rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING))
#     print(await bridge.client.get(rn.STORAGE_CAPACITY_CONTROL_PERIODS))

#     # i = 0
#     # while i < 100:

#     #     try:
#     #         print(await bridge.update())
#     #     except Exception as e:
#     #         print("Updating failed: ", e)

#     #     await asyncio.sleep(2.5)
#     #     i = i+1

#     print(await bridge.get_latest_optimizer_history_data())

#     await bridge.stop()


# loop.run_until_complete(test())
