"""Names and severities of the alarms reported in the active and history alarm files (0xA1 / 0xA2).

The register-based alarm bitfields (32008-32010) only cover the SUN2000 inverter, and `HUAWEI_ALARM_CODES` only
holds SUN2000 and SmartLogger alarm ids. The EMMA, the SmartGuard and the SCharger report their alarms through the
alarm files only; their ids are listed here.

Source: the AlarmInfo catalogue of the FusionSolar app (families SmartHems, Backup and Charge) with its English
names. Only the short alarm names are included, not the causes or the repair suggestions. Levels use the same
scale as the app and as `AlarmLevel`: Critical, Major, Minor, Warning. Within these families the name and the
level of an alarm do not depend on its reason id, and no id appears in two families.
"""

from huawei_solar.register_values import Alarm

EMMA_ALARM_CODES: dict[int, Alarm] = {
    2112: Alarm("Phase Sequence Abnormal", 2112, "Major"),
    4000: Alarm("Inverter Communication Error", 4000, "Major"),
    4001: Alarm("App Communication Certificate Expired", 4001, "Minor"),
    4002: Alarm("Management System Certificate Expired", 4002, "Minor"),
    4003: Alarm("The auxiliary power supply is faulty", 4003, "Critical"),
    4004: Alarm("Abnormal DI Instruction", 4004, "Major"),
    4006: Alarm("Charger Communication Error", 4006, "Major"),
    4008: Alarm("BackupBox Communication Error", 4008, "Major"),
    4009: Alarm("Management System Certificate Invalid", 4009, "Minor"),
    4010: Alarm("Management System Certificate About to Expire", 4010, "Warning"),
    4011: Alarm("App Communication Certificate Invalid", 4011, "Minor"),
    4012: Alarm("App Communication Certificate Will Expire", 4012, "Warning"),
    4013: Alarm("BackupBox Overload", 4013, "Major"),
    4014: Alarm("On-/Off-Grid Switching Signal Abnormal", 4014, "Major"),
    4015: Alarm("Smart Switch Communication Error", 4015, "Major"),
    4016: Alarm("Phase Sequence Abnormal", 4016, "Major"),
    4017: Alarm("Generator Control Failure", 4017, "Warning"),
    4018: Alarm("Generator Output Abnormal", 4018, "Major"),
    4019: Alarm("Generator Faulty", 4019, "Major"),
    4020: Alarm("Abnormal Power at Grid Connection Point", 4020, "Major"),
    4021: Alarm("CT connection abnormal", 4021, "Major"),
    4022: Alarm("Meter Communication Error", 4022, "Minor"),
    4023: Alarm("AC Cable Connection Abnormal", 4023, "Major"),
    4024: Alarm("Software version mismatch", 4024, "Major"),
    4025: Alarm("Heat Pump Communication Error", 4025, "Major"),
    4026: Alarm("Heating Rod Communication Error", 4026, "Major"),
    4027: Alarm("SmartAssistant Southbound Network Communication Certificate Expired", 4027, "Minor"),
    4028: Alarm("SmartAssistant Southbound Network Communication Certificate Invalid", 4028, "Minor"),
    4029: Alarm("SmartAssistant Southbound Communication Certificate About to Expire", 4029, "Warning"),
    4030: Alarm("Management System-1 Communication Certificate Expired", 4030, "Minor"),
    4031: Alarm("Management System-1 Communication Certificate Invalid", 4031, "Minor"),
    4032: Alarm("Management System-1 Communication Certificate About to Expire", 4032, "Warning"),
    4033: Alarm("Incorrect Power Configuration of Third-Party Inverter", 4033, "Warning"),
}

SMARTGUARD_ALARM_CODES: dict[int, Alarm] = {
    4200: Alarm("Internal fan abnormal", 4200, "Major"),
    4201: Alarm("Incorrect Wiring", 4201, "Major"),
    4202: Alarm("On-/Off-Grid Switching Signal Abnormal", 4202, "Major"),
    4203: Alarm("Incorrect Connection of Live and Neutral Wires", 4203, "Warning"),
    4204: Alarm("Device fault", 4204, "Major"),
    4205: Alarm("Upgrade Failed or Version Mismatch", 4205, "Minor"),
    4206: Alarm("Overtemperature", 4206, "Minor"),
    4207: Alarm("Abnormal Grounding", 4207, "Warning"),
    4208: Alarm("Grid Overvoltage", 4208, "Major"),
    4209: Alarm("Bypass Switch Turned On", 4209, "Major"),
    4210: Alarm("Short Circuit of Backed-Up Appliance", 4210, "Major"),
    4211: Alarm("Overload", 4211, "Major"),
    4212: Alarm("Communication Failure", 4212, "Major"),
}

SCHARGER_ALARM_CODES: dict[int, Alarm] = {
    62900: Alarm("Input Overvoltage", 62900, "Minor"),
    62901: Alarm("Input Undervoltage", 62901, "Minor"),
    62902: Alarm("Input Phase Failure", 62902, "Minor"),
    62903: Alarm("EPO Activated", 62903, "Critical"),
    62904: Alarm("High Temperature", 62904, "Minor"),
    62905: Alarm("The temperature sensor is faulty", 62905, "Major"),
    62906: Alarm("Leakage Detection Circuit Fault", 62906, "Critical"),
    62907: Alarm("The temperature sensor is faulty", 62907, "Major"),
    62908: Alarm("Control Pilot Circuit Fault", 62908, "Minor"),
    62909: Alarm("High Temperature", 62909, "Minor"),
    62910: Alarm("Overcurrent", 62910, "Minor"),
    62911: Alarm("Electric Leakage", 62911, "Critical"),
    62912: Alarm("Contactor Fault", 62912, "Major"),
    62998: Alarm("Management System Certificate Expired", 62998, "Major"),
    62999: Alarm("Management System Will Expire", 62999, "Major"),
    63019: Alarm("Cable Connection Abnormal", 63019, "Critical"),
    63020: Alarm("Charging Connector Removed Abnormally", 63020, "Minor"),
    63286: Alarm("Charging Connector Lock Faulty", 63286, "Major"),
    63354: Alarm("Charging Cable Abnormal", 63354, "Major"),
    63394: Alarm("EV Charging Abnormal", 63394, "Warning"),
    63414: Alarm("Failed to Communicate with SmartAssistant", 63414, "Major"),
    63415: Alarm("SmartAssistant Communication Certificate Expired", 63415, "Major"),
    63416: Alarm("SmartAssistant Communication Certificate Will Expire", 63416, "Major"),
    63417: Alarm("Failed to Communicate with TCP-Modbus System", 63417, "Major"),
    63418: Alarm("TCP-Modbus Communication Certificate Expired", 63418, "Major"),
    63419: Alarm("TCP-Modbus Communication Certificate Will Expire", 63419, "Major"),
    63420: Alarm("App Communication Certificate Expired", 63420, "Major"),
    63421: Alarm("App Communication Certificate Will Expire", 63421, "Major"),
    63422: Alarm("Derated Charging Alarm due to High Temperature", 63422, "Minor"),
    63488: Alarm("Failed to Communicate with OCPP System", 63488, "Major"),
    63489: Alarm("Certificate for Communication with OCPP System Expired", 63489, "Major"),
    63490: Alarm("Certificate for Communication with OCPP System About to Expire", 63490, "Major"),
}

HUAWEI_FILE_ALARM_CODES: dict[int, Alarm] = {
    **EMMA_ALARM_CODES,
    **SMARTGUARD_ALARM_CODES,
    **SCHARGER_ALARM_CODES,
}
"""Alarm ids that only appear in the alarm files. Look these up before `HUAWEI_ALARM_CODES`."""

CATALOGUE_LEVEL_OVERRIDES: dict[int, str] = {
    2015: "Major",  # PV String Loss: "Warning" in HUAWEI_ALARM_CODES, Major for every reason in the catalogue
}
"""FusionSolar catalogue levels of alarms whose level in `HUAWEI_ALARM_CODES` differs; used by `effective_level`."""

MANUAL_CLEAR_ALARMS: dict[int, frozenset[int] | None] = {
    # SUN2000 / LUNA2000 (the app's default catalogue family)
    2002: None,  # DC arc fault
    2003: None,  # DC arc fault
    2009: None,  # String short-circuited to ground
    2021: frozenset({1}),  # AFCI self-check failure: only reason 1
    2075: None,  # Peripheral port short circuit
    2077: None,  # Output overload
    2104: None,  # DC terminal temperature abnormal
    2136: None,  # Device rusty and requiring maintenance
    3832: None,  # Fire alarm
    3874: None,  # Fire suppression system abnormal
    # EMMA
    4014: None,  # On-/Off-grid switching signal abnormal
}
"""Alarms that stay active until they are cleared manually ("ADMC" in the FusionSolar catalogue).

Maps the alarm id to the reason ids concerned, or to None when every reason needs a manual clear. Covers the
SUN2000/LUNA2000 family and the EMMA, SmartGuard and SCharger families; the last two have no such alarm.
"""


def is_manual_clear_alarm(alarm_id: int, reason_id: int) -> bool:
    """Return True when the FusionSolar catalogue marks this alarm as needing a manual clear."""
    if alarm_id not in MANUAL_CLEAR_ALARMS:
        return False
    reasons = MANUAL_CLEAR_ALARMS[alarm_id]
    return reasons is None or reason_id in reasons
