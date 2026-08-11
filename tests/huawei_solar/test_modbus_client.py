"""Tests for the AsyncHuaweiSolarClient class."""

import struct
from unittest.mock import AsyncMock, MagicMock, patch

import huawei_solar.register_names as rn
import huawei_solar.register_values as rv
import pytest
from huawei_solar.exceptions import ConnectionInterruptedException, DecodeError, ReadException
from huawei_solar.modbus_client import AsyncHuaweiSolarClient, TimeoutAwareSmartTransport
from huawei_solar.register_values import GridCode
from tmodbus.exceptions import IllegalDataValueError, ModbusConnectionError
from tmodbus.transport.async_smart import AsyncSmartTransport


async def test_timeout_aware_transport_forces_reconnect_after_threshold() -> None:
    """A configurable number of consecutive timeouts should trigger a reconnect."""
    transport = TimeoutAwareSmartTransport(MagicMock(), consecutive_timeouts_before_reconnect=2)

    with patch.object(
        AsyncSmartTransport,
        "send_and_receive",
        AsyncMock(side_effect=TimeoutError),
    ) as send_and_receive:
        with pytest.raises(TimeoutError):
            await transport.send_and_receive(1, MagicMock())
        assert not transport._must_reconnect

        with pytest.raises(TimeoutError):
            await transport.send_and_receive(1, MagicMock())
        assert transport._must_reconnect

    assert send_and_receive.await_count == 2


async def test_get_model_name(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.MODEL_NAME)
    assert result.value == "SUN2000-3KTL-L1"
    assert result.unit is None


async def test_get_invalid_model_name(huawei_solar: AsyncHuaweiSolarClient) -> None:
    # invalid utf-8 sequence from here:
    # https://stackoverflow.com/questions/1301402/example-invalid-utf8-string

    value = struct.pack(
        ">15H",
        *[21333, 20018, int.from_bytes(b"\xa0\xa1"), 12336, 12333, 13131, 21580, 226, 0, 0, 0, 0, 0, 226, 10370],
    )

    with patch.object(huawei_solar, "execute", return_value=value):
        result = await huawei_solar.get(rn.MODEL_NAME)
        # Invalid UTF-8 bytes are replaced with backslash escapes
        assert "\\xa0\\xa1" in result.value


async def test_get_serial_number(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.SERIAL_NUMBER)
    assert result.value == "HV3021621085"
    assert result.unit is None


async def test_get_multiple(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get_multiple([rn.MODEL_NAME, rn.SERIAL_NUMBER])
    assert result[0].value == "SUN2000-3KTL-L1"
    assert result[0].unit is None

    assert result[1].value == "HV3021621085"
    assert result[1].unit is None


async def test_get_model_id(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.MODEL_ID)
    assert result.value == 348
    assert result.unit is None


async def test_get_nb_pv_strings(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.NB_PV_STRINGS)
    assert result.value == 2
    assert result.unit is None


async def test_get_nb_mpp_tracks(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.NB_MPP_TRACKS)
    assert result.value == 2
    assert result.unit is None


async def test_get_rated_power(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.RATED_POWER)
    assert result.value == 3000
    assert result.unit == "W"


async def test_get_p_max(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.P_MAX)
    assert result.value == 3300
    assert result.unit == "W"


async def test_get_s_max(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.S_MAX)
    assert result.value == 3300
    assert result.unit == "VA"


async def test_get_q_max_out(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.Q_MAX_OUT)
    assert result.value == 1980
    assert result.unit == "var"


async def test_get_q_max_in(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.Q_MAX_IN)
    assert result.value == -1980
    assert result.unit == "var"


async def test_get_state_1(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.STATE_1)
    assert result.value == ["Standby"]
    assert result.unit is None


async def test_get_state_1_extra_bits_set(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with patch.object(
        huawei_solar,
        "execute",
        return_value=b"\x7c\x00",
    ):
        result = await huawei_solar.get(rn.STATE_1)
        assert result.value == []
        assert result.unit is None


async def test_get_state_2(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.STATE_2)
    assert result.value == ["Locked", "PV disconnected", "No DSP data collection"]
    assert result.unit is None


async def test_get_state_2_extra_bits_set(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with patch.object(
        huawei_solar,
        "execute",
        return_value=b"\x7f\xf8",
    ):
        result = await huawei_solar.get(rn.STATE_2)

        assert result.unit is None


async def test_get_state_3(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.STATE_3)
    assert result.value == ["On-grid", "Off-grid switch disabled"]
    assert result.unit is None


async def test_get_state_3_extra_bits_set(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with patch.object(
        huawei_solar,
        "execute",
        return_value=b"\x7f\xf8\x7f\xff",
    ):
        result = await huawei_solar.get(rn.STATE_3)
        assert result.value == ["Off-grid", "Off-grid switch enabled"]
        assert result.unit is None


async def test_get_alarm_1_some(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.ALARM_1)
    expected_result = [
        rv.ALARM_CODES_1[1],
        rv.ALARM_CODES_1[256],
    ]
    assert result.value == expected_result
    assert result.unit is None


async def test_get_alarm_1_none(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with patch.object(
        huawei_solar,
        "execute",
        return_value=b"\x00\x00",
    ):
        result = await huawei_solar.get(rn.ALARM_1)
        assert result.value == []
        assert result.unit is None


async def test_get_alarm_1_all(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with patch.object(
        huawei_solar,
        "execute",
        return_value=b"\xff\xff",
    ):
        result = await huawei_solar.get(rn.ALARM_1)
        expected_result = list(rv.ALARM_CODES_1.values())
        assert result.value == expected_result
        assert result.unit is None


async def test_get_alarm_2_some(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.ALARM_2)
    expected_result = [
        rv.ALARM_CODES_2[2],
        rv.ALARM_CODES_2[512],
    ]
    assert result.value == expected_result
    assert result.unit is None


async def test_get_alarm_2_none(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with patch.object(
        huawei_solar,
        "execute",
        return_value=b"\x00\x00",
    ):
        result = await huawei_solar.get(rn.ALARM_2)
        expected_result: list[str] = []
        assert result.value == expected_result
        assert result.unit is None


async def test_get_alarm_2_all(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with patch.object(
        huawei_solar,
        "execute",
        return_value=b"\xff\xff",
    ):
        result = await huawei_solar.get(rn.ALARM_2)
        expected_result = list(rv.ALARM_CODES_2.values())
        assert result.value == expected_result
        assert result.unit is None


async def test_get_alarm_3_some(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.ALARM_3)
    expected_result = list(rv.ALARM_CODES_3.values())[0:2] + list(rv.ALARM_CODES_3.values())[3:5]
    assert result.value == expected_result
    assert result.unit is None


async def test_get_alarm_3_almost_all(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with patch.object(
        huawei_solar,
        "execute",
        return_value=b"\x7f\xff",
    ):
        result = await huawei_solar.get(rn.ALARM_3)
        expected_result = list(rv.ALARM_CODES_3.values())[:-1]
        assert result.value == expected_result
        assert result.unit is None


async def test_get_alarm_3_3rd_octet_bits_set(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with patch.object(
        huawei_solar,
        "execute",
        return_value=b"\x0e\x00",
    ):
        result = await huawei_solar.get(rn.ALARM_3)
        expected_result = list(rv.ALARM_CODES_3.values())[9:12]
        assert result.value == expected_result
        assert result.unit is None


async def test_get_pv_01_voltage(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PV_01_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_pv_01_current(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PV_01_CURRENT)
    assert result.value == 0
    assert result.unit == "A"


async def test_get_pv_02_voltage(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PV_02_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_pv_02_current(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PV_02_CURRENT)
    assert result.value == 0
    assert result.unit == "A"


async def test_get_pv_03_voltage(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PV_03_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_pv_03_current(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PV_03_CURRENT)
    assert result.value == 0
    assert result.unit == "A"


async def test_get_pv_04_voltage(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PV_04_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_pv_04_current(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PV_04_CURRENT)
    assert result.value == 0
    assert result.unit == "A"


async def test_get_(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PV_01_VOLTAGE)
    assert result.value == 0.0
    assert result.unit == "V"


async def test_get_input_power(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.INPUT_POWER)
    assert result.value == 0
    assert result.unit == "W"


async def test_get_grid_voltage(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.GRID_VOLTAGE)
    assert result.value == 0.0
    assert result.unit == "V"


async def test_set_negative_i16_register_writes_unsigned_payload(
    huawei_solar: AsyncHuaweiSolarClient,
) -> None:
    """Test writing signed i16 values through a single-register Modbus write."""
    with patch.object(huawei_solar, "write_single_register", return_value=64536) as write_single_register:
        success = await huawei_solar.set(rn.ACTIVE_POWER_PERCENTAGE_DERATING, -100.0)

    assert success is True
    # -100.0 is encoded as -100, which is 0xFF9C in unsigned 16-bit representation, which is 64536 in decimal
    write_single_register.assert_awaited_once_with(40125, 64536)


async def test_get_file_wraps_modbus_response_error(
    huawei_solar: AsyncHuaweiSolarClient,
) -> None:
    with (
        patch.object(
            huawei_solar,
            "execute",
            side_effect=IllegalDataValueError(0x41),
        ),
        pytest.raises(ReadException) as err,
    ):
        await huawei_solar.get_file(0x44)

    assert err.value.modbus_exception_code == IllegalDataValueError.error_code


async def test_get_file_wraps_connection_error(
    huawei_solar: AsyncHuaweiSolarClient,
) -> None:
    with (
        patch.object(
            huawei_solar,
            "execute",
            side_effect=ModbusConnectionError("connection dropped"),
        ),
        pytest.raises(ConnectionInterruptedException),
    ):
        await huawei_solar.get_file(0x44)


async def test_get_line_voltage_a_b(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.LINE_VOLTAGE_A_B)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_line_voltage_b_c(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.LINE_VOLTAGE_B_C)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_line_voltage_c_a(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.LINE_VOLTAGE_C_A)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_line_phase_a_voltage(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PHASE_A_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_line_phase_b_voltage(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PHASE_B_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_line_phase_c_voltage(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PHASE_C_VOLTAGE)
    assert result.value == 0
    assert result.unit == "V"


async def test_get_grid_current(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.GRID_CURRENT)
    assert result.value == 0
    assert result.unit == "A"


async def test_get_phase_a_current(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PHASE_A_CURRENT)
    assert result.value == 0
    assert result.unit == "A"


async def test_get_phase_b_current(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PHASE_B_CURRENT)
    assert result.value == 0
    assert result.unit == "A"


async def test_get_phase_c_current(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.PHASE_C_CURRENT)
    assert result.value == 0
    assert result.unit == "A"


async def test_get_day_active_power_peak(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.DAY_ACTIVE_POWER_PEAK)
    assert result.value == 225
    assert result.unit == "W"


async def test_get_active_power(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.ACTIVE_POWER)
    assert result.value == 0
    assert result.unit == "W"


async def test_get_reactive_power(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.REACTIVE_POWER)
    assert result.value == 0
    assert result.unit == "var"


async def test_get_power_factor(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.POWER_FACTOR)
    assert result.value == 0.0
    assert result.unit is None


async def test_get_grid_frequency(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.GRID_FREQUENCY)
    assert result.value == 0.0
    assert result.unit == "Hz"


async def test_get_efficiency(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.EFFICIENCY)
    assert result.value == 0.0
    assert result.unit == "%"


async def test_get_internal_temperature(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.INTERNAL_TEMPERATURE)
    assert result.value == 0.0
    assert result.unit == "°C"


async def test_get_insulation_resistance(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.INSULATION_RESISTANCE)
    assert result.value == 3.0
    assert result.unit == "MOhm"


async def test_get_device_status(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.DEVICE_STATUS)
    assert result.value == "Standby: no irradiation"
    assert result.unit is None


async def test_get_device_status_invalid(huawei_solar: AsyncHuaweiSolarClient) -> None:
    with (
        patch.object(
            huawei_solar,
            "execute",
            return_value=b"\x02\xff",
        ),
        pytest.raises(DecodeError),
    ):
        await huawei_solar.get(rn.DEVICE_STATUS)


async def test_get_fault_code(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.FAULT_CODE)
    assert result.value == 0
    assert result.unit is None


async def test_get_accumulated_yield_energy(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.ACCUMULATED_YIELD_ENERGY)
    assert result.value == 207.34
    assert result.unit == "kWh"


async def test_get_daily_yield_energy(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.DAILY_YIELD_ENERGY)
    assert result.value == 0.65
    assert result.unit == "kWh"


async def test_get_nb_optimizers(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.NB_OPTIMIZERS)
    assert result.value == 10
    assert result.unit is None


async def test_get_nb_online_optimizers(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.NB_ONLINE_OPTIMIZERS)
    assert result.value == 0
    assert result.unit is None


async def test_get_grid_code(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.GRID_CODE)
    expected_result = GridCode(standard="C10/11", country="Belgium")
    assert result.value == expected_result
    assert result.unit is None


async def test_get_time_zone(huawei_solar: AsyncHuaweiSolarClient) -> None:
    result = await huawei_solar.get(rn.TIME_ZONE)
    assert result.value == 60
    assert result.unit == "min"
