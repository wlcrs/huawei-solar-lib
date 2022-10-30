from huawei_solar import AsyncHuaweiSolar
import asyncio

loop = asyncio.new_event_loop()


async def test(names):

    hs = await AsyncHuaweiSolar.create("192.168.10.2")
    responses = await hs.get_multiple(names)

    for name, response in zip(names, responses):
        print(f"{name}: {response}")

    await hs.stop()


loop.run_until_complete(
    test(
        [
            "pv_01_voltage",
            "pv_01_current",
            "pv_02_voltage",
            "pv_02_current",
            "pv_03_voltage",
            "pv_03_current",
            "pv_04_voltage",
            "pv_04_current",
            "pv_05_voltage",
            "pv_05_current",
            "pv_06_voltage",
            "pv_06_current",
            "pv_07_voltage",
            "pv_07_current",
            "pv_08_voltage",
            "pv_08_current",
            "pv_09_voltage",
            "pv_09_current",
            "pv_10_voltage",
            "pv_10_current",
            "pv_11_voltage",
            "pv_11_current",
            "pv_12_voltage",
            "pv_12_current",
            "pv_13_voltage",
            "pv_13_current",
            "pv_14_voltage",
            "pv_14_current",
            "pv_15_voltage",
            "pv_15_current",
            "pv_16_voltage",
            "pv_16_current",
            "pv_17_voltage",
            "pv_17_current",
            "pv_18_voltage",
            "pv_18_current",
            "pv_19_voltage",
            "pv_19_current",
            "pv_20_voltage",
            "pv_20_current",
            "pv_21_voltage",
            "pv_21_current",
            "pv_22_voltage",
            "pv_22_current",
            "pv_23_voltage",
            "pv_23_current",
            "pv_24_voltage",
            "pv_24_current",
        ]
    )
)

loop.run_until_complete(test(["model_name", "serial_number"]))
loop.run_until_complete(
    test(
        [
            "line_voltage_A_B",
            "line_voltage_B_C",
            "line_voltage_C_A",
            "phase_A_voltage",
            "phase_B_voltage",
            "phase_C_voltage",
            "phase_A_current",
            "phase_B_current",
            "phase_C_current",
            "day_active_power_peak",
            "active_power",
            "reactive_power",
            "power_factor",
            "grid_frequency",
            "efficiency",
            "internal_temperature",
            "insulation_resistance",
            "device_status",
            "fault_code",
            "startup_time",
            "shutdown_time",
        ]
    )
)

loop.run_until_complete(
    test(
        [
            "meter_status",
            "grid_A_voltage",
            "grid_B_voltage",
            "grid_C_voltage",
            "active_grid_A_current",
            "active_grid_B_current",
            "active_grid_C_current",
            "power_meter_active_power",
            "power_meter_reactive_power",
            "active_grid_power_factor",
            "active_grid_frequency",
            "grid_exported_energy",
            "grid_accumulated_energy",
            "meter_type",
            "active_grid_A_B_voltage",
            "active_grid_B_C_voltage",
            "active_grid_C_A_voltage",
            "active_grid_A_power",
            "active_grid_B_power",
            "active_grid_C_power",
        ]
    )
)


async def test_single(name):

    hs = await AsyncHuaweiSolar.create("192.168.10.2")

    print(await hs.get(name))

    await hs.stop()


loop.run_until_complete(test_single("active_power"))
loop.run_until_complete(test_single("pv_04_current"))
