[![pipeline status](https://gitlab.com/Emilv2/huawei-solar/badges/master/pipeline.svg)](https://gitlab.com/Emilv2/huawei-solar/commits/master)
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

The library consists out of a low level interface implemented in [huawei_solar.py](src/huawei_solar/huawei_solar.py) which implements all the Modbus-operations, and a high level interface in [bridge.py](src/huawei_solar/bridge.py) which facilitates easy usage (primarily meant for the HA integration).

### Using the high level interface

An example on how to read the most interesting registers from the inverter:

```py
bridge = await HuaweiSolarBridge.create(host="192.168.200.1", port=6607)
print(await bridge.batch_update([rn.INPUT_POWER, rn.LINE_VOLTAGE_A_B, rn.LINE_VOLTAGE_B_C, rn.LINE_VOLTAGE_C_A]))
```

This results in the following output being printed:

```
{'input_power': Result(value=82, unit='W'), 'line_voltage_A_B': Result(value=233.4, unit='V'), 'line_voltage_B_C': Result(value=0.0, unit='V'), 'line_voltage_C_A': Result(value=0.0, unit='V')}
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

Subsequent development on v2 was done by [@wlcrs](https://github.com/wlcrs/huawei_solar).
