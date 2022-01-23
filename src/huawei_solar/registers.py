from datetime import datetime, timezone
from dataclasses import dataclass
from enum import IntEnum
from functools import partial

from huawei_solar.exceptions import DecodeError
from .const import METER_STATUS, ALARM_CODES_1, ALARM_CODES_2, ALARM_CODES_3, STATE_CODES_1, STATE_CODES_2, STATE_CODES_3, STORAGE_CHARGE_FROM_GRID, STORAGE_EXCESS_PV_ENERGY_USE_IN_TOU, STORAGE_STATUS_DEFINITIONS, STORAGE_TOU_PRICE, STORAGE_WORKING_MODES_A, STORAGE_WORKING_MODES_B, STORAGE_WORKING_MODES_C, StorageProductModel, DEVICE_STATUS_DEFINITIONS, BACKUP_VOLTAGE_INDEPENDENT_OPERATION, GRID_CODES, METER_TYPE, METER_TYPE_CHECK
from pymodbus.payload import BinaryPayloadDecoder

import typing as t
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .huawei_solar import AsyncHuaweiSolar


@dataclass
class RegisterDefinition:
    def __init__(self, register, length):
        self.register = register
        self.length = length

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        raise NotImplementedError()


class StringRegister(RegisterDefinition):
    def __init__(self, register, length):
        super().__init__(register, length)

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        return decoder.decode_string(self.length * 2).decode("utf-8").strip("\0")


class NumberRegister(RegisterDefinition):
    def __init__(self, unit, gain, register, length, decode_function_name):
        super().__init__(register, length)
        self.unit = unit
        self.gain = gain

        self._decode_function_name = decode_function_name

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        result = getattr(decoder, self._decode_function_name)()

        if self.gain != 1:
            result /= self.gain
        if callable(self.unit):
            result = self.unit(result)
        elif isinstance(self.unit, dict):
            result = self.unit[result]

        return result


class U16Register(NumberRegister):
    def __init__(self, unit, gain, register, length):
        super().__init__(unit, gain, register, length, "decode_16bit_uint")


class U32Register(NumberRegister):
    def __init__(self, unit, gain, register, length):
        super().__init__(unit, gain, register, length, "decode_32bit_uint")


class I16Register(NumberRegister):
    def __init__(self, unit, gain, register, length):
        super().__init__(unit, gain, register, length, "decode_16bit_int")


class I32Register(NumberRegister):
    def __init__(self, unit, gain, register, length):
        super().__init__(unit, gain, register, length, "decode_32bit_int")


def bitfield_decoder(definition, value):
    result = []
    for key, value in definition.items():
        if key & value:
            result.append(value)

    return result


class TimestampRegister(U32Register):
    def __init__(self, register, length):
        super().__init__(None, 1, register, length)

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        value = super().decode(decoder, inverter)

        try:
            return datetime.fromtimestamp(value - 60 * inverter.time_zone, timezone.utc)
        except OverflowError as err:
            raise DecodeError(f"Received invalid timestamp {value}") from err


@dataclass
class LG_RESU_TimeOfUsePeriod:
    start_time: int  # minutes sinds midnight
    end_time: int  # minutes sinds midnight
    electricity_price: float


class ChargeFlag(IntEnum):
    Charge = 0
    Discharge = 1


@dataclass
class HUAWEI_LUNA2000_TimeOfUsePeriod:
    start_time: int  # minutes sinds midnight
    end_time: int  # minutes sinds midnight
    charge_flag: ChargeFlag
    days_effective: t.Tuple[
        bool, bool, bool, bool, bool, bool, bool
    ]  # Valid on days Sunday to Saturday


class TimeOfUseRegisters(RegisterDefinition):
    def __init__(self, register, length):
        super().__init__(register, length)

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        if inverter.battery_type == StorageProductModel.LG_RESU:
            return self.decode_lg_resu(decoder)
        elif inverter.battery_type == StorageProductModel.HUAWEI_LUNA2000:
            return self.decode_huawei_luna2000(decoder)
        else:
            return DecodeError(
                f"Invalid model to decode TOU Registers for: {inverter.battery_type}"
            )

    def decode_lg_resu(self, decoder: BinaryPayloadDecoder):
        number_of_periods = decoder.decode_16bit_uint()
        assert number_of_periods <= 10

        periods = []
        for _ in range(number_of_periods):
            periods.append(
                LG_RESU_TimeOfUsePeriod(
                    decoder.decode_16bit_uint(),
                    decoder.decode_16bit_uint(),
                    decoder.decode_32bit_uint() / 1000,
                )
            )

        return periods

    def decode_huawei_luna2000(self, decoder: BinaryPayloadDecoder):
        number_of_periods = decoder.decode_16bit_uint()
        assert number_of_periods <= 14

        def _days_effective_parser(value):
            result = []
            mask = 0x1
            for _ in range(7):
                result.append((value & mask) != 0)
                mask = mask << 1

            return tuple(result)

        periods = []
        for _ in range(number_of_periods):
            periods.append(
                HUAWEI_LUNA2000_TimeOfUsePeriod(
                    decoder.decode_16bit_uint(),
                    decoder.decode_16bit_uint(),
                    ChargeFlag(decoder.decode_8bit_uint()),
                    _days_effective_parser(decoder.decode_8bit_uint()),
                )
            )

        return periods


class ChargeDischargePeriod:
    start_time: int  # minutes sinds midnight
    end_time: int  # minutes sinds midnight
    power: int  # power in watts


class ChargeDischargePeriodRegisters(RegisterDefinition):
    def __init__(self, register, length):
        super().__init__(register, length)

    def decode(self, decoder: BinaryPayloadDecoder, inverter: "AsyncHuaweiSolar"):
        number_of_periods = decoder.decode_16bit_uint()
        assert number_of_periods <= 10

        periods = []
        for _ in range(number_of_periods):
            periods.append(
                ChargeDischargePeriod(
                    decoder.decode_16bit_uint(),
                    decoder.decode_16bit_uint(),
                    decoder.decode_32bit_int(),
                )
            )

        return periods


REGISTERS = {
    "model_name": StringRegister(30000, 15),
    "serial_number": StringRegister(30015, 10),
    "model_id": U16Register(None, 1, 30070, 1),
    "nb_pv_strings": U16Register(None, 1, 30071, 1),
    "nb_mpp_tracks": U16Register(None, 1, 30072, 1),
    "rated_power": U32Register("W", 1, 30073, 2),
    "P_max": U32Register("W", 1, 30075, 2),
    "S_max": U32Register("VA", 1, 30077, 2),
    "Q_max_out": I32Register("VAr", 1, 30079, 2),
    "Q_max_in": I32Register("VAr", 1, 30081, 2),
    "state_1": U16Register(partial(bitfield_decoder, STATE_CODES_1), 1, 32000, 1),
    "state_2": U16Register(partial(bitfield_decoder, STATE_CODES_2), 1, 32002, 1),
    "state_3": U32Register(partial(bitfield_decoder, STATE_CODES_3), 1, 32003, 2),
    "alarm_1": U16Register(partial(bitfield_decoder, ALARM_CODES_1), 1, 32008, 1),
    "alarm_2": U16Register(partial(bitfield_decoder, ALARM_CODES_2), 1, 32009, 1),
    "alarm_3": U16Register(partial(bitfield_decoder, ALARM_CODES_3), 1, 32010, 1),
    "input_power": I32Register("W", 1, 32064, 2),
    "grid_voltage": U16Register("V", 10, 32066, 1),
    "line_voltage_A_B": U16Register("V", 10, 32066, 1),
    "line_voltage_B_C": U16Register("V", 10, 32067, 1),
    "line_voltage_C_A": U16Register("V", 10, 32068, 1),
    "phase_A_voltage": U16Register("V", 10, 32069, 1),
    "phase_B_voltage": U16Register("V", 10, 32070, 1),
    "phase_C_voltage": U16Register("V", 10, 32071, 1),
    "grid_current": I32Register("A", 1000, 32072, 2),
    "phase_A_current": I32Register("A", 1000, 32072, 2),
    "phase_B_current": I32Register("A", 1000, 32074, 2),
    "phase_C_current": I32Register("A", 1000, 32076, 2),
    "day_active_power_peak": I32Register("W", 1, 32078, 2),
    "active_power": I32Register("W", 1, 32080, 2),
    "reactive_power": I32Register("VA", 1, 32082, 2),
    "power_factor": I16Register(None, 1000, 32084, 1),
    "grid_frequency": U16Register("Hz", 100, 32085, 1),
    "efficiency": U16Register("%", 100, 32086, 1),
    "internal_temperature": I16Register("°C", 10, 32087, 1),
    "insulation_resistance": U16Register("MOhm", 100, 32088, 1),
    "device_status": U16Register(DEVICE_STATUS_DEFINITIONS, 1, 32089, 1),
    "fault_code": U16Register(None, 1, 32090, 1),
    "startup_time": TimestampRegister(32091, 2),
    "shutdown_time": TimestampRegister(32093, 2),
    "accumulated_yield_energy": U32Register("kWh", 100, 32106, 2),
    # last contact with server?
    "unknown_time_1": TimestampRegister(32110, 2),
    "daily_yield_energy": U32Register("kWh", 100, 32114, 2),
    # something todo with startup time?
    "unknown_time_2": TimestampRegister(32156, 2),
    # something todo with shutdown time?
    "unknown_time_3": TimestampRegister(32160, 2),
    # installation time?
    "unknown_time_4": TimestampRegister(35113, 2),
    "nb_optimizers": U16Register(None, 1, 37200, 1),
    "meter_type_check": U16Register(METER_TYPE_CHECK, 1, 37125, 2),
    "nb_online_optimizers": U16Register(None, 1, 37201, 1),
    "system_time": TimestampRegister(40000, 2),
    # seems to be the same as unknown_time_4
    "unknown_time_5": TimestampRegister(40500, 2),
    "grid_code": U16Register(GRID_CODES, 1, 42000, 1),
    "time_zone": I16Register("min", 1, 43006, 1),
}


OPTIMIZER_REGISTERS = {
    "pv_01_voltage": I16Register("V", 10, 32016, 1),
    "pv_01_current": I16Register("A", 100, 32017, 1),
    "pv_02_voltage": I16Register("V", 10, 32018, 1),
    "pv_02_current": I16Register("A", 100, 32019, 1),
    "pv_03_voltage": I16Register("V", 10, 32020, 1),
    "pv_03_current": I16Register("A", 100, 32021, 1),
    "pv_04_voltage": I16Register("V", 10, 32022, 1),
    "pv_04_current": I16Register("A", 100, 32023, 1),
    "pv_05_voltage": I16Register("V", 10, 32024, 1),
    "pv_05_current": I16Register("A", 100, 32025, 1),
    "pv_06_voltage": I16Register("V", 10, 32026, 1),
    "pv_06_current": I16Register("A", 100, 32027, 1),
    "pv_07_voltage": I16Register("V", 10, 32028, 1),
    "pv_07_current": I16Register("A", 100, 32029, 1),
    "pv_08_voltage": I16Register("V", 10, 32030, 1),
    "pv_08_current": I16Register("A", 100, 32031, 1),
    "pv_09_voltage": I16Register("V", 10, 32032, 1),
    "pv_09_current": I16Register("A", 100, 32033, 1),
    "pv_10_voltage": I16Register("V", 10, 32034, 1),
    "pv_10_current": I16Register("A", 100, 32035, 1),
    "pv_11_voltage": I16Register("V", 10, 32036, 1),
    "pv_11_current": I16Register("A", 100, 32037, 1),
    "pv_12_voltage": I16Register("V", 10, 32038, 1),
    "pv_12_current": I16Register("A", 100, 32039, 1),
    "pv_13_voltage": I16Register("V", 10, 32040, 1),
    "pv_13_current": I16Register("A", 100, 32041, 1),
    "pv_14_voltage": I16Register("V", 10, 32042, 1),
    "pv_14_current": I16Register("A", 100, 32043, 1),
    "pv_15_voltage": I16Register("V", 10, 32044, 1),
    "pv_15_current": I16Register("A", 100, 32045, 1),
    "pv_16_voltage": I16Register("V", 10, 32046, 1),
    "pv_16_current": I16Register("A", 100, 32047, 1),
    "pv_17_voltage": I16Register("V", 10, 32048, 1),
    "pv_17_current": I16Register("A", 100, 32049, 1),
    "pv_18_voltage": I16Register("V", 10, 32050, 1),
    "pv_18_current": I16Register("A", 100, 32051, 1),
    "pv_19_voltage": I16Register("V", 10, 32052, 1),
    "pv_19_current": I16Register("A", 100, 32053, 1),
    "pv_20_voltage": I16Register("V", 10, 32054, 1),
    "pv_20_current": I16Register("A", 100, 32055, 1),
    "pv_21_voltage": I16Register("V", 10, 32056, 1),
    "pv_21_current": I16Register("A", 100, 32057, 1),
    "pv_22_voltage": I16Register("V", 10, 32058, 1),
    "pv_22_current": I16Register("A", 100, 32059, 1),
    "pv_23_voltage": I16Register("V", 10, 32060, 1),
    "pv_23_current": I16Register("A", 100, 32061, 1),
    "pv_24_voltage": I16Register("V", 10, 32062, 1),
    "pv_24_current": I16Register("A", 100, 32063, 1),
}

REGISTERS.update(OPTIMIZER_REGISTERS)

BATTERY_REGISTERS = {
    "storage_unit_1_running_status": U16Register(
        STORAGE_STATUS_DEFINITIONS, 1, 37000, 1
    ),
    "storage_unit_1_charge_discharge_power": I32Register("W", 1, 37001, 2),
    "storage_unit_1_bus_voltage": U16Register("V", 10, 37003, 1),
    "storage_unit_1_state_of_capacity": U16Register("%", 10, 37004, 1),
    "storage_unit_1_working_mode_b": U16Register(STORAGE_WORKING_MODES_B, 1, 37006, 1),
    "storage_unit_1_rated_charge_power": U32Register("W", 1, 37007, 2),
    "storage_unit_1_rated_discharge_power": U32Register("W", 1, 37009, 2),
    "storage_unit_1_fault_id": U16Register(None, 1, 37014, 1),
    "storage_unit_1_current_day_charge_capacity": U32Register("kWh", 100, 37015, 2),
    "storage_unit_1_current_day_discharge_capacity": U32Register("kWh", 100, 37017, 2),
    "storage_unit_1_bus_current": I16Register("A", 10, 37021, 1),
    "storage_unit_1_battery_temperature": I16Register("°C", 10, 37022, 1),
    "storage_unit_1_remaining_charge_dis_charge_time": U16Register("min", 1, 37025, 1),
    "storage_unit_1_dcdc_version": StringRegister(37026, 10),
    "storage_unit_1_bms_version": StringRegister(37036, 10),
    "storage_maximum_charge_power": U32Register("W", 1, 37046, 2),
    "storage_maximum_discharge_power": U32Register("W", 1, 37048, 2),
    "storage_unit_1_serial_number": StringRegister(37052, 10),
    "storage_unit_1_total_charge": U32Register("kWh", 100, 37066, 2),
    "storage_unit_1_total_discharge": U32Register("kWh", 100, 37068, 2),
    "storage_unit_2_serial_number": StringRegister(37700, 10),
    "storage_unit_2_state_of_capacity": U16Register("%", 10, 37738, 1),
    "storage_unit_2_running_status": U16Register(
        STORAGE_STATUS_DEFINITIONS, 1, 37741, 1
    ),
    "storage_unit_2_charge_discharge_power": I32Register("W", 1, 37743, 2),
    "storage_unit_2_current_day_charge_capacity": U32Register("kWh", 100, 37746, 2),
    "storage_unit_2_current_day_discharge_capacity": U32Register("kWh", 100, 37748, 2),
    "storage_unit_2_bus_voltage": U16Register("V", 10, 37750, 1),
    "storage_unit_2_bus_current": I16Register("A", 10, 37751, 1),
    "storage_unit_2_battery_temperature": I16Register("°C", 10, 37752, 1),
    "storage_unit_2_total_charge": U32Register("kWh", 100, 37753, 2),
    "storage_unit_2_total_discharge": U32Register("kWh", 100, 37755, 2),
    "storage_rated_capacity": U32Register("Wh", 1, 37758, 2),
    "storage_state_of_capacity": U16Register("%", 10, 37760, 1),
    "storage_running_status": U16Register(STORAGE_STATUS_DEFINITIONS, 1, 37762, 1),
    "storage_bus_voltage": U16Register("V", 10, 37763, 1),
    "storage_bus_current": I16Register("A", 10, 37764, 1),
    "storage_charge_discharge_power": I32Register("W", 1, 37765, 2),
    "storage_total_charge": U32Register("kWh", 100, 37780, 2),
    "storage_total_discharge": U32Register("kWh", 100, 37782, 2),
    "storage_current_day_charge_capacity": U32Register("kWh", 100, 37784, 2),
    "storage_current_day_discharge_capacity": U32Register("kWh", 100, 37786, 2),
    "storage_unit_2_software_version": StringRegister(37799, 15),
    "storage_unit_1_software_version": StringRegister(37814, 15),
    "storage_unit_1_battery_pack_1_serial_number": StringRegister(38200, 10),
    "storage_unit_1_battery_pack_1_firmware_version": StringRegister(38210, 15),
    "storage_unit_1_battery_pack_1_working_status": U16Register(None, 1, 38228, 1),
    "storage_unit_1_battery_pack_1_state_of_capacity": U16Register("%", 10, 38229, 1),
    "storage_unit_1_battery_pack_1_charge_discharge_power": I32Register(
        "W", 1, 38233, 2
    ),
    "storage_unit_1_battery_pack_1_voltage": U16Register("V", 10, 38235, 1),
    "storage_unit_1_battery_pack_1_current": I16Register("A", 10, 38236, 1),
    "storage_unit_1_battery_pack_1_total_charge": U32Register("kWh", 100, 38238, 2),
    "storage_unit_1_battery_pack_1_total_discharge": U32Register("kWh", 100, 38240, 2),
    "storage_unit_1_battery_pack_2_serial_number": StringRegister(38242, 10),
    "storage_unit_1_battery_pack_2_firmware_version": StringRegister(38252, 15),
    "storage_unit_1_battery_pack_2_working_status": U16Register(None, 1, 38270, 1),
    "storage_unit_1_battery_pack_2_state_of_capacity": U16Register("%", 10, 38271, 1),
    "storage_unit_1_battery_pack_2_charge_discharge_power": I32Register(
        "W", 1, 38275, 2
    ),
    "storage_unit_1_battery_pack_2_voltage": U16Register("V", 10, 38277, 1),
    "storage_unit_1_battery_pack_2_current": I16Register("A", 10, 38278, 1),
    "storage_unit_1_battery_pack_2_total_charge": U32Register("kWh", 100, 38280, 2),
    "storage_unit_1_battery_pack_2_total_discharge": U32Register("kWh", 100, 38282, 2),
    "storage_unit_1_battery_pack_3_serial_number": StringRegister(38284, 10),
    "storage_unit_1_battery_pack_3_firmware_version": StringRegister(38294, 15),
    "storage_unit_1_battery_pack_3_working_status": U16Register(None, 1, 38312, 1),
    "storage_unit_1_battery_pack_3_state_of_capacity": U16Register("%", 10, 38313, 1),
    "storage_unit_1_battery_pack_3_charge_discharge_power": I32Register(
        "W", 1, 38317, 2
    ),
    "storage_unit_1_battery_pack_3_voltage": U16Register("V", 10, 38319, 1),
    "storage_unit_1_battery_pack_3_current": I16Register("A", 10, 38320, 1),
    "storage_unit_1_battery_pack_3_total_charge": U32Register("kWh", 100, 38322, 2),
    "storage_unit_1_battery_pack_3_total_discharge": U32Register("kWh", 100, 38324, 2),
    "storage_unit_2_battery_pack_1_serial_number": StringRegister(38326, 10),
    "storage_unit_2_battery_pack_1_firmware_version": StringRegister(38336, 15),
    "storage_unit_2_battery_pack_1_working_status": U16Register(None, 1, 38354, 1),
    "storage_unit_2_battery_pack_1_state_of_capacity": U16Register("%", 10, 38355, 1),
    "storage_unit_2_battery_pack_1_charge_discharge_power": I32Register(
        "W", 1, 38359, 2
    ),
    "storage_unit_2_battery_pack_1_voltage": U16Register("V", 10, 38361, 1),
    "storage_unit_2_battery_pack_1_current": I16Register("A", 10, 38362, 1),
    "storage_unit_2_battery_pack_1_total_charge": U32Register("kWh", 100, 38364, 2),
    "storage_unit_2_battery_pack_1_total_discharge": U32Register("kWh", 100, 38366, 2),
    "storage_unit_2_battery_pack_2_serial_number": StringRegister(38368, 10),
    "storage_unit_2_battery_pack_2_firmware_version": StringRegister(38378, 15),
    "storage_unit_2_battery_pack_2_working_status": U16Register(None, 1, 38396, 1),
    "storage_unit_2_battery_pack_2_state_of_capacity": U16Register("%", 10, 38397, 1),
    "storage_unit_2_battery_pack_2_charge_discharge_power": I32Register(
        "W", 1, 38401, 2
    ),
    "storage_unit_2_battery_pack_2_voltage": U16Register("V", 10, 38403, 1),
    "storage_unit_2_battery_pack_2_current": I16Register("A", 10, 38404, 1),
    "storage_unit_2_battery_pack_2_total_charge": U32Register("kWh", 100, 38406, 2),
    "storage_unit_2_battery_pack_2_total_discharge": U32Register("kWh", 100, 38408, 2),
    "storage_unit_2_battery_pack_3_serial_number": StringRegister(38410, 10),
    "storage_unit_2_battery_pack_3_firmware_version": StringRegister(38420, 15),
    "storage_unit_2_battery_pack_3_working_status": U16Register(None, 1, 38438, 1),
    "storage_unit_2_battery_pack_3_state_of_capacity": U16Register("%", 10, 38439, 1),
    "storage_unit_2_battery_pack_3_charge_discharge_power": I32Register(
        "W", 1, 38443, 2
    ),
    "storage_unit_2_battery_pack_3_voltage": U16Register("V", 10, 38445, 1),
    "storage_unit_2_battery_pack_3_current": I16Register("A", 10, 38446, 1),
    "storage_unit_2_battery_pack_3_total_charge": U32Register("kWh", 100, 38448, 2),
    "storage_unit_2_battery_pack_3_total_discharge": U32Register("kWh", 100, 38450, 2),
    "storage_unit_1_battery_pack_1_maximum_temperature": I16Register(
        "°C", 10, 38452, 1
    ),
    "storage_unit_1_battery_pack_1_minimum_temperature": I16Register(
        "°C", 10, 38453, 1
    ),
    "storage_unit_1_battery_pack_2_maximum_temperature": I16Register(
        "°C", 10, 38454, 1
    ),
    "storage_unit_1_battery_pack_2_minimum_temperature": I16Register(
        "°C", 10, 38455, 1
    ),
    "storage_unit_1_battery_pack_3_maximum_temperature": I16Register(
        "°C", 10, 38456, 1
    ),
    "storage_unit_1_battery_pack_3_minimum_temperature": I16Register(
        "°C", 10, 38457, 1
    ),
    "storage_unit_2_battery_pack_1_maximum_temperature": I16Register(
        "°C", 10, 38458, 1
    ),
    "storage_unit_2_battery_pack_1_minimum_temperature": I16Register(
        "°C", 10, 38459, 1
    ),
    "storage_unit_2_battery_pack_2_maximum_temperature": I16Register(
        "°C", 10, 38460, 1
    ),
    "storage_unit_2_battery_pack_2_minimum_temperature": I16Register(
        "°C", 10, 38461, 1
    ),
    "storage_unit_2_battery_pack_3_maximum_temperature": I16Register(
        "°C", 10, 38462, 1
    ),
    "storage_unit_2_battery_pack_3_minimum_temperature": I16Register(
        "°C", 10, 38463, 1
    ),
    "storage_unit_1_product_model": U16Register(StorageProductModel, 1, 47000, 1),
    "storage_working_mode_a": I16Register(STORAGE_WORKING_MODES_A, 1, 47004, 1),
    "storage_time_of_use_price": I16Register(STORAGE_TOU_PRICE, 1, 47027, 1),
    "storage_time_of_use_price_periods": TimeOfUseRegisters(47028, 41),
    "storage_lcoe": U32Register(None, 1000, 47069, 2),
    "storage_maximum_charging_power": U32Register("W", 1, 47075, 2),
    "storage_maximum_discharging_power": U32Register("W", 1, 47077, 2),
    "storage_power_limit_grid_tied_point": I32Register("W", 1, 47079, 2),
    "storage_charging_cutoff_capacity": U16Register("%", 10, 47081, 1),
    "storage_discharging_cutoff_capacity": U16Register("%", 10, 47082, 1),
    "storage_forced_charging_and_discharging_period": U16Register("min", 1, 47083, 1),
    "storage_forced_charging_and_discharging_power": I32Register("min", 1, 47084, 2),
    "storage_working_mode_settings": U16Register(STORAGE_WORKING_MODES_C, 1, 47086, 1),
    "storage_charge_from_grid_function": U16Register(
        STORAGE_CHARGE_FROM_GRID, 1, 47087, 1
    ),
    "storage_grid_charge_cutoff_state_of_charge": U16Register("%", 1, 47088, 1),
    "storage_unit_2_product_model": U16Register(StorageProductModel, 1, 47089, 1),
    "storage_backup_power_state_of_charge": U16Register("%", 10, 47102, 1),
    "storage_unit_1_no": U16Register(None, 1, 47107, 1),
    "storage_unit_2_no": U16Register(None, 1, 47108, 1),
    "storage_fixed_charging_and_discharging_periods": ChargeDischargePeriodRegisters(
        47200, 41
    ),
    "storage_power_of_charge_from_grid": U32Register("W", 1, 47242, 2),
    "storage_maximum_power_of_charge_from_grid": U32Register("W", 1, 47244, 2),
    "storage_forcible_charge_discharge_setting_mode": U16Register(None, 1, 47246, 2),
    "storage_forcible_charge_power": U32Register(None, 1, 47247, 2),
    "storage_forcible_discharge_power": U32Register(None, 1, 47249, 2),
    "storage_time_of_use_charging_and_discharging_periods": TimeOfUseRegisters(
        47255, 43
    ),
    "storage_excess_pv_energy_use_in_tou": U16Register(
        STORAGE_EXCESS_PV_ENERGY_USE_IN_TOU, 1, 47299, 1
    ),
    "dongle_plant_maximum_charge_from_grid_power": U32Register("W", 1, 47590, 2),
    "backup_switch_to_off_grid": U16Register(None, 1, 47604, 1),
    "backup_voltage_independend_operation": U16Register(
        BACKUP_VOLTAGE_INDEPENDENT_OPERATION, 1, 47604, 1
    ),
    "storage_unit_1_pack_1_no": U16Register(None, 1, 47750, 1),
    "storage_unit_1_pack_2_no": U16Register(None, 1, 47751, 1),
    "storage_unit_1_pack_3_no": U16Register(None, 1, 47752, 1),
    "storage_unit_2_pack_1_no": U16Register(None, 1, 47753, 1),
    "storage_unit_2_pack_2_no": U16Register(None, 1, 47754, 1),
    "storage_unit_2_pack_3_no": U16Register(None, 1, 47755, 1),
}

REGISTERS.update(BATTERY_REGISTERS)

METER_REGISTERS = {
    "meter_status": U16Register(METER_STATUS, 1, 37100, 1),
    "grid_A_voltage": I32Register("V", 10, 37101, 2),
    "grid_B_voltage": I32Register("V", 10, 37103, 2),
    "grid_C_voltage": I32Register("V", 10, 37105, 2),
    "active_grid_A_current": I32Register("I", 100, 37107, 2),
    "active_grid_B_current": I32Register("I", 100, 37109, 2),
    "active_grid_C_current": I32Register("I", 100, 37111, 2),
    "power_meter_active_power": I32Register("W", 1, 37113, 2),
    "power_meter_reactive_power": I32Register("Var", 1, 37115, 2),
    "active_grid_power_factor": I16Register(None, 1000, 37117, 1),
    "active_grid_frequency": I16Register("Hz", 100, 37118, 1),
    "grid_exported_energy": I32Register("kWh", 100, 37119, 2),
    "grid_accumulated_energy": U32Register("kWh", 100, 37121, 2),
    "grid_accumulated_reactive_power": U32Register("kVarh", 100, 37123, 2),
    "meter_type": U16Register(METER_TYPE, 1, 37125, 1),
    "active_grid_A_B_voltage": I32Register("V", 10, 37126, 2),
    "active_grid_B_C_voltage": I32Register("V", 10, 37128, 2),
    "active_grid_C_A_voltage": I32Register("V", 10, 37130, 2),
    "active_grid_A_power": I32Register("W", 1, 37132, 2),
    "active_grid_B_power": I32Register("W", 1, 37134, 2),
    "active_grid_C_power": I32Register("W", 1, 37136, 2),
}

REGISTERS.update(METER_REGISTERS)
