"""Definitions of register values returned by the Huawei inverter"""

from collections import namedtuple
from enum import IntEnum

GridCode = namedtuple("GridCode", "standard country")
Alarm = namedtuple("Alarm", "name id level")
OnOffBit = namedtuple("OnOffBit", "off_value on_value")

DEVICE_STATUS_DEFINITIONS = {
    0x0000: "Standby: initializing",
    0x0001: "Standby: detecting insulation resistance",
    0x0002: "Standby: detecting irradiation",
    0x0003: "Standby: grid detecting",
    0x0100: "Starting",
    0x0200: "On-grid",
    0x0201: "Grid Connection: power limited",
    0x0202: "Grid Connection: self-derating",
    0x0300: "Shutdown: fault",
    0x0301: "Shutdown: command",
    0x0302: "Shutdown: OVGR",
    0x0303: "Shutdown: communication disconnected",
    0x0304: "Shutdown: power limited",
    0x0305: "Shutdown: manual startup required",
    0x0306: "Shutdown: DC switches disconnected",
    0x0307: "Shutdown: rapid cutoff",
    0x0308: "Shutdown: input underpowered",
    0x0401: "Grid scheduling: cosphi-P curve",
    0x0402: "Grid scheduling: Q-U curve",
    0x0403: "Grid scheduling: PF-U curve",
    0x0404: "Grid scheduling: dry contact",
    0x0405: "Grid scheduling: Q-P curve",
    0x0500: "Spot-check ready",
    0x0501: "Spot-checking",
    0x0600: "Inspecting",
    0x0700: "AFCI self check",
    0x0800: "I-V scanning",
    0x0900: "DC input detection",
    0x0A00: "Running: off-grid charging",
    0xA000: "Standby: no irradiation",
}


class StorageStatus(IntEnum):
    """Status of the attached energy storage."""

    OFFLINE = 0
    STANDBY = 1
    RUNNING = 2
    FAULT = 3
    SLEEP_MODE = 4

    def __str__(self) -> str:
        return self.name.replace("_", " ").capitalize()


class StorageWorkingModesA(IntEnum):
    """Working mode of the Connected Energy Storage."""

    UNLIMITED = 0
    GRID_CONNECTION_WITH_ZERO_POWER = 1
    GRID_CONNECTION_WITH_LIMITED_POWER = 2


class StorageWorkingModesB(IntEnum):
    """Working mode of the Connected Energy Storage."""

    NONE = 0
    FORCIBLE_CHARGE_DISCHARGE = 1
    TIME_OF_USE_LG = 2
    FIXED_CHARGE_DISCHARGE = 3
    MAXIMISE_SELF_CONSUMPTION = 4
    FULLY_FED_TO_GRID = 5
    TIME_OF_USE_LUNA2000 = 6
    REMOTE_SCHEDULING_MAXIMUM_SELF_USE = 7
    REMOTE_SCHEDULING_FULL_INTERNET_ACCESS = 8
    REMOTE_SCHEDULING_TOU = 9
    AI_ENERGY_MANAGEMENT_AND_SCHEDULING = 10


class StorageWorkingModesC(IntEnum):
    """Working mode of the Connected Energy Storage."""

    ADAPTIVE = 0
    FIXED_CHARGE_DISCHARGE = 1
    MAXIMISE_SELF_CONSUMPTION = 2
    TIME_OF_USE_LG = 3
    FULLY_FED_TO_GRID = 4
    TIME_OF_USE_LUNA2000 = 5


class StorageProductModel(IntEnum):
    """Storage Product Model."""

    NONE = 0
    LG_RESU = 1
    HUAWEI_LUNA2000 = 2


class StorageForcibleChargeDischarge(IntEnum):
    """Storage Product Model."""

    STOP = 0
    CHARGE = 1
    DISCHARGE = 2


class StorageExcessPvEnergyUseInTOU(IntEnum):
    """Storage Excess PV Energy use in Time-of-Use."""

    FED_TO_GRID = 0
    CHARGE = 1


class ActivePowerControlMode(IntEnum):
    """Active Power Control Mode."""

    UNLIMITED = 0  # default mode
    DI_ACTIVE_SCHEDULING = 1
    ZERO_POWER_GRID_CONNECTION = 5
    POWER_LIMITED_GRID_CONNECTION_WATT = 6
    POWER_LIMITED_GRID_CONNECTION_PERCENT = 7


class MeterStatus(IntEnum):
    """Power meter status."""

    OFFLINE = 0
    NORMAL = 1


class MeterType(IntEnum):
    """Power meter type."""

    SINGLE_PHASE = 0
    THREE_PHASE = 1


class MeterTypeCheck(IntEnum):
    """Power meter type check."""

    RECOGNIZING = 0
    MATCHES_WITH_METER = 1
    MATCHES_NOT_WITH_METER = 2


class BackupVoltageIndependentOperation(IntEnum):
    """Backup voltage independent operation."""

    BV_101V = 0
    BV_202V = 1


# pylint: disable=fixme
GRID_CODES = {
    0: GridCode("VDE-AR-N-4105", "Germany"),
    1: GridCode("NB/T 32004", "China"),
    2: GridCode("UTE C 15-712-1(A)", "France"),
    3: GridCode("UTE C 15-712-1(B)", "France"),
    4: GridCode("UTE C 15-712-1(C)", "France"),
    5: GridCode("VDE 0126-1-1-BU", "Bulgary"),
    6: GridCode("VDE 0126-1-1-GR(A)", "Greece"),
    7: GridCode("VDE 0126-1-1-GR(B)", "Greece"),
    8: GridCode("BDEW-MV", "Germany"),
    9: GridCode("G59-England", "UK"),
    10: GridCode("G59-Scotland", "UK"),
    11: GridCode("G83-England", "UK"),
    12: GridCode("G83-Scotland", "UK"),
    13: GridCode("CEI0-21", "Italy"),
    14: GridCode("EN50438-CZ", "Czech Republic"),
    15: GridCode("RD1699/661", "Spain"),
    16: GridCode("RD1699/661-MV480", "Spain"),
    17: GridCode("EN50438-NL", "Netherlands"),
    18: GridCode("C10/11", "Belgium"),
    19: GridCode("AS4777", "Australia"),
    20: GridCode("IEC61727", "General"),
    21: GridCode("Custom (50 Hz)", "Custom"),
    22: GridCode("Custom (60 Hz)", "Custom"),
    23: GridCode("CEI0-16", "Italy"),
    24: GridCode("CHINA-MV480", "China"),
    25: GridCode("CHINA-MV", "China"),
    26: GridCode("TAI-PEA", "Thailand"),
    27: GridCode("TAI-MEA", "Thailand"),
    28: GridCode("BDEW-MV480", "Germany"),
    29: GridCode("Custom MV480 (50 Hz)", "Custom"),
    30: GridCode("Custom MV480 (60 Hz)", "Custom"),
    31: GridCode("G59-England-MV480", "UK"),
    32: GridCode("IEC61727-MV480", "General"),
    33: GridCode("UTE C 15-712-1-MV480", "France"),
    34: GridCode("TAI-PEA-MV480", "Thailand"),
    35: GridCode("TAI-MEA-MV480", "Thailand"),
    36: GridCode("EN50438-DK-MV480", "Denmark"),
    37: GridCode("Japan standard (50 Hz)", "Japan"),
    38: GridCode("Japan standard (60 Hz)", "Japan"),
    39: GridCode("EN50438-TR-MV480", "Turkey"),
    40: GridCode("EN50438-TR", "Turkey"),
    41: GridCode("C11/C10-MV480", "Belgium"),
    42: GridCode("Philippines", "Philippines"),
    43: GridCode("Philippines-MV480", "Philippines"),
    44: GridCode("AS4777-MV480", "Australia"),
    45: GridCode("NRS-097-2-1", "South Africa"),
    46: GridCode("NRS-097-2-1-MV480", "South Africa"),
    47: GridCode("KOREA", "South Korea"),
    48: GridCode("IEEE 1547-MV480", "USA"),
    49: GridCode("IEC61727-60Hz", "General"),
    50: GridCode("IEC61727-60Hz-MV480", "General"),
    51: GridCode("CHINA_MV500", "China"),
    52: GridCode("ANRE", "Romania"),
    53: GridCode("ANRE-MV480", "Romania"),
    54: GridCode("ELECTRIC RULE NO.21-MV480", "California, USA"),
    55: GridCode("HECO-MV480", "Hawaii, USA"),
    56: GridCode("PRC_024_Eastern-MV480", "Eastern USA"),
    57: GridCode("PRC_024_Western-MV480", "Western USA"),
    58: GridCode("PRC_024_Quebec-MV480", "Quebec, Canada"),
    59: GridCode("PRC_024_ERCOT-MV480", "Texas, USA"),
    60: GridCode("PO12.3-MV480", "Spain"),
    61: GridCode("EN50438_IE-MV480", "Ireland"),
    62: GridCode("EN50438_IE", "Ireland"),
    63: GridCode("IEEE 1547a-MV480", "USA"),
    64: GridCode("Japan standard (MV420-50 Hz)", "Japan"),
    65: GridCode("Japan standard (MV420-60 Hz)", "Japan"),
    66: GridCode("Japan standard (MV440-50 Hz)", "Japan"),
    67: GridCode("Japan standard (MV440-60 Hz)", "Japan"),
    68: GridCode("IEC61727-50Hz-MV500", "General"),
    70: GridCode("CEI0-16-MV480", "Italy"),
    71: GridCode("PO12.3", "Spain"),
    72: GridCode("Japan standard (MV400-50 Hz)", "Japan"),
    73: GridCode("Japan standard (MV400-60 Hz)", "Japan"),
    74: GridCode("CEI0-21-MV480", "Italy"),
    75: GridCode("KOREA-MV480", "South Korea"),
    76: GridCode("Egypt ETEC", "Egypt"),
    77: GridCode("Egypt ETEC-MV480", "Egypt"),
    78: GridCode("CHINA_MV800", "China"),
    79: GridCode("IEEE 1547-MV600", "USA"),
    80: GridCode("ELECTRIC RULE NO.21-MV600", "California, USA"),
    81: GridCode("HECO-MV600", "Hawaii, USA"),
    82: GridCode("PRC_024_Eastern-MV600", "Eastern USA"),
    83: GridCode("PRC_024_Western-MV600", "Western USA"),
    84: GridCode("PRC_024_Quebec-MV600", "Quebec, Canada"),
    85: GridCode("PRC_024_ERCOT-MV600", "Texas, USA"),
    86: GridCode("IEEE 1547a-MV600", "USA"),
    87: GridCode("EN50549-LV", "Ireland"),
    88: GridCode("EN50549-MV480", "Ireland"),
    89: GridCode("Jordan-Transmission", "Jordan"),
    90: GridCode("Jordan-Transmission-MV480", "Jordan"),
    91: GridCode("NAMIBIA", "Namibia"),
    92: GridCode("ABNT NBR 16149", "Brazil"),
    93: GridCode("ABNT NBR 16149-MV480", "Brazil"),
    94: GridCode("SA_RPPs", "South Africa"),
    95: GridCode("SA_RPPs-MV480", "South Africa"),
    96: GridCode("INDIA", "India"),
    97: GridCode("INDIA-MV500", "India"),
    98: GridCode("ZAMBIA", "Zambia"),
    99: GridCode("ZAMBIA-MV480", "Zambia"),
    100: GridCode("Chile", "Chile"),
    101: GridCode("Chile-MV480", "Chile"),
    102: GridCode("CHINA-MV500-STD", "China"),
    103: GridCode("CHINA-MV480-STD", "China"),
    104: GridCode("Mexico-MV480", "Mexico"),
    105: GridCode("Malaysian", "Malaysia"),
    106: GridCode("Malaysian-MV480", "Malaysia"),
    107: GridCode("KENYA_ETHIOPIA", "East Africa"),
    108: GridCode("KENYA_ETHIOPIA-MV480", "East Africa"),
    109: GridCode("G59-England-MV800", "UK"),
    110: GridCode("NEGERIA", "Negeria"),
    111: GridCode("NEGERIA-MV480", "Negeria"),
    112: GridCode("DUBAI", "Dubai"),
    113: GridCode("DUBAI-MV480", "Dubai"),
    114: GridCode("Northern Ireland", "Northern Ireland"),
    115: GridCode("Northern Ireland-MV480", "Northern Ireland"),
    116: GridCode("Cameroon", "Cameroon"),
    117: GridCode("Cameroon-MV480", "Cameroon"),
    118: GridCode("Jordan Distribution", "Jordan"),
    119: GridCode("Jordan Distribution-MV480", "Jordan"),
    120: GridCode("Custom MV600-50 Hz", "Custom"),
    121: GridCode("AS4777-MV800", "Australia"),
    122: GridCode("INDIA-MV800", "India"),
    123: GridCode("IEC61727-MV800", "General"),
    124: GridCode("BDEW-MV800", "Germany"),
    125: GridCode("ABNT NBR 16149-MV800", "Brazil"),
    126: GridCode("UTE C 15-712-1-MV800", "France"),
    127: GridCode("Chile-MV800", "Chile"),
    128: GridCode("Mexico-MV800", "Mexico"),
    129: GridCode("EN50438-TR-MV800", "Turkey"),
    130: GridCode("TAI-PEA-MV800", "Thailand"),
    133: GridCode("NRS-097-2-1-MV800", "South Africa"),
    134: GridCode("SA_RPPs-MV800", "South Africa"),
    135: GridCode("Jordan-Transmission-MV800", "Jordan"),
    136: GridCode("Jordan-Distribution-MV800", "Jordan"),
    137: GridCode("Egypt ETEC-MV800", "Egypt"),
    138: GridCode("DUBAI-MV800", "Dubai"),
    139: GridCode("SAUDI-MV800", "Saudi Arabia"),
    140: GridCode("EN50438_IE-MV800", "Ireland"),
    141: GridCode("EN50549-MV800", "Ireland"),
    142: GridCode("Northern Ireland-MV800", "Northern Ireland"),
    143: GridCode("CEI0-21-MV800", "Italy"),
    144: GridCode("IEC 61727-MV800-60Hz", "General"),
    145: GridCode("NAMIBIA_MV480", "Namibia"),
    146: GridCode("Japan (LV202-50 Hz)", "Japan"),
    147: GridCode("Japan (LV202-60 Hz)", "Japan"),
    148: GridCode("Pakistan-MV800", "Pakistan"),
    149: GridCode("BRASIL-ANEEL-MV800", "Brazil"),
    150: GridCode("Israel-MV800", "Israel"),
    151: GridCode("CEI0-16-MV800", "Italy"),
    152: GridCode("ZAMBIA-MV800", "Zambia"),
    153: GridCode("KENYA_ETHIOPIA-MV800", "East Africa"),
    154: GridCode("NAMIBIA_MV800", "Namibia"),
    155: GridCode("Cameroon-MV800", "Cameroon"),
    156: GridCode("NIGERIA-MV800", "Nigeria"),
    157: GridCode("ABUDHABI-MV800", "Abu Dhabi"),
    158: GridCode("LEBANON", "Lebanon"),
    159: GridCode("LEBANON-MV480", "Lebanon"),
    160: GridCode("LEBANON-MV800", "Lebanon"),
    161: GridCode("ARGENTINA-MV800", "Argentina"),
    162: GridCode("ARGENTINA-MV500", "Argentina"),
    163: GridCode("Jordan-Transmission-HV", "Jordan"),
    164: GridCode("Jordan-Transmission-HV480", "Jordan"),
    165: GridCode("Jordan-Transmission-HV800", "Jordan"),
    166: GridCode("TUNISIA", "Tunisia"),
    167: GridCode("TUNISIA-MV480", "Tunisia"),
    168: GridCode("TUNISIA-MV800", "Tunisia"),
    169: GridCode("JAMAICA-MV800", "Jamaica"),
    170: GridCode("AUSTRALIA-NER", "Australia"),
    171: GridCode("AUSTRALIA-NER-MV480", "Australia"),
    172: GridCode("AUSTRALIA-NER-MV800", "Australia"),
    173: GridCode("SAUDI", "Saudi Arabia"),
    174: GridCode("SAUDI-MV480", "Saudi Arabia"),
    175: GridCode("Ghana-MV480", "Ghana"),
    176: GridCode("Israel", "Israel"),
    177: GridCode("Israel-MV480", "Israel"),
    178: GridCode("Chile-PMGD", "Chile"),
    179: GridCode("Chile-PMGD-MV480", "Chile"),
    180: GridCode("VDE-AR-N4120-HV", "Germany"),
    181: GridCode("VDE-AR-N4120-HV480", "Germany"),
    182: GridCode("VDE-AR-N4120-HV800", "Germany"),
    183: GridCode("IEEE 1547-MV800", "USA"),
    184: GridCode("Nicaragua-MV800", "Nicaragua"),
    185: GridCode("IEEE 1547a-MV800", "USA"),
    186: GridCode("ELECTRIC RULE NO.21-MV800", "California, USA"),
    187: GridCode("HECO-MV800", "Hawaii, USA"),
    188: GridCode("PRC_024_Eastern-MV800", "Eastern USA"),
    189: GridCode("PRC_024_Western-MV800", "Western USA"),
    190: GridCode("PRC_024_Quebec-MV800", "Quebec, Canada"),
    191: GridCode("PRC_024_ERCOT-MV800", "Texas, USA"),
    192: GridCode("Custom-MV800-50Hz", "Custom"),
    193: GridCode("RD1699/661-MV800", "Spain"),
    194: GridCode("PO12.3-MV800", "Spain"),
    195: GridCode("Mexico-MV600", "Mexico"),
    196: GridCode("Vietnam-MV800", "Vietnam"),
    197: GridCode("CHINA-LV220/380", "China"),
    198: GridCode("SVG-LV", "Dedicated"),
    199: GridCode("Vietnam", "Vietnam"),
    200: GridCode("Vietnam-MV480", "Vietnam"),
    201: GridCode("Chile-PMGD-MV800", "Chile"),
    202: GridCode("Ghana-MV800", "Ghana"),
    203: GridCode("TAIPOWER", "Taiwan"),
    204: GridCode("TAIPOWER-MV480", "Taiwan"),
    205: GridCode("TAIPOWER-MV800", "Taiwan"),
    206: GridCode("IEEE 1547-LV208", "USA"),
    207: GridCode("IEEE 1547-LV240", "USA"),
    208: GridCode("IEEE 1547a-LV208", "USA"),
    209: GridCode("IEEE 1547a-LV240", "USA"),
    210: GridCode("ELECTRIC RULE NO.21-LV208", "USA"),
    211: GridCode("ELECTRIC RULE NO.21-LV240", "USA"),
    212: GridCode("HECO-O+M+H-LV208", "USA"),
    213: GridCode("HECO-O+M+H-LV240", "USA"),
    214: GridCode("PRC_024_Eastern-LV208", "USA"),
    215: GridCode("PRC_024_Eastern-LV240", "USA"),
    216: GridCode("PRC_024_Western-LV208", "USA"),
    217: GridCode("PRC_024_Western-LV240", "USA"),
    218: GridCode("PRC_024_ERCOT-LV208", "USA"),
    219: GridCode("PRC_024_ERCOT-LV240", "USA"),
    220: GridCode("PRC_024_Quebec-LV208", "USA"),
    221: GridCode("PRC_024_Quebec-LV240", "USA"),
    222: GridCode("ARGENTINA-MV480", "Argentina"),
    223: GridCode("Oman", "Oman"),
    224: GridCode("Oman-MV480", "Oman"),
    225: GridCode("Oman-MV800", "Oman"),
    226: GridCode("Kuwait", "Kuwait"),
    227: GridCode("Kuwait-MV480", "Kuwait"),
    228: GridCode("Kuwait-MV800", "Kuwait"),
    229: GridCode("Bangladesh", "Bangladesh"),
    230: GridCode("Bangladesh-MV480", "Bangladesh"),
    231: GridCode("Bangladesh-MV800", "Bangladesh"),
    232: GridCode("Chile-Net_Billing", "Chile"),
    233: GridCode("EN50438-NL-MV480", "Netherlands"),
    234: GridCode("Bahrain", "Bahrain"),
    235: GridCode("Bahrain-MV480", "Bahrain"),
    236: GridCode("Bahrain-MV800", "Bahrain"),
    238: GridCode("Japan-MV550-50Hz", "Japan"),
    239: GridCode("Japan-MV550-60Hz", "Japan"),
    241: GridCode("ARGENTINA", "Argentina"),
    242: GridCode("KAZAKHSTAN-MV800", "Kazakhstan"),
    243: GridCode("Mauritius", "Mauritius"),
    244: GridCode("Mauritius-MV480", "Mauritius"),
    245: GridCode("Mauritius-MV800", "Mauritius"),
    246: GridCode("Oman-PDO-MV800", "Oman"),
    247: GridCode("EN50438-SE", "Sweden"),
    248: GridCode("TAI-MEA-MV800", "Thailand"),
    249: GridCode("Pakistan", "Pakistan"),
    250: GridCode("Pakistan-MV480", "Pakistan"),
    251: GridCode("PORTUGAL-MV800", "Portugal"),
    252: GridCode("HECO-L+M-LV208", "USA"),
    253: GridCode("HECO-L+M-LV240", "USA"),
    254: GridCode("C10/11-MV800", "Belgium"),
    255: GridCode("Austria", "Austria"),
    256: GridCode("Austria-MV480", "Austria"),
    257: GridCode("G98", "UK"),
    258: GridCode("G99-TYPEA-LV", "UK"),
    259: GridCode("G99-TYPEB-LV", "UK"),
    260: GridCode("G99-TYPEB-HV", "UK"),
    261: GridCode("G99-TYPEB-HV-MV480", "UK"),
    262: GridCode("G99-TYPEB-HV-MV800", "UK"),
    263: GridCode("G99-TYPEC-HV-MV800", "UK"),
    264: GridCode("G99-TYPED-MV800", "UK"),
    265: GridCode("G99-TYPEA-HV", "UK"),
    266: GridCode("CEA-MV800", "India"),
    267: GridCode("EN50549-MV400", "Europe"),
    268: GridCode("VDE-AR-N4110", "Germany"),
    269: GridCode("VDE-AR-N4110-MV480", "Germany"),
    270: GridCode("VDE-AR-N4110-MV800", "Germany"),
    271: GridCode("Panama-MV800", "Panama"),
    272: GridCode("North Macedonia-MV800", "North Macedonia"),
    273: GridCode("NTS", "Spain"),
    274: GridCode("NTS-MV480", "Spain"),
    275: GridCode("NTS-MV800", "Spain"),
}

STATE_CODES_1 = {
    0b0000_0000_0000_0001: "Standby",
    0b0000_0000_0000_0010: "Grid-Connected",
    0b0000_0000_0000_0100: "Grid-Connected normally",
    0b0000_0000_0000_1000: "Grid connection with derating due to power rationing",
    0b0000_0000_0001_0000: "Grid connection with derating due to internalcauses of the solar inverter",
    0b0000_0000_0010_0000: "Normal stop",
    0b0000_0000_0100_0000: "Stop due to faults",
    0b0000_0000_1000_0000: "Stop due to power rationing",
    0b0000_0001_0000_0000: "Shutdown",
    0b0000_0010_0000_0000: "Spot check",
}

STATE_CODES_2 = {
    0b0000_0000_0000_0001: OnOffBit("Locked", "Unlocked"),
    0b0000_0000_0000_0010: OnOffBit("PV disconnected", "PV connected"),
    0b0000_0000_0000_0100: OnOffBit("No DSP data collection", "DSP data collection"),
}

STATE_CODES_3 = {
    0b0000_0000_0000_0000_0000_0000_0000_0001: OnOffBit("On-grid", "Off-grid"),
    0b0000_0000_0000_0000_0000_0000_0000_0010: OnOffBit(
        "Off-grid switch disabled",
        "Off-grid switch enabled",
    ),
}

ALARM_CODES_1 = {
    0b0000_0000_0000_0001: Alarm("High String Input Voltage", 2001, "Major"),
    0b0000_0000_0000_0010: Alarm("DC Arc Fault", 2002, "Major"),
    0b0000_0000_0000_0100: Alarm("String Reverse Connection", 2011, "Major"),
    0b0000_0000_0000_1000: Alarm("String Current Backfeed", 2012, "Warning"),
    0b0000_0000_0001_0000: Alarm("Abnormal String Power", 2013, "Warning"),
    0b0000_0000_0010_0000: Alarm("AFCI Self-Check Fail", 2021, "Major"),
    0b0000_0000_0100_0000: Alarm("Phase Wire Short-Circuited to PE", 2031, "Major"),
    0b0000_0000_1000_0000: Alarm("Grid Loss", 2032, "Major"),
    0b0000_0001_0000_0000: Alarm("Grid Undervoltage", 2033, "Major"),
    0b0000_0010_0000_0000: Alarm("Grid Overvoltage", 2034, "Major"),
    0b0000_0100_0000_0000: Alarm("Grid Volt. Imbalance", 2035, "Major"),
    0b0000_1000_0000_0000: Alarm("Grid Overfrequency", 2036, "Major"),
    0b0001_0000_0000_0000: Alarm("Grid Underfrequency", 2037, "Major"),
    0b0010_0000_0000_0000: Alarm("Unstable Grid Frequency", 2038, "Major"),
    0b0100_0000_0000_0000: Alarm("Output Overcurrent", 2039, "Major"),
    0b1000_0000_0000_0000: Alarm("Output DC Component Overhigh", 2040, "Major"),
}

ALARM_CODES_2 = {
    0b0000_0000_0000_0001: Alarm("Abnormal Residual Current", 2051, "Major"),
    0b0000_0000_0000_0010: Alarm("Abnormal Grounding", 2061, "Major"),
    0b0000_0000_0000_0100: Alarm("Low Insulation Resistance", 2062, "Major"),
    0b0000_0000_0000_1000: Alarm("Overtemperature", 2063, "Minor"),
    0b0000_0000_0001_0000: Alarm("Device Fault", 2064, "Major"),
    0b0000_0000_0010_0000: Alarm("Upgrade Failed or Version Mismatch", 2065, "Minor"),
    0b0000_0000_0100_0000: Alarm("License Expired", 2066, "Warning"),
    0b0000_0000_1000_0000: Alarm("Faulty Monitoring Unit", 61440, "Minor"),
    0b0000_0001_0000_0000: Alarm("Faulty Power Collector", 2067, "Major"),
    0b0000_0010_0000_0000: Alarm("Battery abnormal", 2068, "Minor"),
    0b0000_0100_0000_0000: Alarm("Active Islanding", 2070, "Major"),
    0b0000_1000_0000_0000: Alarm("Passive Islanding", 2071, "Major"),
    0b0001_0000_0000_0000: Alarm("Transient AC Overvoltage", 2072, "Major"),
    0b0010_0000_0000_0000: Alarm("Peripheral port short circuit", 2075, "Warning"),
    0b0100_0000_0000_0000: Alarm("Churn output overload", 2077, "Major"),
    0b1000_0000_0000_0000: Alarm("Abnormal PV module configuration", 2080, "Major"),
}

ALARM_CODES_3 = {
    0b0000_0000_0000_0001: Alarm("Optimizer fault", 2081, "Warning"),
    0b0000_0000_0000_0010: Alarm("Built-in PID operation abnormal", 2085, "Minor"),
    0b0000_0000_0000_0100: Alarm("High input string voltage to ground", 2014, "Major"),
    0b0000_0000_0000_1000: Alarm("External Fan Abnormal", 2086, "Major"),
    0b0000_0000_0001_0000: Alarm("Battery Reverse Connection", 2069, "Major"),
    0b0000_0000_0010_0000: Alarm("On-grid/Off-grid controller abnormal", 2082, "Major"),
    0b0000_0000_0100_0000: Alarm("PV String Loss", 2015, "Warning"),
    0b0000_0000_1000_0000: Alarm("Internal Fan Abnormal", 2087, "Major"),
    0b0000_0001_0000_0000: Alarm("DC Protection Unit Abnormal", 2088, "Major"),
}


class StorageCapacityControlMode(IntEnum):
    """Storage Capacity Control Mode"""

    DISABLE = 0
    ACTIVE_CAPACITY_CONTROL = 1
