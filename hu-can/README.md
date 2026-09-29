# R80 test CAN database

A made-up CAN database for developing the headunit before the real message list
exists. Rules (Alex, 2026-09-29): **classic CAN only, one signal per message,
standard 11-bit IDs, one extended 29-bit ID for testing.**

All signals: Intel byte order (little endian), start bit 0, DLC 8, sender `CAR`,
receiver `HU`. Cycle times are in the DBC (`GenMsgCycleTime`).

| ID | Message | Signal | Bits | Scale / offset | Unit | Cycle | Mockup property |
|---|---|---|---|---|---|---|---|
| 0x100 | R80_VehicleSpeed | VehicleSpeed | 16 | 0.01 | km/h | 20 ms | `speed` |
| 0x101 | R80_EngineSpeed | EngineSpeed | 16 | 0.25 | rpm | 20 ms | `rpm` |
| 0x102 | R80_BoostPressure | BoostPressure | 16 signed | 0.001 | bar (rel.) | 50 ms | new |
| 0x110 | R80_Gear | Gear | 4 | enum N,1–6,R,P,D,S | – | 100 ms | `gear` |
| 0x120 | R80_IgnitionState | IgnitionState | 3 | enum Off, KeyInserted, Accessory, IgnitionOn, Cranking | – | 100 ms | new (power states) |
| 0x121 | R80_LightState | LightState | 3 | enum Off, Parking, LowBeam, HighBeam | – | 200 ms | new (night mode) |
| 0x200 | R80_CoolantTemp | CoolantTemp | 8 | 1 / −40 | °C | 500 ms | `coolantTemp` |
| 0x201 | R80_OilTemp | OilTemp | 8 | 1 / −40 | °C | 500 ms | `oilTemp` |
| 0x202 | R80_OutsideTemp | OutsideTemp | 8 | 0.5 / −50 | °C | 1 s | `outsideTemp` |
| 0x203 | R80_OilPressure | OilPressure | 8 | 0.05 | bar | 100 ms | new |
| 0x210 | R80_BatteryVoltage | BatteryVoltage | 8 | 0.1 | V | 500 ms | `batteryVolt` |
| 0x220 | R80_FuelLevel | FuelLevel | 8 | 0.5 | % | 1 s | `fuelLevel` (×0.01) |
| 0x221 | R80_Range | Range | 16 | 1 | km | 1 s | `rangeKm` |
| 0x222 | R80_AvgConsumption | AvgConsumption | 16 | 0.1 | l/100 km | 1 s | `avgConsumption` |
| 0x230 | R80_Odometer | Odometer | 32 | 0.1 | km | 1 s | `odometer` |
| 0x231 | R80_TripDistance | TripDistance | 16 | 0.1 | km | 1 s | `tripKm` |
| 0x232 | R80_ServiceDistance | ServiceDistance | 16 signed | 1 | km | 1 s | `serviceKm` |
| 0x240–0x243 | R80_TyrePressureFL/FR/RL/RR | TyrePressure.. | 8 | 0.02 | bar | 1 s | `tyres[0..3]` |
| **0x18FF0100 (ext.)** | R80_ServiceDays | ServiceDays | 16 signed | 1 | days | 1 s | `serviceDays` |

## Files

- `r80_test.dbc` – the database (open it in SavvyCAN, Kayak, cantools, …).
- `tools/make_dbc.py` – generates the DBC from one table; edit and re-run to change it.
- `tools/r80_can_sim.py` – plays a 60 s drive cycle (idle, accelerate, cruise, brake)
  at the DBC cycle times, either to a candump log or live on a CAN interface.
- `sample_drive_60s.log` – 60 s of that drive in candump format.

```bash
pip install cantools python-can
python3 tools/make_dbc.py                       # regenerate r80_test.dbc
python3 tools/r80_can_sim.py --log drive.log    # write a log
sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0
python3 tools/r80_can_sim.py --channel vcan0    # live on a virtual bus (or can0 on the Pi HAT)
candump -a vcan0                                # watch it (can-utils)
canplayer -I sample_drive_60s.log               # or replay the sample log
```
