import unittest
from datetime import datetime
from unittest.mock import patch

import mock_huawei_solar
import pytz
import src.huawei_solar.huawei_solar as huawei_solar


class TestHuaweiSolar(unittest.TestCase):
    def setUp(self):
        self.api_instance = huawei_solar.HuaweiSolar("192.0.2.0", wait=0, timeout=0)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_model_name(self):
        result = self.api_instance.get("model_name")
        self.assertEqual(result.value, "SUN2000L-3KTL")
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_serial_number(self):
        result = self.api_instance.get("serial_number")
        self.assertEqual(result.value, "0000000000HVK0000000")
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_model_id(self):
        result = self.api_instance.get("model_id")
        self.assertEqual(result.value, 304)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_nb_pv_strings(self):
        result = self.api_instance.get("nb_pv_strings")
        self.assertEqual(result.value, 2)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_nb_mpp_tracks(self):
        result = self.api_instance.get("nb_mpp_tracks")
        self.assertEqual(result.value, 2)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_rated_power(self):
        result = self.api_instance.get("rated_power")
        self.assertEqual(result.value, 3000)
        self.assertEqual(result.unit, "W")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_P_max(self):
        result = self.api_instance.get("P_max")
        self.assertEqual(result.value, 3300)
        self.assertEqual(result.unit, "W")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_S_max(self):
        result = self.api_instance.get("S_max")
        self.assertEqual(result.value, 3300)
        self.assertEqual(result.unit, "VA")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_Q_max_out(self):
        result = self.api_instance.get("Q_max_out")
        self.assertEqual(result.value, 1980)
        self.assertEqual(result.unit, "VAr")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_Q_max_in(self):
        result = self.api_instance.get("Q_max_in")
        self.assertEqual(result.value, -1980)
        self.assertEqual(result.unit, "VAr")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_state_1(self):
        result = self.api_instance.get("state_1")
        self.assertEqual(result.value, ["grid-connected", "grid-connected normally"])
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_state_2(self):
        result = self.api_instance.get("state_2")
        self.assertEqual(
            result.value, ["unlocked", "PV connected", "DSP data collection"]
        )
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_state_3(self):
        result = self.api_instance.get("state_3")
        self.assertEqual(result.value, ["on-grid", "off-grid switch disabled"])
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_alarm_1_some(self):
        result = self.api_instance.get("alarm_1")
        expected_result = [
            huawei_solar.ALARM_CODES_1[1],
            huawei_solar.ALARM_CODES_1[256],
        ]
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32008, 1): b"\x02\x00\x00"})
    def test_get_alarm_1_none(self):
        result = self.api_instance.get("alarm_1")
        self.assertEqual(result.value, [])
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32008, 1): b"\x02\xff\xff"})
    def test_get_alarm_1_all(self):
        result = self.api_instance.get("alarm_1")
        expected_result = list(huawei_solar.ALARM_CODES_1.values())
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_alarm_2_some(self):
        result = self.api_instance.get("alarm_2")
        expected_result = [
            huawei_solar.ALARM_CODES_2[2],
            huawei_solar.ALARM_CODES_2[512],
        ]
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32009, 1): b"\x02\x00\x00"})
    def test_get_alarm_2_none(self):
        result = self.api_instance.get("alarm_2")
        expected_result = []
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32009, 1): b"\x02\xff\xff"})
    def test_get_alarm_2_all(self):
        result = self.api_instance.get("alarm_2")
        expected_result = list(huawei_solar.ALARM_CODES_2.values())
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_alarm_3_some(self):
        result = self.api_instance.get("alarm_3")
        expected_result = [
            huawei_solar.ALARM_CODES_3[4],
            huawei_solar.ALARM_CODES_3[256],
        ]
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32010, 1): b"\x02\x00\x00"})
    def test_get_alarm_3_none(self):
        result = self.api_instance.get("alarm_3")
        expected_result = []
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32010, 1): b"\x02\x01\xff"})
    def test_get_alarm_3_all(self):
        result = self.api_instance.get("alarm_3")
        expected_result = list(huawei_solar.ALARM_CODES_3.values())
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_01_voltage(self):
        result = self.api_instance.get("pv_01_voltage")
        self.assertEqual(result.value, 192)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_01_current(self):
        result = self.api_instance.get("pv_01_current")
        self.assertEqual(result.value, 1.78)
        self.assertEqual(result.unit, "A")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_02_voltage(self):
        result = self.api_instance.get("pv_02_voltage")
        self.assertEqual(result.value, 125.4)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_02_current(self):
        result = self.api_instance.get("pv_02_current")
        self.assertEqual(result.value, 2.24)
        self.assertEqual(result.unit, "A")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_03_voltage(self):
        result = self.api_instance.get("pv_03_voltage")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_03_current(self):
        result = self.api_instance.get("pv_03_current")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "A")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_04_voltage(self):
        result = self.api_instance.get("pv_04_voltage")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_04_current(self):
        result = self.api_instance.get("pv_04_current")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "A")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_05_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_05_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_05_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_05_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_06_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_06_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_06_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_06_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_07_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_07_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_07_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_07_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_08_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_08_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_08_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_08_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_09_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_09_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_09_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_09_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_10_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_10_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_10_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_10_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_11_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_11_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_11_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_11_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_12_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_12_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_12_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_12_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_13_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_13_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_13_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_13_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_14_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_14_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_14_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_14_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_15_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_15_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_15_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_15_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_16_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_16_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_16_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_16_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_17_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_17_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_17_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_17_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_18_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_18_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_18_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_18_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_19_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_19_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_19_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_19_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_20_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_20_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_20_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_20_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_21_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_21_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_21_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_21_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_22_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_22_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_22_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_22_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_23_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_23_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_23_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_23_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_24_voltage(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_24_voltage")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_24_current(self):
        with self.assertRaises(Exception) as context_manager:
            self.api_instance.get("pv_24_current")
            message = "could not read register value"
            self.assertEqual(str(context_manager.exception), message)
            self.assertEqual(str(context_manager.exception), message)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_(self):
        result = self.api_instance.get("pv_01_voltage")
        self.assertEqual(result.value, 192)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_input_power(self):
        result = self.api_instance.get("input_power")
        self.assertEqual(result.value, 912)
        self.assertEqual(result.unit, "W")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_grid_voltage(self):
        result = self.api_instance.get("grid_voltage")
        self.assertEqual(result.value, 229.7)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_line_voltage_A_B(self):
        result = self.api_instance.get("line_voltage_A_B")
        self.assertEqual(result.value, 229.7)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_line_voltage_B_C(self):
        result = self.api_instance.get("line_voltage_B_C")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_line_voltage_C_A(self):
        result = self.api_instance.get("line_voltage_C_A")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_line_phase_A_voltage(self):
        result = self.api_instance.get("phase_A_voltage")
        self.assertEqual(result.value, 235.0)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_line_phase_B_voltage(self):
        result = self.api_instance.get("phase_B_voltage")
        self.assertEqual(result.value, 199.7)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_line_phase_C_voltage(self):
        result = self.api_instance.get("phase_C_voltage")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_grid_current(self):
        result = self.api_instance.get("grid_current")
        self.assertEqual(result.value, 2.803)
        self.assertEqual(result.unit, "A")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_phase_A_current(self):
        result = self.api_instance.get("phase_A_current")
        self.assertEqual(result.value, 2.803)
        self.assertEqual(result.unit, "A")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_phase_B_current(self):
        result = self.api_instance.get("phase_B_current")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "A")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_phase_C_current(self):
        result = self.api_instance.get("phase_C_current")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "A")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_day_active_power_peak(self):
        result = self.api_instance.get("day_active_power_peak")
        self.assertEqual(result.value, 2697)
        self.assertEqual(result.unit, "W")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_active_power(self):
        result = self.api_instance.get("active_power")
        self.assertEqual(result.value, 711)
        self.assertEqual(result.unit, "W")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_reactive_power(self):
        result = self.api_instance.get("reactive_power")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, "VA")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_power_factor(self):
        result = self.api_instance.get("power_factor")
        self.assertEqual(result.value, 1.0)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_grid_frequency(self):
        result = self.api_instance.get("grid_frequency")
        self.assertEqual(result.value, 49.99)
        self.assertEqual(result.unit, "Hz")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_efficiency(self):
        result = self.api_instance.get("efficiency")
        self.assertEqual(result.value, 97.57)
        self.assertEqual(result.unit, "%")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_internal_temperature(self):
        result = self.api_instance.get("internal_temperature")
        self.assertEqual(result.value, 26.9)
        self.assertEqual(result.unit, "°C")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_insulation_resistance(self):
        result = self.api_instance.get("insulation_resistance")
        self.assertEqual(result.value, 6.32)
        self.assertEqual(result.unit, "MOhm")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_device_status(self):
        result = self.api_instance.get("device_status")
        self.assertEqual(result.value, "On-grid")
        self.assertEqual(result.unit, "status_enum")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_fault_code(self):
        result = self.api_instance.get("fault_code")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_startup_time(self):
        result = self.api_instance.get("startup_time")
        tmp = datetime(2020, 2, 17, 7, 9, 19)
        expected_result = pytz.utc.localize(tmp)
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, "epoch")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_shutdown_time(self):
        result = self.api_instance.get("shutdown_time")
        tmp = datetime(2020, 2, 16, 16, 31, 9)
        expected_result = pytz.utc.localize(tmp)
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, "epoch")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_accumulated_yield_energy(self):
        result = self.api_instance.get("accumulated_yield_energy")
        self.assertEqual(result.value, 42.51)
        self.assertEqual(result.unit, "kWh")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_daily_yield_energy(self):
        result = self.api_instance.get("daily_yield_energy")
        self.assertEqual(result.value, 5.27)
        self.assertEqual(result.unit, "kWh")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_nb_optimizers(self):
        result = self.api_instance.get("nb_optimizers")
        self.assertEqual(result.value, 7)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_nb_online_optimizers(self):
        result = self.api_instance.get("nb_online_optimizers")
        self.assertEqual(result.value, 7)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_system_time(self):
        result = self.api_instance.get("system_time")
        tmp = datetime(2020, 2, 17, 13, 45, 37)
        expected_result = pytz.utc.localize(tmp)
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, "epoch")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_grid_code(self):
        result = self.api_instance.get("grid_code")
        expected_result = huawei_solar.GridCode(standard="C10/11", country="Belgium")
        self.assertEqual(result.value, expected_result)
        self.assertEqual(result.unit, "grid_enum")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_time_zone(self):
        result = self.api_instance.get("time_zone")
        self.assertEqual(result.value, 60)
        self.assertEqual(result.unit, "min")
