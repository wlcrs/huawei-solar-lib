import unittest
from unittest.mock import patch

import src.huawei_solar.huawei_solar as huawei_solar
from tests import mock_huawei_solar


class TestHuaweiSolar(unittest.TestCase):
    def setUp(self):
        self.api_instance = huawei_solar.HuaweiSolar("192.168.1.23")

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
        self.assertEqual(result.value,304)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_nb_pv_strings(self):
        result = self.api_instance.get("nb_pv_strings")
        self.assertEqual(result.value,2)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_nb_mpp_tracks(self):
        result = self.api_instance.get("nb_mpp_tracks")
        self.assertEqual(result.value,2)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_rated_power(self):
        result = self.api_instance.get("rated_power")
        self.assertEqual(result.value, 3000)
        self.assertEqual(result.unit, 'W')

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_P_max(self):
        result = self.api_instance.get("P_max")
        self.assertEqual(result.value,3300)
        self.assertEqual(result.unit, 'W')

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_S_max(self):
        result = self.api_instance.get("S_max")
        self.assertEqual(result.value,3300)
        self.assertEqual(result.unit, 'VA')

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_Q_max_out(self):
        result = self.api_instance.get("Q_max_out")
        self.assertEqual(result.value,1980)
        self.assertEqual(result.unit, "VAr")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_Q_max_in(self):
        result = self.api_instance.get("Q_max_in")
        self.assertEqual(result.value,-1980)
        self.assertEqual(result.unit, "VAr")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_state_1(self):
        result = self.api_instance.get("state_1")
        self.assertEqual(result.value,['grid-connected', 'grid-connected normally'])
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_state_2(self):
        result = self.api_instance.get("state_2")
        self.assertEqual(result.value,['unlocked', 'PV connected', 'DSP data collection'])
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_state_3(self):
        result = self.api_instance.get("state_3")
        self.assertEqual(result.value,['on-grid', 'off-grid switch disabled'])
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_alarm_1_some(self):
        result = self.api_instance.get("alarm_1")
        expected_result = [huawei_solar.ALARM_CODES_1[1], huawei_solar.ALARM_CODES_1[256]]
        self.assertEqual(result.value,expected_result)
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
        self.assertEqual(result.value,expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_alarm_2_some(self):
        result = self.api_instance.get("alarm_2")
        expected_result = [huawei_solar.ALARM_CODES_2[2], huawei_solar.ALARM_CODES_2[512]]
        self.assertEqual(result.value,expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32009, 1): b"\x02\x00\x00"})
    def test_get_alarm_2_none(self):
        result = self.api_instance.get("alarm_2")
        expected_result = []
        self.assertEqual(result.value,expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32009, 1): b"\x02\xff\xff"})
    def test_get_alarm_2_all(self):
        result = self.api_instance.get("alarm_2")
        expected_result = list(huawei_solar.ALARM_CODES_2.values())
        self.assertEqual(result.value,expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_alarm_3_some(self):
        result = self.api_instance.get("alarm_3")
        expected_result = [huawei_solar.ALARM_CODES_3[4], huawei_solar.ALARM_CODES_3[256]]
        self.assertEqual(result.value,expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32010, 1): b"\x02\x00\x00"})
    def test_get_alarm_3_none(self):
        result = self.api_instance.get("alarm_3")
        expected_result = []
        self.assertEqual(result.value,expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    @patch.dict(mock_huawei_solar.MOCK_REGISTERS, {(32010, 1): b"\x02\x01\xff"})
    def test_get_alarm_2_all(self):
        result = self.api_instance.get("alarm_3")
        expected_result = list(huawei_solar.ALARM_CODES_3.values())
        self.assertEqual(result.value,expected_result)
        self.assertEqual(result.unit, None)

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_01_voltage(self):
        result = self.api_instance.get("pv_01_voltage")
        self.assertEqual(result.value,192)
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
        self.assertEqual(result.value,125.4)
        self.assertEqual(result.unit, "V")

    @patch(
        "pymodbus.client.sync.ModbusTcpClient.read_holding_registers",
        mock_huawei_solar.mock_read_holding_registers,
    )
    def test_get_pv_02_current(self):
        result = self.api_instance.get("pv_02_current")
        self.assertEqual(result.value, 2.24)
        self.assertEqual(result.unit, "A")
