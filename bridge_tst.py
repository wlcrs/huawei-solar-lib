import logging
import logging
import time
from huawei_solar import HuaweiSolarBridge, register_names as rn, register_values as rv
import asyncio

loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.DEBUG)


async def test():

    bridge = await HuaweiSolarBridge.create("131.87.12.200", port=502, slave_id=1)

    # print("Write permission: ", await bridge.has_write_permission())

    #  await bridge.login("installer", "00000a")

    # print("Write permission: ", await bridge.has_write_permission())

    await asyncio.sleep(5)

    # for _ in range(5):
    #     start = time.perf_counter()
    #     print(await bridge.update())
    #     end = time.perf_counter()

    #     print(f"*** Updated in {end-start}")
    #     await asyncio.sleep(1)

    # print(await bridge.client.get(rn.STORAGE_MAXIMUM_DISCHARGING_POWER))

    # print(await bridge.set(rn.STORAGE_MAXIMUM_DISCHARGING_POWER, 0))

    # print(await bridge.set(
    #     rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
    #     rv.StorageForcibleChargeDischarge.STOP,
    # ))
    # print(await bridge.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, 0))
    # print(await bridge.set(
    #     rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
    #     0,
    # ))
    # print(await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE, 0))
    # print(await bridge.set(
    #     rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
    #     0,
    # ))
    # await asyncio.sleep(60)

    print(await bridge.read_real_time_optimizer_data())

    await bridge.stop()


loop.run_until_complete(test())
