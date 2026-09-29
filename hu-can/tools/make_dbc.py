#!/usr/bin/env python3
"""Generate r80_test.dbc: the R80 test CAN database.

Rules (Alex, 2026-09-29): classic CAN only, one signal per message, standard
11-bit IDs, except one message with an extended 29-bit ID for testing.
All signals are Intel byte order (little endian, like VW), unsigned unless noted,
start at bit 0, DLC 8. Sender "CAR" stands for whatever puts it on the bus
(ECU, cluster or gateway); receiver is the headunit "HU".

Edit SIGNALS below and re-run to regenerate the DBC.
"""
import sys
from pathlib import Path
import cantools
from cantools.database.can import Database, Message, Signal, Node
from cantools.database.conversion import BaseConversion

# (message name, frame id, extended, cycle ms, signal name, bits, signed,
#  factor, offset, min, max, unit, value table, comment)
SIGNALS = [
    ("R80_VehicleSpeed",   0x100, False,   20, "VehicleSpeed",   16, False, 0.01,  0,    0, 400,     "km/h",   None, "Vehicle speed"),
    ("R80_EngineSpeed",    0x101, False,   20, "EngineSpeed",    16, False, 0.25,  0,    0, 10000,   "rpm",    None, "Engine speed"),
    ("R80_BoostPressure",  0x102, False,   50, "BoostPressure",  16, True,  0.001, 0,   -1, 3,       "bar",    None, "Boost pressure, relative to ambient (signed)"),
    ("R80_Gear",           0x110, False,  100, "Gear",            4, False, 1,     0,    0, 15,      "",
        {0: "N", 1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "R", 8: "P", 9: "D", 10: "S", 15: "Invalid"},
        "Selected gear"),
    ("R80_IgnitionState",  0x120, False,  100, "IgnitionState",   3, False, 1,     0,    0, 7,       "",
        {0: "Off", 1: "KeyInserted", 2: "Accessory", 3: "IgnitionOn", 4: "Cranking", 7: "Invalid"},
        "Key / ignition state (terminal S, 15, 50)"),
    ("R80_LightState",     0x121, False,  200, "LightState",      3, False, 1,     0,    0, 7,       "",
        {0: "Off", 1: "Parking", 2: "LowBeam", 3: "HighBeam", 7: "Invalid"},
        "Exterior light state, also drives HU night mode"),
    ("R80_CoolantTemp",    0x200, False,  500, "CoolantTemp",     8, False, 1,   -40,  -40, 215,     "degC",   None, "Engine coolant temperature"),
    ("R80_OilTemp",        0x201, False,  500, "OilTemp",         8, False, 1,   -40,  -40, 215,     "degC",   None, "Engine oil temperature"),
    ("R80_OutsideTemp",    0x202, False, 1000, "OutsideTemp",     8, False, 0.5, -50,  -50, 77.5,    "degC",   None, "Outside air temperature"),
    ("R80_OilPressure",    0x203, False,  100, "OilPressure",     8, False, 0.05,  0,    0, 12.75,   "bar",    None, "Engine oil pressure"),
    ("R80_BatteryVoltage", 0x210, False,  500, "BatteryVoltage",  8, False, 0.1,   0,    0, 25.5,    "V",      None, "Battery voltage (terminal 30)"),
    ("R80_FuelLevel",      0x220, False, 1000, "FuelLevel",       8, False, 0.5,   0,    0, 100,     "%",      None, "Fuel tank level, 55 l tank"),
    ("R80_Range",          0x221, False, 1000, "Range",          16, False, 1,     0,    0, 2000,    "km",     None, "Remaining range"),
    ("R80_AvgConsumption", 0x222, False, 1000, "AvgConsumption", 16, False, 0.1,   0,    0, 99.9,    "l/100km", None, "Average consumption since trip reset"),
    ("R80_Odometer",       0x230, False, 1000, "Odometer",       32, False, 0.1,   0,    0, 9999999, "km",     None, "Total distance"),
    ("R80_TripDistance",   0x231, False, 1000, "TripDistance",   16, False, 0.1,   0,    0, 6553.5,  "km",     None, "Trip distance since reset"),
    ("R80_ServiceDistance",0x232, False, 1000, "ServiceDistance",16, True,  1,     0, -32768, 32767, "km",     None, "Distance to next service, negative = overdue"),
    ("R80_TyrePressureFL", 0x240, False, 1000, "TyrePressureFL",  8, False, 0.02,  0,    0, 5.1,     "bar",    None, "Tyre pressure front left"),
    ("R80_TyrePressureFR", 0x241, False, 1000, "TyrePressureFR",  8, False, 0.02,  0,    0, 5.1,     "bar",    None, "Tyre pressure front right"),
    ("R80_TyrePressureRL", 0x242, False, 1000, "TyrePressureRL",  8, False, 0.02,  0,    0, 5.1,     "bar",    None, "Tyre pressure rear left"),
    ("R80_TyrePressureRR", 0x243, False, 1000, "TyrePressureRR",  8, False, 0.02,  0,    0, 5.1,     "bar",    None, "Tyre pressure rear right"),
    # The one extended-ID test message.
    ("R80_ServiceDays",    0x18FF0100, True, 1000, "ServiceDays", 16, True, 1, 0, -32768, 32767, "d", None,
        "Days to next service, negative = overdue. Extended 29-bit ID test message"),
]


def build():
    msgs = []
    for (mname, fid, ext, cycle, sname, bits, signed, factor, offset, mn, mx, unit, choices, comment) in SIGNALS:
        sig = Signal(
            name=sname, start=0, length=bits, byte_order="little_endian", is_signed=signed,
            conversion=BaseConversion.factory(scale=factor, offset=offset, choices=choices),
            minimum=mn, maximum=mx, unit=unit, receivers=["HU"], comment=comment,
        )
        msgs.append(Message(
            frame_id=fid, name=mname, length=8, signals=[sig], senders=["CAR"],
            is_extended_frame=ext, cycle_time=cycle, comment=comment,
        ))
    return Database(messages=msgs, nodes=[Node("CAR"), Node("HU")], version="0.1")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "r80_test.dbc")
    db = build()
    out.write_text(db.as_dbc_string())
    # Round-trip check: reload and make sure every message survived.
    back = cantools.database.load_file(str(out))
    assert len(back.messages) == len(SIGNALS)
    assert all(len(m.signals) == 1 for m in back.messages)
    assert sum(m.is_extended_frame for m in back.messages) == 1
    print(f"wrote {out} ({len(back.messages)} messages)")
