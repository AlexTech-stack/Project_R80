# hu-virtual: the R80 headunit without target hardware

Runs the headunit software on a Linux PC, with the car simulated by BoAt on
virtual CAN buses and the vehicle MCU replaced by an emulator process.

```
 BoAt (gateway :50061)                      "the headunit"
 ┌──────────────────────┐   vcan_info    ┌───────────────┐  UART (pty)  ┌──────────────┐  D-Bus   ┌────────────┐
 │ restbus.py  (R80 DBC)├───────────────►│ mcu_emu.py    ├─────────────►│ hu/vehicled  ├─────────►│ UI mockup  │
 │ tests/*.py           │   vcan_motor   │ power, knob,  │◄─────────────┤ DBC decode   │          │ (Sim.qml   │
 │ boat test run        │  (CAN 2, listen│ dimming, CAN  │              │ de.r80.Vehicle│         │  overlay)  │
 └──────────────────────┘   only)        └───────────────┘              └──────────────┘          └────────────┘
          ▲  mcuctl.py (knob, buttons, dim override) ────┘
```

| Part | Real car / bench | Virtual |
|---|---|---|
| CAN buses | Motor, Infotainment, Comfort | `vcan_motor`, `vcan_info`, `vcan_comfort` (SocketCAN) |
| Rest of the car | real ECUs | BoAt gateway + `boat/restbus.py` playing `../hu-can/r80_test.dbc` |
| Vehicle MCU, CAN 1 active on Infotainment, CAN 2 listen-only (D8) | MCU on the HU board | `mcu_emu/mcu_emu.py` (same UART protocol), CAN 2 on `vcan_motor` by default |
| MCU ↔ Linux | UART, e.g. `/dev/ttyAMA0` | pty, symlinked at `$XDG_RUNTIME_DIR/r80-mcu-uart` |
| Knob / buttons | MCU pins | `mcu_emu/mcuctl.py` over a control socket |
| Linux vehicle service | `hu/vehicled.py --system --uart /dev/ttyAMA0` | `hu/vehicled.py` (session bus) |
| UI | Qt 6 / QML | `../hu-mockup`, with `hu/ui/qml/Sim.qml` swapped in |

Everything under `hu/` is target software and has no BoAt dependency; it runs
unchanged on the Pi. `mcu_emu/` and `boat/` exist only for the PC.

## Run it

Needs: [BoAt](https://github.com/AlexTech-stack/BoAt) built at `~/BoAt` (or `BOAT_ROOT=`), Python 3 with PySide6,
dbus-python and PyGObject, and `sudo` once to create the vcan buses. No
cantools or python-can.

```bash
cd hu-virtual
./hu-virtual.sh drive      # buses, gateway, MCU emulator, vehicled, restbus drive cycle
./hu-virtual.sh ui         # the UI window on top (UI_ARGS="--fullscreen" etc.)
./hu-virtual.sh status
./hu-virtual.sh down
```

Poke it while it runs:

```bash
python3 mcu_emu/mcuctl.py knob 1           # turn (-1 = back)
python3 mcu_emu/mcuctl.py push
python3 mcu_emu/mcuctl.py button NAV       # HOME BACK NAV MEDIA RADIO PHONE CAR SETUP VOL_UP VOL_DOWN MUTE
python3 mcu_emu/mcuctl.py dim 30           # or "auto"
python3 mcu_emu/mcuctl.py status
gdbus call --session -d de.r80.Vehicle -o /de/r80/Vehicle \
  -m org.freedesktop.DBus.Properties.GetAll de.r80.Vehicle1
candump -a vcan_info
RESTBUS_ARGS="--lights LowBeam" ./hu-virtual.sh restbus   # night mode (stop the drive one first)
MCU_CAN2=vcan_comfort MCU_CAN2_BUS=comfort ./hu-virtual.sh up   # CAN 2 on Comfort instead of Motor
```

The UI falls back to the mockup's own fake data whenever hu-vehicled or the
MCU link is not there, so `run_hu.py` also works on its own.

## Tests (BoAt)

```bash
./hu-virtual.sh up
./hu-virtual.sh test       # boat test run boat/manifest_hu_smoke.json, reports in $XDG_RUNTIME_DIR/r80-hu/reports
```

| ID | Checks |
|---|---|
| TC_HU_001 | restbus values arrive decoded on D-Bus: signed, offset, enum, 32-bit, the 29-bit ID |
| TC_HU_002 | a missing message is flagged in `StaleSignals` and recovers |
| TC_HU_003 | on / acc / standby from IgnitionState, bus sleep → shutdown handshake → off, wake-up |
| TC_HU_004 | day/night from LightState, MCU dim override |
| TC_HU_005 | knob and button events reach D-Bus in order |
| TC_HU_006 | HU can send on Infotainment, never on Motor or Comfort (checked on the wire by BoAt) |

Each test starts its own `Restbus` from Python (`from restbus import Restbus`),
so stop the drive-cycle node first (`./hu-virtual.sh test` does that).

## Files

```
hu-virtual.sh            start/stop everything, run tests
build/                   git-ignored; the BoAt PDU database made from ../hu-can/r80_test.dbc
                         (tools/dbc2boatjson.py --bus Infotainment), rebuilt when the DBC changes
hu/mcu_link.py           MCU <-> Linux UART protocol (framing, message types)
hu/dbc.py                small DBC decoder/encoder, no dependencies
hu/vehicled.py           Linux vehicle service: UART -> DBC -> D-Bus de.r80.Vehicle
hu/ui/run_hu.py          UI launcher: mockup + Sim.qml overlay + MCU key input + power blanking
hu/ui/backend.py         QML singleton `Vehicle` (R80.Backend 1.0) mirroring D-Bus
hu/ui/qml/Sim.qml        mockup's Sim.qml with vehicle values bound to `Vehicle`
mcu_emu/mcu_emu.py       MCU emulator
mcu_emu/mcuctl.py        control client (also used by the tests)
boat/restbus.py          BoAt restbus node / library
boat/env_hu_virtual.json BoAt test environment (gateway started by hu-virtual.sh)
boat/manifest_hu_smoke.json
boat/tests/              the six tests
docs/                    two screenshots of the UI on live CAN data
```

## Assumptions to check

- **The MCU link protocol is a placeholder** (`hu/mcu_link.py`: HDLC-style
  framing, CRC-16, message types for CAN, power, input, dimming). Architecture
  v0.3 names the link "SPI/UART" but doesn't define a protocol yet; all framing
  lives in that one file.
- The whole test DBC is put on the Infotainment bus (as if the car's gateway
  routes it there). Motor and Comfort are up but idle; the emulator's CAN 2
  listens on one of them and only forwards its frames with `--forward-can2`.
- Power: no Infotainment traffic for 2 s = bus asleep; Linux gets 10 s to
  answer SHUTDOWN_READY. Night = LowBeam or HighBeam, night level 40 %.
- D-Bus property names are the DBC signal names; `backend.py` maps them to the
  mockup's names (`VehicleSpeed` → `speed`, `FuelLevel` % → `fuelLevel` 0..1, …).

## BoAt notes found on the way

Full write-ups with repro steps are in BoAt's `test/foundIssues.md` (issues 1 to 4).

- `boat/test/harness.py:355` passes the whole env config to `DutProxy`
  instead of `config.dut`, so any environment with a `dut` entry fails with
  `'EnvironmentConfig' object has no attribute 'type'` (line 401 does it right).
  `env_hu_virtual.json` leaves `dut` out for now.
- The test runner's gateway manager ignores the environment's `plugins` list
  (no `BOAT_NODE_PLUGINS`), which is one reason the gateway is started by
  `hu-virtual.sh`.
- `pdu_router` has no way to update a cyclic PDU's payload without an
  immediate extra send (`PduRouter::SendPdu` always transmits). That would
  double the rate of fast-changing signals, so the restbus paces frames itself
  through `FrameService.SendFrame` instead of using cyclic PDU routes.
