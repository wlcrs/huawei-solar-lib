[![pipeline status](https://gitlab.com/Emilv2/huawei-solar/badges/master/pipeline.svg)](https://gitlab.com/Emilv2/huawei-solar/commits/master)
[![codecov](https://codecov.io/gl/Emilv2/huawei-solar/branch/master/graph/badge.svg)](https://codecov.io/gl/Emilv2/huawei-solar)
[![PyPI version](https://badge.fury.io/py/huawei-solar.svg)](https://badge.fury.io/py/huawei-solar)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/huawei-solar.svg)](https://pypi.org/project/huawei-solar/)
[![PyPI - License](https://img.shields.io/pypi/l/huawei-solar.svg)](https://choosealicense.com/licenses/mit/)
[![Code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/python/black)

# Python library for connecting to Huawei SUN2000 Inverters over Modbus

This library implements an easy to use interface to locally connect to Huawei SUN2000 inverters over 
Modbus-TCP or Modbus-RTU following the 'Solar Inverter Modbus Interface Definitions' provided by Huawei.

It was primarily developed to add support for Huawei Solar inverters to Home Assistant, resulting
in the following integration: [wlcrs/huawei_solar](https://github.com/wlcrs/huawei_solar). 

**Features:**
- Modbus-TCP support: connecting to the inverter via the SDongle, or over the WiFi-AP (`SUN2000-<serial_no>`) 
  broadcasted by the inverter
- Modbus-RTU support: connecting to the inverter via the RS485A1 and RS485B1 pins on the COM port
- Batched reading of Modbus registers and converting them into the correct units
- Reading Optimizer data via the specialized 'file' Modbus extension  
- Writing to Modbus registers (mostly useful for setting battery parameters)
- Performing the login sequence to gain 'installer'-level access rights

Note t

## Installation

This library is [published on PyPI](https://pypi.org/project/huawei-solar/):

```bash
pip3 install huawei-solar
```

## Basic usage

The library consists out of a low level interface implemented in [huwei_solar.py](src/huawei_solar/huawei_solar.py) which implements all the Modbus-operations, and a high level interface in [bridge.py](src/huawei_solar/bridge.py) which facilitates easy usage (primarily meant for the HA integration). 

### Using the high level interface

An example on how to read the most interesting registers from the inverter:

```py
bridge = await HuaweiSolarBridge.create(host="192.168.200.1", port=6607)
print(await bridge.update())
```

This results in the following output being printed:

```
{'input_power': Result(value=82, unit='W'), 'line_voltage_A_B': Result(value=233.4, unit='V'), 'line_voltage_B_C': Result(value=0.0, unit='V'), 'line_voltage_C_A': Result(value=0.0, unit='V'), 'phase_A_voltage': Result(value=247.2, unit='V'), 'phase_B_voltage': Result(value=0.3, unit='V'), 'phase_C_voltage': Result(value=0.0, unit='V'), 'phase_A_current': Result(value=0.408, unit='A'), 'phase_B_current': Result(value=0.0, unit='A'), 'phase_C_current': Result(value=0.0, unit='A'), 'day_active_power_peak': Result(value=2407, unit='W'), 'active_power': Result(value=70, unit='W'), 'reactive_power': Result(value=-1, unit='VA'), 'power_factor': Result(value=1.0, unit=None), 'grid_frequency': Result(value=50.02, unit='Hz'), 'efficiency': Result(value=100.0, unit='%'), 'internal_temperature': Result(value=24.4, unit='°C'), 'insulation_resistance': Result(value=30.0, unit='MOhm'), 'device_status': Result(value='On-grid', unit=None), 'fault_code': Result(value=0, unit=None), 'startup_time': Result(value=datetime.datetime(2022, 11, 18, 9, 2, 40, tzinfo=datetime.timezone.utc), unit=None), 'shutdown_time': Result(value=None, unit=None), 'accumulated_yield_energy': Result(value=3515.62, unit='kWh'), 'daily_yield_energy': Result(value=0.12, unit='kWh'), 'state_1': Result(value=['Grid-Connected', 'Grid-Connected normally'], unit=None), 'state_2': Result(value=['Locked', 'PV connected', 'DSP data collection'], unit=None), 'state_3': Result(value=['On-grid', 'Off-grid switch disabled'], unit=None), 'alarm_1': Result(value=[], unit=None), 'alarm_2': Result(value=[], unit=None), 'alarm_3': Result(value=[], unit=None), 'pv_01_voltage': Result(value=287.8, unit='V'), 'pv_01_current': Result(value=0.0, unit='A'), 'pv_02_voltage': Result(value=0.0, unit='V'), 'pv_02_current': Result(value=0.0, unit='A'), 'nb_online_optimizers': Result(value=10, unit=None), 'grid_A_voltage': Result(value=234.1, unit='V'), 'grid_B_voltage': Result(value=234.1, unit='V'), 'grid_C_voltage': Result(value=233.1, unit='V'), 'active_grid_A_current': Result(value=-0.48, unit='I'), 'active_grid_B_current': Result(value=-0.46, unit='I'), 'active_grid_C_current': Result(value=-0.56, unit='I'), 'power_meter_active_power': Result(value=-151, unit='W'), 'power_meter_reactive_power': Result(value=187, unit='Var'), 'active_grid_power_factor': Result(value=-0.428, unit=None), 'active_grid_frequency': Result(value=50.0, unit='Hz'), 'grid_exported_energy': Result(value=1705.65, unit='kWh'), 'grid_accumulated_energy': Result(value=1048.0, unit='kWh'), 'grid_accumulated_reactive_power': Result(value=0.0, unit='kVarh'), 'meter_type': Result(value=<MeterType.THREE_PHASE: 1>, unit=None), 'active_grid_A_B_voltage': Result(value=405.3, unit='V'), 'active_grid_B_C_voltage': Result(value=404.6, unit='V'), 'active_grid_C_A_voltage': Result(value=404.6, unit='V'), 'active_grid_A_power': Result(value=-72, unit='W'), 'active_grid_B_power': Result(value=-71, unit='W'), 'active_grid_C_power': Result(value=-7, unit='W'), 'storage_state_of_capacity': Result(value=22.0, unit='%'), 'storage_running_status': Result(value=<StorageStatus.RUNNING: 2>, unit=None), 'storage_bus_voltage': Result(value=454.2, unit='V'), 'storage_bus_current': Result(value=0.0, unit='A'), 'storage_charge_discharge_power': Result(value=12, unit='W'), 'storage_total_charge': Result(value=1094.26, unit='kWh'), 'storage_total_discharge': Result(value=1049.3, unit='kWh'), 'storage_current_day_charge_capacity': Result(value=0.39, unit='kWh'), 'storage_current_day_discharge_capacity': Result(value=0.15, unit='kWh')}
```

### Using the low level interface

Example code:

```py
from huawei_solar import AsyncHuaweiSolar, register_names as rn

slave_id = 0
client = await AsyncHuaweiSolar.create("192.168.200.1", 6607, slave_id)

# Reading a single register

result = await bridge.client.get(rn.NB_PV_STRINGS, slave_id)
print("Number of PV strings: ", result.value)

# Batched reading of multiple registers
# Only possible when they are located closely to each other in the Modbus register space

results = await self.client.get_multiple([rn.LINE_VOLTAGE_A_B, rn.LINE_VOLTAGE_B_C, rn.LINE_VOLTAGE_C_A], self.slave_id)
print("A-B voltage: ", results[0].value)
print("B-C voltage: ", results[1].value)
print("C-A voltage: ", results[2].value)
```

A good starting point to learn how to use the low level interface is to look at how the high level interface in 
[bridge.py](src/huawei_solar/bridge.py) uses it.

# Acknowledgements

The initial implementation of v1 was done by [@Emilv2](https://gitlab.com/Emilv2/huawei-solar/-/tree/1.1.0).

Subsequent developement on v2 was done by [@wlcrs](https://github.com/wlcrs/huawei_solar).