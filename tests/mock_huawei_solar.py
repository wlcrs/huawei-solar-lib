import asyncio

from huawei_solar import AsyncHuaweiSolar

from .conftest import MOCK_REGISTERS


async def get_mock_registers(host):
    """
    Get the registers from a huawei device.
    Can be used to add more tests for new devices.
    """

    api = AsyncHuaweiSolar(host)
    print("MOCK_REGISTERS = {")
    for key in MOCK_REGISTERS.keys():
        response = await (await api._get_client()).protocol.read_holding_registers(*key)
        print(key, ": ", response.registers, ",")
        await asyncio.sleep(0.5)

    print("}")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    loop.run_until_complete(get_mock_registers("192.168.10.2"))
