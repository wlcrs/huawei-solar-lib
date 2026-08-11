[![Homepage](https://img.shields.io/badge/Homepage-2088ff?logo=github&logoColor=white)](https://github.com/wlcrs/huawei-solar-lib)
[![GitHub License](https://img.shields.io/github/license/wlcrs/huawei-solar-lib)](https://github.com/wlcrs/huawei-solar-lib/blob/main/LICENSE)
[![Release](https://img.shields.io/github/v/release/wlcrs/huawei-solar-lib.svg)](https://github.com/wlcrs/huawei-solar-lib/releases)
[![Python Versions](https://img.shields.io/pypi/pyversions/huawei-solar)](https://pypi.org/p/huawei-solar/)
[![Testing](https://github.com/wlcrs/huawei-solar-lib/actions/workflows/tests.yml/badge.svg)](https://github.com/wlcrs/huawei-solar-lib/actions/workflows/tests.yml)


# Python library for connecting to Huawei SUN2000 Inverters over Modbus

This library implements an easy to use interface to locally connect to Huawei Solar devices over
Modbus-TCP or Modbus-RTU following the 'Solar Inverter Modbus Interface Definitions' provided by Huawei.

It was primarily developed to add support for Huawei Solar inverters to Home Assistant, resulting
in the following integration: [wlcrs/huawei_solar](https://github.com/wlcrs/huawei_solar).

**Supported devices:**
- SUN2000 inverters
- LUNA2000 batteries (when connected to SUN2000)
- EMMA
- SCharger (when connected to EMMA)

**Features:**

- Modbus-TCP support: connecting to the inverter via the SDongle, EMMA, or over the WiFi-AP (`SUN2000-<serial_no>`)
  broadcasted by the inverter
- Modbus-RTU support: connecting to the inverter via the RS485A1 and RS485B1 pins on the COM port
- Batched reading of Modbus registers and converting them into the correct units
- Reading Optimizer data via the specialized 'file' Modbus extension
- Writing to Modbus registers (mostly useful for setting battery parameters)
- Performing the login sequence to gain 'installer'-level access rights

## Installation

This library is [published on PyPI](https://pypi.org/project/huawei-solar/).


## Basic usage

The library consists out of a low level interface implemented in [modbus_client.py](src/huawei_solar/modbus_client.py) which implements all the Modbus-operations, and a high level interface in [huawei_solar/devices](src/huawei_solar/devices.py) which facilitates easy usage (primarily meant for the HA integration).

### Using the high level 'Devices' interface

An example on how to read the most interesting registers from the inverter:

```py
import asyncio

from huawei_solar import (
    SUN2000Device,
    create_device_instance,
    create_tcp_client,
)
from huawei_solar import register_names as rn


async def test() -> None:
    """Run test."""
    client = create_tcp_client(host="192.168.1.1", port=503)
    device = await create_device_instance(client)

    assert isinstance(device, SUN2000Device)
    print(
        await device.batch_update(
            [
                rn.INPUT_POWER,
                rn.LINE_VOLTAGE_A_B,
                rn.LINE_VOLTAGE_B_C,
                rn.LINE_VOLTAGE_C_A,
            ]
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())
```

This results in the following output being printed:

```
{'input_power': Result(value=82, unit='W'), 'line_voltage_A_B': Result(value=233.4, unit='V'), 'line_voltage_B_C': Result(value=0.0, unit='V'), 'line_voltage_C_A': Result(value=0.0, unit='V')}
```

## Frequently asked questions

**Q:** the connection is interrupted a few seconds after connecting to the Huawei Device. How do I solve this?

**A:**: Huawei devices only support one connection at a time. If your connection is interrupted, this is typically because another device is trying to (re-)connect to it. Disable that device and try again.

## Acknowledgements

The initial implementation of v1 was done by [@Emilv2](https://gitlab.com/Emilv2/huawei-solar/-/tree/1.1.0).

Subsequent development on v2 was done by [@wlcrs](https://github.com/wlcrs/huawei_solar).
