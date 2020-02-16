from pymodbus.client.sync import ModbusTcpClient
from collections import namedtuple
from time import gmtime

import logging
from datetime import datetime


__version__ = "1.1.0"

RegisterDefinitions = namedtuple(
    "RegisterDefinitions", "type unit gain register length"
)
GridCodes = namedtuple("GridCodes", "standard country")
Result = namedtuple("Result", "value unit")


class HuaweiInverter:
    def __init__(self, host, port="502", timeout=5):
        self.client = ModbusTcpClient(host, port=port, timeout=timeout)

    def get(self, name):
        reg = registers[name]
        #        try:
        response = read_register(self.client, reg.register, reg.length)
        #        except:
        #            pass
        if reg.type == "str":
            result = response.decode("utf-8").strip("\0")
        elif reg.type == "u16" and reg.unit == "status_enum":
            result = device_status_definitions[response.hex()]
        elif reg.type == "u16" and reg.unit == "grid_enum":
            tmp = int.from_bytes(response, byteorder="big")
            result = grid_codes[tmp]
        elif reg.type == "u32" and reg.unit == "epoch":
            tmp = int.from_bytes(response, byteorder="big")
            # epoch is in local time so this gives local time, not gmtime
            result = gmtime(tmp)
        elif reg.type == "u16" or reg.type == "u32":
            result = int.from_bytes(response, byteorder="big") / reg.gain
        elif reg.type == "i16":
            tmp = int.from_bytes(response, byteorder="big")
            # result is actually negative
            if (tmp & 0x8000) == 0x8000:
                tmp = -((tmp ^ 0xFFFF) + 1)
            result = tmp / reg.gain
        elif reg.type == "i32":
            tmp = int.from_bytes(response, byteorder="big")
            # result is actually negative
            if (tmp & 0x80000000) == 0x80000000:
                tmp = -((tmp ^ 0xFFFF) + 1)
            result = tmp / reg.gain

        return Result(result, reg.unit)


def read_register(client, register, length):
    i = 0
    # 5 tries and then we give up
    # usually works after 3 tries if we haven't connected for a while (independend of timeout). It seems to only support one connected device at the same time
    while i < 4:
        print(i)
        response = client.read_holding_registers(register, length)

        if not response.isError():
            break
        i = i + 1
    else:
        raise Exception("could not read register value")
    return response.encode()[1:]


registers = {
    "model_name": RegisterDefinitions("str", None, 1, 30000, 15),
    "serial_number": RegisterDefinitions("str", None, 1, 30015, 10),
    "model_id": RegisterDefinitions("u16", None, 1, 30070, 1),
    "nb_pv_strings": RegisterDefinitions("u16", None, 1, 30071, 1),
    "nb_mpp_tracks": RegisterDefinitions("u16", None, 1, 30072, 1),
    "rated_power": RegisterDefinitions("u32", "W", 1, 30073, 2),
    "P_max": RegisterDefinitions("u32", "W", 1, 30075, 2),
    "S_max": RegisterDefinitions("u32", "VA", 1, 30077, 2),
    "Q_max_out": RegisterDefinitions("u32", "VAr", 1, 30079, 2),
    "Q_max_in": RegisterDefinitions("u32", "VAr", 1, 30081, 2),
    "state_1": RegisterDefinitions("bitfield16", None, 1, 32000, 1),
    "state_2": RegisterDefinitions("bitfield16", None, 1, 32002, 1),
    "state_3": RegisterDefinitions("bitfield32", None, 1, 32003, 2),
    "alarm_1": RegisterDefinitions("bitfield16", None, 1, 32008, 1),
    "alarm_2": RegisterDefinitions("bitfield16", None, 1, 32009, 1),
    "alarm_3": RegisterDefinitions("bitfield16", None, 1, 32010, 1),
    "pv_01_voltage": RegisterDefinitions("i16", "V", 10, 32016, 1),
    "pv_01_current": RegisterDefinitions("i16", "A", 100, 32017, 1),
    "pv_02_voltage": RegisterDefinitions("i16", "V", 10, 32018, 1),
    "pv_02_current": RegisterDefinitions("i16", "A", 100, 32019, 1),
    "pv_03_voltage": RegisterDefinitions("i16", "V", 10, 32020, 1),
    "pv_03_current": RegisterDefinitions("i16", "A", 100, 32021, 1),
    "pv_04_voltage": RegisterDefinitions("i16", "V", 10, 32022, 1),
    "pv_04_current": RegisterDefinitions("i16", "A", 100, 32023, 1),
    "pv_05_voltage": RegisterDefinitions("i16", "V", 10, 32024, 1),
    "pv_05_current": RegisterDefinitions("i16", "A", 100, 32025, 1),
    "pv_06_voltage": RegisterDefinitions("i16", "V", 10, 32026, 1),
    "pv_06_current": RegisterDefinitions("i16", "A", 100, 32027, 1),
    "pv_07_voltage": RegisterDefinitions("i16", "V", 10, 32028, 1),
    "pv_07_current": RegisterDefinitions("i16", "A", 100, 32029, 1),
    "pv_08_voltage": RegisterDefinitions("i16", "V", 10, 32030, 1),
    "pv_08_current": RegisterDefinitions("i16", "A", 100, 32031, 1),
    "pv_09_voltage": RegisterDefinitions("i16", "V", 10, 32032, 1),
    "pv_09_current": RegisterDefinitions("i16", "A", 100, 32033, 1),
    "pv_10_voltage": RegisterDefinitions("i16", "V", 10, 32034, 1),
    "pv_10_current": RegisterDefinitions("i16", "A", 100, 32035, 1),
    "pv_11_voltage": RegisterDefinitions("i16", "V", 10, 32036, 1),
    "pv_11_current": RegisterDefinitions("i16", "A", 100, 32037, 1),
    "pv_12_voltage": RegisterDefinitions("i16", "V", 10, 32038, 1),
    "pv_12_current": RegisterDefinitions("i16", "A", 100, 32039, 1),
    "pv_13_voltage": RegisterDefinitions("i16", "V", 10, 32040, 1),
    "pv_13_current": RegisterDefinitions("i16", "A", 100, 32041, 1),
    "pv_14_voltage": RegisterDefinitions("i16", "V", 10, 32042, 1),
    "pv_14_current": RegisterDefinitions("i16", "A", 100, 32043, 1),
    "pv_15_voltage": RegisterDefinitions("i16", "V", 10, 32044, 1),
    "pv_15_current": RegisterDefinitions("i16", "A", 100, 32045, 1),
    "pv_16_voltage": RegisterDefinitions("i16", "V", 10, 32046, 1),
    "pv_16_current": RegisterDefinitions("i16", "A", 100, 32047, 1),
    "pv_17_voltage": RegisterDefinitions("i16", "V", 10, 32048, 1),
    "pv_17_current": RegisterDefinitions("i16", "A", 100, 32049, 1),
    "pv_18_voltage": RegisterDefinitions("i16", "V", 10, 32050, 1),
    "pv_18_current": RegisterDefinitions("i16", "A", 100, 32051, 1),
    "pv_19_voltage": RegisterDefinitions("i16", "V", 10, 32052, 1),
    "pv_19_current": RegisterDefinitions("i16", "A", 100, 32053, 1),
    "pv_20_voltage": RegisterDefinitions("i16", "V", 10, 32054, 1),
    "pv_20_current": RegisterDefinitions("i16", "A", 100, 32055, 1),
    "pv_21_voltage": RegisterDefinitions("i16", "V", 10, 32056, 1),
    "pv_21_current": RegisterDefinitions("i16", "A", 100, 32057, 1),
    "pv_22_voltage": RegisterDefinitions("i16", "V", 10, 32058, 1),
    "pv_22_current": RegisterDefinitions("i16", "A", 100, 32059, 1),
    "pv_23_voltage": RegisterDefinitions("i16", "V", 10, 32060, 1),
    "pv_23_current": RegisterDefinitions("i16", "A", 100, 32061, 1),
    "pv_24_voltage": RegisterDefinitions("i16", "V", 10, 32062, 1),
    "pv_24_current": RegisterDefinitions("i16", "A", 100, 32063, 1),
    "input_power": RegisterDefinitions("i32", "W", 1, 32064, 2),
    "power_grid_voltage": RegisterDefinitions("u16", "V", 10, 32066, 1),
    "line_voltage_A_B": RegisterDefinitions("u16", "V", 10, 32066, 1),
    "line_voltage_B_C": RegisterDefinitions("u16", "V", 10, 32067, 1),
    "line_voltage_C_A": RegisterDefinitions("u16", "V", 10, 32068, 1),
    "phase_A_voltage": RegisterDefinitions("u16", "V", 10, 32069, 1),
    "phase_B_voltage": RegisterDefinitions("u16", "V", 10, 32070, 1),
    "phase_C_voltage": RegisterDefinitions("u16", "V", 10, 32071, 1),
    "power_grid_current": RegisterDefinitions("i32", "A", 1000, 32072, 2),
    "phase_A_current": RegisterDefinitions("i32", "A", 1000, 32072, 2),
    "phase_B_current": RegisterDefinitions("i32", "A", 1000, 32074, 2),
    "phase_C_current": RegisterDefinitions("i32", "A", 1000, 32076, 2),
    "day_active_power_peak": RegisterDefinitions("i32", "W", 1, 32078, 2),
    "active_power": RegisterDefinitions("i32", "W", 1, 32080, 2),
    "reactive_power": RegisterDefinitions("i32", "VA", 1, 32082, 2),
    "power_factor": RegisterDefinitions("i16", None, 1000, 32084, 1),
    "grid_frequency": RegisterDefinitions("u16", "Hz", 100, 32085, 1),
    "efficiency": RegisterDefinitions("u16", "%", 100, 32086, 1),
    "internal_temperature": RegisterDefinitions("i16", "°C", 10, 32087, 1),
    "insulation_resistance": RegisterDefinitions("u16", "MOhm", 100, 32088, 1),
    "device_status": RegisterDefinitions("u16", "status_enum", 1, 32089, 1),
    "fault_code": RegisterDefinitions("u16", None, 1, 32090, 1),
    "startup_time": RegisterDefinitions("u32", "epoch", 1, 32091, 2),
    "shutdown_time": RegisterDefinitions("u32", "epoch", 1, 32093, 2),
    "accumulated_yield_energy": RegisterDefinitions("u32", "kWh", 100, 32106, 2),
    "daily_yield_energy": RegisterDefinitions("u32", "kWh", 100, 32114, 2),
    "system_time": RegisterDefinitions("u32", "epoch", 1, 40000, 2),
    "grid_code": RegisterDefinitions("u16", "grid_enum", 1, 42000, 1),
}


device_status_definitions = {
    "0000": "Standby: initializing",
    "0001": "Standby: detecting insulation resistance",
    "0002": "Standby: detecting irradiation",
    "0003": "Standby: grid detecting",
    "0100": "Starting",
    "0200": "On-grid",
    "0201": "Grid Connection: power limited",
    "0202": "Grid Connection: self-derating",
    "0300": "Shutdown: fault",
    "0301": "Shutdown: command",
    "0302": "Shutdown: OVGR",
    "0303": "Shutdown: communication disconnected",
    "0304": "Shutdown: power limited",
    "0305": "Shutdown: manual startup required",
    "0306": "Shutdown: DC switches disconnected",
    "0307": "Shutdown: rapid cutoff",
    "0308": "Shutdown: input underpowered",
    "0401": "Grid scheduling: cosphi-P curve",
    "0402": "Grid scheduling: Q-U curve",
    "0403": "Grid scheduling: PF-U curve",
    "0404": "Grid scheduling: dry contact",
    "0405": "Grid scheduling: Q-P curve",
    "0500": "Spot-check ready",
    "0501": "Spot-checking",
    "0600": "Inspecting",
    "0700": "AFCI self check",
    "0800": "I-V scanning",
    "0900": "DC input detection",
    "0a00": "Running: off-grid charging",
    "a000": "Standby: no irradiation",
}

grid_codes = {
    0: GridCodes("VDE-AR-N-4105", "Germany"),
    1: GridCodes("NB/T 32004", "China"),
    2: GridCodes("UTE C 15-712-1(A)", "France"),
    3: GridCodes("UTE C 15-712-1(B)", "France"),
    4: GridCodes("UTE C 15-712-1(C)", "France"),
    5: GridCodes("VDE 0126-1-1-BU", "Bulgary"),
    6: GridCodes("VDE 0126-1-1-GR(A)", "Greece"),
    7: GridCodes("VDE 0126-1-1-GR(B)", "Greece"),
    8: GridCodes("BDEW-MV", "Germany"),
    9: GridCodes("G59-England", "UK"),
    10: GridCodes("G59-Scotland", "UK"),
    11: GridCodes("G83-England", "UK"),
    12: GridCodes("G83-Scotland", "UK"),
    13: GridCodes("CEI0-21", "Italy"),
    14: GridCodes("EN50438-CZ", "Czech Republic"),
    15: GridCodes("RD1699/661", "Spain"),
    16: GridCodes("RD1699/661-MV480", "Spain"),
    17: GridCodes("EN50438-NL", "Netherlands"),
    18: GridCodes("C10/11", "Belgium"),
    19: GridCodes("AS4777", "Australia"),
    20: GridCodes("IEC61727", "General"),
    21: GridCodes("Custom (50 Hz)", "Custom"),
    22: GridCodes("Custom (60 Hz)", "Custom"),
    23: GridCodes("CEI0-16", "Italy"),
    24: GridCodes("CHINA-MV480", "China"),
    25: GridCodes("CHINA-MV", "China"),
    26: GridCodes("TAI-PEA", "Thailand"),
    27: GridCodes("TAI-MEA", "Thailand"),
    28: GridCodes("BDEW-MV480", "Germany"),
}
