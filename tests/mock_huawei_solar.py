import time

from src.huawei_solar import HuaweiSolar


class MockResponse:
    def __init__(self, register, length):
        self._register = register
        self._length = length

    def isError(self):
        return not (self._register, self._length) in MOCK_REGISTERS.keys()

    def encode(self):
        return MOCK_REGISTERS[(self._register, self._length)]


def mock_read_holding_registers(self, register, length):
    return MockResponse(register, length)


MOCK_REGISTERS = {
    (
        30000,
        15,
    ): b"\x1eSUN2000L-3KTL\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
    (30015, 10): b"\x140000000000HVK0000000",
    (30070, 1): b"\x02\x010",
    (30071, 1): b"\x02\x00\x02",
    (30072, 1): b"\x02\x00\x02",
    (30073, 2): b"\x04\x00\x00\x0b\xb8",
    (30075, 2): b"\x04\x00\x00\x0c\xe4",
    (30077, 2): b"\x04\x00\x00\x0c\xe4",
    (30079, 2): b"\x04\x00\x00\x07\xbc",
    (30081, 2): b"\x04\xff\xff\xf8D",
    (32000, 1): b"\x02\x00\x06",
    (32002, 1): b"\x02\x00\x07",
    (32003, 2): b"\x04\x00\x00\x00\x00",
    (32008, 1): b"\x02\x01\x01",
    (32009, 1): b"\x02\x02\x02",
    (32010, 1): b"\x02\x01\x04",
    (32016, 1): b"\x02\x07\x80",
    (32017, 1): b"\x02\x00\xb2",
    (32018, 1): b"\x02\x04\xe6",
    (32019, 1): b"\x02\x00\xe0",
    (32020, 1): b"\x02\x00\x00",
    (32021, 1): b"\x02\x00\x00",
    (32022, 1): b"\x02\x00\x00",
    (32023, 1): b"\x02\x00\x00",
    (32024, 1): None,
    (32025, 1): None,
    (32026, 1): None,
    (32027, 1): None,
    (32028, 1): None,
    (32029, 1): None,
    (32030, 1): None,
    (32031, 1): None,
    (32032, 1): None,
    (32033, 1): None,
    (32034, 1): None,
    (32035, 1): None,
    (32036, 1): None,
    (32037, 1): None,
    (32038, 1): None,
    (32039, 1): None,
    (32040, 1): None,
    (32041, 1): None,
    (32042, 1): None,
    (32043, 1): None,
    (32044, 1): None,
    (32045, 1): None,
    (32046, 1): None,
    (32047, 1): None,
    (32048, 1): None,
    (32049, 1): None,
    (32050, 1): None,
    (32051, 1): None,
    (32052, 1): None,
    (32053, 1): None,
    (32054, 1): None,
    (32055, 1): None,
    (32056, 1): None,
    (32057, 1): None,
    (32058, 1): None,
    (32059, 1): None,
    (32060, 1): None,
    (32061, 1): None,
    (32062, 1): None,
    (32063, 1): None,
    (32064, 2): b"\x04\x00\x00\x03\x90",
    (32066, 1): b"\x02\x08\xf9",
    (32067, 1): b"\x02\x00\x00",
    (32068, 1): b"\x02\x00\x00",
    (32069, 1): b"\x02\t.",
    (32070, 1): b"\x02\x07\xcd",
    (32071, 1): b"\x02\x00\x00",
    (32072, 2): b"\x04\x00\x00\n\xf3",
    (32074, 2): b"\x04\x00\x00\x00\x00",
    (32076, 2): b"\x04\x00\x00\x00\x00",
    (32078, 2): b"\x04\x00\x00\n\x89",
    (32080, 2): b"\x04\x00\x00\x02\xc7",
    (32082, 2): b"\x04\x00\x00\x00\x00",
    (32084, 1): b"\x02\x03\xe8",
    (32085, 1): b"\x02\x13\x87",
    (32086, 1): b"\x02&\x1d",
    (32087, 1): b"\x02\x01\r",
    (32088, 1): b"\x02\x02x",
    (32089, 1): b"\x02\x02\x00",
    (32090, 1): b"\x02\x00\x00",
    (32091, 2): b"\x04^JJ/",
    (32093, 2): b"\x04^I|]",
    (32106, 2): b"\x04\x00\x00\x10\x9b",
    (32114, 2): b"\x04\x00\x00\x02\x0f",
    (37200, 1): b"\x02\x00\x07",
    (37201, 1): b"\x02\x00\x07",
    (40000, 2): b"\x04^J\xa7\x11",
    (42000, 1): b"\x02\x00\x12",
}


def get_mock_registers(host):
    """
    Get the registers from a huawei device. Can be used to add more tests for new devices
    """

    api = HuaweiSolar(host)
    print("MOCK_REGISTERS = {")
    for key in MOCK_REGISTERS.keys():
        i = 1
        while True:
            if i == 5:
                break
            i = i + 1
            response = api.client.read_holding_registers(*key)
            if not response.isError():
                break
            time.sleep(0.1)
        if i == 5:
            result = None
        else:
            result = response.encode()
        print(key, ": ", result, ",")
        time.sleep(0.1)
    print("}")
