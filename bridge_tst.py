import logging
import time
from huawei_solar import HuaweiSolarBridge, register_names as rn, register_values as rv
import asyncio

loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.DEBUG)


async def test():

    bridge = await HuaweiSolarBridge.create_rtu(port="/dev/ttyUSB0", slave_id=1)

    print(await bridge.client.get(rn.STORAGE_MAXIMUM_DISCHARGING_POWER))

    print(await bridge.get_latest_optimizer_history_data())

    await bridge.stop()


loop.run_until_complete(test())
