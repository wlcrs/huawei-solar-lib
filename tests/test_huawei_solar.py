from datetime import datetime, timezone
from unittest.mock import patch

import huawei_solar.register_names as rn
import huawei_solar.register_values as rv
import pytest
from huawei_solar.exceptions import DecodeError
from huawei_solar.register_values import GridCode
from pymodbus.register_read_message import ReadHoldingRegistersResponse


@pytest.mark.asyncio()
async def test_get_model_name(huawei_solar):
    result = await huawei_solar.get(rn.MODEL_NAME)
    assert result.value == "SUN2000-3KTL-L1"
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_invalid_model_name(huawei_solar):
    with (
        patch.object(
            huawei_solar,
            "_read_registers",
            return_value=ReadHoldingRegistersResponse(
                [
                    21333,
                    20018,
                    12336,
                    12333,
                    13131,
                    21580,
                    11596,
                    12544,
                    0,
                    0,
                    0,
                    0,
                    0,
                    226,
                    10370,
                ],
            ),
        ),
        pytest.raises(DecodeError),
    ):
        await huawei_solar.get("model_name")
        # invalid utf-8 sequence from here:
        # https://stackoverflow.com/questions/1301402/example-invalid-utf8-string


@pytest.mark.asyncio()
async def test_get_serial_number(huawei_solar):
    result = await huawei_solar.get(rn.SERIAL_NUMBER)
    assert result.value == "HV3021621085"
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_multiple(huawei_solar):
    result = await huawei_solar.get_multiple([rn.MODEL_NAME, rn.SERIAL_NUMBER])
    assert result[0].value == "SUN2000-3KTL-L1"
    assert result[0].unit is None

    assert result[1].value == "HV3021621085"
    assert result[1].unit is None


@pytest.mark.asyncio()
async def test_get_model_id(huawei_solar):
    result = await huawei_solar.get("model_id")
    assert result.value == 348
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_nb_pv_strings(huawei_solar):
    result = await huawei_solar.get("nb_pv_strings")
    assert result.value == 2
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_nb_mpp_tracks(huawei_solar):
    result = await huawei_solar.get("nb_mpp_tracks")
    assert result.value == 2
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_rated_power(huawei_solar):
    result = await huawei_solar.get("rated_power")
    assert result.value == 3000
    assert result.unit == "W"


@pytest.mark.asyncio()
async def test_get_p_max(huawei_solar):
    result = await huawei_solar.get("P_max")
    assert result.value == 3300
    assert result.unit == "W"


@pytest.mark.asyncio()
async def test_get_s_max(huawei_solar):
    result = await huawei_solar.get("S_max")
    assert result.value == 3300
    assert result.unit == "VA"


@pytest.mark.asyncio()
async def test_get_q_max_out(huawei_solar):
    result = await huawei_solar.get("Q_max_out")
    assert result.value == 1980
    assert result.unit == "var"


@pytest.mark.asyncio()
async def test_get_q_max_in(huawei_solar):
    result = await huawei_solar.get("Q_max_in")
    assert result.value == -1980
    assert result.unit == "var"


@pytest.mark.asyncio()
async def test_get_state_1(huawei_solar):
    result = await huawei_solar.get(rn.STATE_1)
    assert result.value == ["Standby"]
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_state_1_extra_bits_set(huawei_solar):
    with patch.object(
        huawei_solar,
        "_read_registers",
        return_value=ReadHoldingRegistersResponse([0b0111_1100_0000_0000]),
    ):
        result = await huawei_solar.get(rn.STATE_1)
        assert result.value == []
        assert result.unit is None


@pytest.mark.asyncio()
async def test_get_state_2(huawei_solar):
    result = await huawei_solar.get(rn.STATE_2)
    assert result.value == ["Locked", "PV disconnected", "No DSP data collection"]
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_state_2_extra_bits_set(huawei_solar):
    with patch.object(
        huawei_solar,
        "_read_registers",
        return_value=ReadHoldingRegistersResponse([0b0111_1111_1111_1000]),
    ):
        result = await huawei_solar.get(rn.STATE_2)

        assert result.unit is None


@pytest.mark.asyncio()
async def test_get_state_3(huawei_solar):
    result = await huawei_solar.get(rn.STATE_3)
    assert result.value == ["On-grid", "Off-grid switch disabled"]
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_state_3_extra_bits_set(huawei_solar):
    with patch.object(
        huawei_solar,
        "_read_registers",
        return_value=ReadHoldingRegistersResponse(
            [0b0111_1111_1111_1111, 0b0111_1111_1111_1111],
        ),
    ):
        result = await huawei_solar.get(rn.STATE_3)
        assert result.value, ["Off-grid", "Off-grid switch enabled"]
        assert result.unit is None


@pytest.mark.asyncio()
async def test_get_alarm_1_some(huawei_solar):
    result = await huawei_solar.get(rn.ALARM_1)
    expected_result = [
        rv.ALARM_CODES_1[1],
        rv.ALARM_CODES_1[256],
    ]
    assert result.value == expected_result
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_alarm_1_none(huawei_solar):
    with patch.object(
        huawei_solar,
        "_read_registers",
        return_value=ReadHoldingRegistersResponse([0]),
    ):
        result = await huawei_solar.get(rn.ALARM_1)
        assert result.value == []
        assert result.unit is None


@pytest.mark.asyncio()
async def test_get_alarm_1_all(huawei_solar):
    with patch.object(
        huawei_solar,
        "_read_registers",
        return_value=ReadHoldingRegistersResponse([0b1111_1111_1111_1111]),
    ):
        result = await huawei_solar.get(rn.ALARM_1)
        expected_result = list(rv.ALARM_CODES_1.values())
        assert result.value == expected_result
        assert result.unit is None


@pytest.mark.asyncio()
async def test_get_alarm_2_some(huawei_solar):
    result = await huawei_solar.get(rn.ALARM_2)
    expected_result = [
        rv.ALARM_CODES_2[2],
        rv.ALARM_CODES_2[512],
    ]
    assert result.value == expected_result
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_alarm_2_none(huawei_solar):
    with patch.object(
        huawei_solar,
        "_read_registers",
        return_value=ReadHoldingRegistersResponse([0]),
    ):
        result = await huawei_solar.get(rn.ALARM_2)
        expected_result = []
        assert result.value == expected_result
        assert result.unit is None


@pytest.mark.asyncio()
async def test_get_alarm_2_all(huawei_solar):
    with patch.object(
        huawei_solar,
        "_read_registers",
        return_value=ReadHoldingRegistersResponse([0b1111_1111_1111_1111]),
    ):
        result = await huawei_solar.get(rn.ALARM_2)
        expected_result = list(rv.ALARM_CODES_2.values())
        assert result.value == expected_result
        assert result.unit is None


@pytest.mark.asyncio()
async def test_get_alarm_3_some(huawei_solar):
    result = await huawei_solar.get(rn.ALARM_3)
    expected_result = list(rv.ALARM_CODES_3.values())[0:2] + list(rv.ALARM_CODES_3.values())[3:5]
    assert result.value == expected_result
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_alarm_3_almost_all(huawei_solar):
    with patch.object(
        huawei_solar,
        "_read_registers",
        return_value=ReadHoldingRegistersResponse([0b0111_1111_1111_1111]),
    ):
        result = await huawei_solar.get(rn.ALARM_3)
        expected_result = list(rv.ALARM_CODES_3.values())[:-1]
        assert result.value == expected_result
        assert result.unit is None


@pytest.mark.asyncio()
async def test_get_alarm_3_3rd_octet_bits_set(huawei_solar):
    with patch.object(
        huawei_solar,
        "_read_registers",
        return_value=ReadHoldingRegistersResponse([0b0000_1110_0000_0000]),
    ):
        result = await huawei_solar.get(rn.ALARM_3)
        expected_result = list(rv.ALARM_CODES_3.values())[9:12]
        assert result.value == expected_result
        assert result.unit is None


@pytest.mark.asyncio()
async def test_get_pv_01_voltage(huawei_solar):
    result = await huawei_solar.get("pv_01_voltage")
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_pv_01_current(huawei_solar):
    result = await huawei_solar.get("pv_01_current")
    assert result.value == 0
    assert result.unit == "A"


@pytest.mark.asyncio()
async def test_get_pv_02_voltage(huawei_solar):
    result = await huawei_solar.get("pv_02_voltage")
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_pv_02_current(huawei_solar):
    result = await huawei_solar.get("pv_02_current")
    assert result.value == 0
    assert result.unit == "A"


@pytest.mark.asyncio()
async def test_get_pv_03_voltage(huawei_solar):
    result = await huawei_solar.get("pv_03_voltage")
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_pv_03_current(huawei_solar):
    result = await huawei_solar.get("pv_03_current")
    assert result.value == 0
    assert result.unit == "A"


@pytest.mark.asyncio()
async def test_get_pv_04_voltage(huawei_solar):
    result = await huawei_solar.get("pv_04_voltage")
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_pv_04_current(huawei_solar):
    result = await huawei_solar.get("pv_04_current")
    assert result.value == 0
    assert result.unit == "A"


@pytest.mark.asyncio()
async def test_get_(huawei_solar):
    result = await huawei_solar.get(rn.PV_01_VOLTAGE)
    assert result.value == 0.0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_input_power(huawei_solar):
    result = await huawei_solar.get(rn.INPUT_POWER)
    assert result.value == 0
    assert result.unit == "W"


@pytest.mark.asyncio()
async def test_get_grid_voltage(huawei_solar):
    result = await huawei_solar.get(rn.GRID_VOLTAGE)
    assert result.value == 0.0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_line_voltage_a_b(huawei_solar):
    result = await huawei_solar.get(rn.LINE_VOLTAGE_A_B)
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_line_voltage_b_c(huawei_solar):
    result = await huawei_solar.get(rn.LINE_VOLTAGE_B_C)
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_line_voltage_c_a(huawei_solar):
    result = await huawei_solar.get(rn.LINE_VOLTAGE_C_A)
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_line_phase_a_voltage(huawei_solar):
    result = await huawei_solar.get(rn.PHASE_A_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_line_phase_b_voltage(huawei_solar):
    result = await huawei_solar.get(rn.PHASE_B_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_line_phase_c_voltage(huawei_solar):
    result = await huawei_solar.get(rn.PHASE_C_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


@pytest.mark.asyncio()
async def test_get_grid_current(huawei_solar):
    result = await huawei_solar.get("grid_current")
    assert result.value == 0
    assert result.unit == "A"


@pytest.mark.asyncio()
async def test_get_phase_a_current(huawei_solar):
    result = await huawei_solar.get("phase_A_current")
    assert result.value == 0
    assert result.unit == "A"


@pytest.mark.asyncio()
async def test_get_phase_b_current(huawei_solar):
    result = await huawei_solar.get("phase_B_current")
    assert result.value == 0
    assert result.unit == "A"


@pytest.mark.asyncio()
async def test_get_phase_c_current(huawei_solar):
    result = await huawei_solar.get("phase_C_current")
    assert result.value == 0
    assert result.unit == "A"


@pytest.mark.asyncio()
async def test_get_day_active_power_peak(huawei_solar):
    result = await huawei_solar.get("day_active_power_peak")
    assert result.value == 225
    assert result.unit == "W"


@pytest.mark.asyncio()
async def test_get_active_power(huawei_solar):
    result = await huawei_solar.get("active_power")
    assert result.value == 0
    assert result.unit == "W"


@pytest.mark.asyncio()
async def test_get_reactive_power(huawei_solar):
    result = await huawei_solar.get("reactive_power")
    assert result.value == 0
    assert result.unit == "var"


@pytest.mark.asyncio()
async def test_get_power_factor(huawei_solar):
    result = await huawei_solar.get("power_factor")
    assert result.value == 0.0
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_grid_frequency(huawei_solar):
    result = await huawei_solar.get("grid_frequency")
    assert result.value == 0.0
    assert result.unit == "Hz"


@pytest.mark.asyncio()
async def test_get_efficiency(huawei_solar):
    result = await huawei_solar.get("efficiency")
    assert result.value == 0.0
    assert result.unit == "%"


@pytest.mark.asyncio()
async def test_get_internal_temperature(huawei_solar):
    result = await huawei_solar.get("internal_temperature")
    assert result.value == 0.0
    assert result.unit == "°C"


@pytest.mark.asyncio()
async def test_get_insulation_resistance(huawei_solar):
    result = await huawei_solar.get(rn.INSULATION_RESISTANCE)
    assert result.value == 3.0
    assert result.unit == "MOhm"


@pytest.mark.asyncio()
async def test_get_device_status(huawei_solar):
    result = await huawei_solar.get(rn.DEVICE_STATUS)
    assert result.value == "Standby: no irradiation"
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_device_status_invalid(huawei_solar):
    with (
        patch.object(
            huawei_solar,
            "_read_registers",
            return_value=ReadHoldingRegistersResponse([0b0000_0010_1111_1111]),
        ),
        pytest.raises(DecodeError),
    ):
        await huawei_solar.get(rn.DEVICE_STATUS)


@pytest.mark.asyncio()
async def test_get_fault_code(huawei_solar):
    result = await huawei_solar.get(rn.FAULT_CODE)
    assert result.value == 0
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_startup_time(huawei_solar):
    result = await huawei_solar.get(rn.STARTUP_TIME)

    assert result.value == datetime(2022, 1, 23, 8, 3, 49, tzinfo=timezone.utc)
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_shutdown_time(huawei_solar):
    result = await huawei_solar.get(rn.SHUTDOWN_TIME)
    assert result.value == datetime(2022, 1, 23, 16, 7, 25, tzinfo=timezone.utc)
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_accumulated_yield_energy(huawei_solar):
    result = await huawei_solar.get(rn.ACCUMULATED_YIELD_ENERGY)
    assert result.value == 207.34
    assert result.unit == "kWh"


@pytest.mark.asyncio()
async def test_get_daily_yield_energy(huawei_solar):
    result = await huawei_solar.get(rn.DAILY_YIELD_ENERGY)
    assert result.value == 0.65
    assert result.unit == "kWh"


@pytest.mark.asyncio()
async def test_get_nb_optimizers(huawei_solar):
    result = await huawei_solar.get(rn.NB_OPTIMIZERS)
    assert result.value == 10
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_nb_online_optimizers(huawei_solar):
    result = await huawei_solar.get(rn.NB_ONLINE_OPTIMIZERS)
    assert result.value == 0
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_system_time(huawei_solar):
    result = await huawei_solar.get(rn.SYSTEM_TIME)
    tmp = datetime(2022, 1, 23, 21, 6, 35, tzinfo=timezone.utc)
    assert result.value == tmp
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_grid_code(huawei_solar):
    result = await huawei_solar.get(rn.GRID_CODE)
    expected_result = GridCode(standard="C10/11", country="Belgium")
    assert result.value == expected_result
    assert result.unit is None


@pytest.mark.asyncio()
async def test_get_time_zone(huawei_solar):
    result = await huawei_solar.get(rn.TIME_ZONE)
    assert result.value == 60
    assert result.unit == "min"
