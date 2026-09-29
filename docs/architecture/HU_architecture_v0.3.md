# R80 Headunit – Architecture (v0.3)

Status: v0.3, 2026-09-29. Updated with Alex's decisions (see §0). Everything else is still a proposal.

## 0. Decisions so far (2026-09-28)

| # | Topic | Decision |
|---|---|---|
| D1 | Instrument cluster | Keep the stock cluster for now. The HU may send text to its DIS; the Drive screen stays an extra view on the HU. |
| D2 | Phone projection | No Android Auto, no CarPlay. A deeper Android phone link may come later but is out of scope for now. |
| D3 | Audio | HU outputs to a separate DSP amplifier; no power amp on the HU board. |
| D4 | Compute platform | Bench development on a Raspberry Pi 3B+ or 4, upgrade only if needed. Final hardware is chosen once the software nears feature completion; almost certainly ARM-based. The software must therefore stay portable (no Pi-specific code outside a thin hardware layer). |
| D5 | Vehicle data | All vehicle values (speed, rpm, ignition, lights, range, odometer, temperatures, pressures, …) are available on CAN. No diagnostic polling or extra sensors planned. |
| D6 | CAN database | No real message list yet. Development uses a made-up test DBC: classic CAN, one signal per message, standard IDs plus one extended ID. See `hu-can/`. |
| D7 | Car networks | The car has three CAN networks: Motor (powertrain), Infotainment, Comfort. Which one carries each signal at the HU is not yet known. |
| D8 | CAN channels | Agreed for now (2026-09-29): vehicle MCU gets two CAN channels, CAN 1 active on Infotainment, CAN 2 listen-only on Motor or Comfort. Revisit once real bus logs exist. |

Car: Audi A3 Sportback 8PA, 2005 (PQ35 platform), heavily modified.
Starting point: the QML mockup v0.3 in `hu-mockup/`.

Connector details in §3 describe a stock 2005 8P and are still to be checked on the car.

---

## 1. The big picture

```
                        ┌──────────────────────── HEADUNIT ─────────────────────────┐
                        │                                                           │
  Car 12 V (+30, +15) ──┼─► Automotive PSU ──► always-on rail ──► Vehicle MCU        │
  Illumination (58) ────┼─►  (load dump,                          (STM32-class)      │
                        │    cranking,                             • power states    │
  Infotainment CAN ─────┼─►  delayed off)  ──► switched rail ──┐   • CAN (+ wake)    │
  (via gateway J533)    │                                      │   • knob / buttons  │
                        │                                      │   • dimming, watchdog
  Middle console ───────┼─► knob, buttons, hazard etc. ───────►│   └──── SPI/UART ───┤
  controls              │                                      ▼                     │
                        │                            Application SoM (Linux)        │
                        │                            • HMI (the QML UI)             │
  Display + touch ◄─────┼── LVDS / eDP / MIPI ◄──────• services (below)             │
                        │                            │                              │
  Speakers / amp ◄──────┼── DSP + class-D amp ◄── I2S┤                              │
  Microphone ───────────┼──────────────────────► I2S ┤                              │
  FM / DAB+ aerial ─────┼─► tuner module ──── I2S/I2C┤                              │
  GNSS aerial ──────────┼─► GNSS module ──── UART ───┤                              │
  Phone ◄──── BT/Wi-Fi ─┼─► BT + Wi-Fi module ─ SDIO/UART                           │
  USB port(s) ──────────┼──────────────────────── USB┤                              │
  Reverse camera ───────┼──────────────── CSI / analog decoder ┘ (optional)         │
                        └───────────────────────────────────────────────────────────┘
```

The core idea is **two computers in one box**:

- A small **vehicle MCU** that is always powered, boots in milliseconds and owns
  everything "car": power on/off, CAN, the knob and buttons, dimming. It keeps
  working while Linux is booting, updating or has crashed.
- A **Linux application SoM** that runs the UI and all the media / phone / nav
  services. It only ever sees clean, already decoded data from the MCU.

This keeps the car safe from Linux (Linux never talks to the CAN bus directly),
makes start-up feel instant, and lets the Linux side be developed on a desktop PC
with the simulator, exactly like the mockup today.

---

## 2. Hardware blocks

| Block | Proposal | Why |
|---|---|---|
| Application computer | **Bench: Raspberry Pi 4 (2–4 GB) or 3B+** with a CAN HAT (MCP2515 or similar). **Final: open (D4)**, ARM-based, chosen near feature completion. | Pi 4 is the better start: Qt 6 Quick runs well on its GPU at 1280×768, and 1 GB on the 3B+ gets tight once nav and media run. Candidates for the final board, for later: i.MX 8M class, Rockchip RK35xx, Pi Compute Module. |
| Vehicle MCU | STM32G4 (or similar Cortex-M4 with CAN) | Always-on, µA standby, wake on CAN / +15, deterministic. On the bench this can start as a Nucleo board, or be skipped at first with the Pi reading the CAN HAT directly behind the same vehicle-service interface. |
| Power | 9–16 V automotive input, reverse/load-dump protection, survives cranking dips, MCU-controlled switched rail with delayed power-off | Linux needs a clean shutdown after ignition off; standby current must stay < 1 mA. |
| Display | 7–8" IPS panel, ~1280×768 or 1280×800, capacitive touch, high brightness | Mockup design size is 1280×768; exact size depends on the middle console design. |
| Audio | Line-level or digital (I2S/S/PDIF/TOSLINK) out to an external DSP amplifier (D3) | Keeps heat and power off the HU board. |
| Tuner | FM + DAB+ module (e.g. Silicon Labs Si468x class) | DAB+ matters in Germany. |
| Connectivity | BT 5 + Wi-Fi combo module; optional LTE modem | Hands-free, music streaming, updates, weather. No projection (D2). |
| GNSS | u-blox class module, FAKRA antenna | Navigation; can later add dead reckoning from CAN wheel speed. |
| Inputs | Rotary knob with push + tilt, hard keys, via MCU | Matches the MMI-style control model already in the mockup. |
| Optional | Reverse camera input | Nice to have, needs a fast-path design (see §5). |

---

## 3. Interfaces to the car

The stock 8P head units (Chorus / Concert / Symphony / RNS-E) plug into a **Quadlock**
connector behind the double-DIN slot. On a stock car that gives:

| Signal | Source | Used for |
|---|---|---|
| +30 permanent, ground | Quadlock | Power |
| +15 / S-contact | Quadlock or Infotainment CAN | Wake-up, power states |
| Infotainment CAN, 100 kbit/s | Quadlock, through gateway J533 | Ignition/key state, reverse gear, speed, outside temp, illumination, steering-wheel buttons, driver display (DIS) text in the cluster |
| Illumination (58) | Quadlock / CAN | Night dimming |
| Speaker outputs | Quadlock | Not used by the HU (D3); rerouted to the external amp |
| Aerial power, antennas | Quadlock / FAKRA | Radio, GNSS |

Vehicle data (D5): every value the screens show comes from CAN, received and
decoded by the MCU and published by the vehicle service. Battery voltage can
additionally be measured by the MCU on +30 as a cross-check.

The CAN message list lives in one DBC file shared by the MCU firmware, the
vehicle service and the bench simulator, so a change in the car means editing one
file, not code. Until the real list exists, the test database in
`hu-can/r80_test.dbc` stands in for it (D6).

**Which bus the HU connects to (D7).** The car has Motor, Infotainment and
Comfort CAN. The HU's natural home is the Infotainment CAN: that is where a stock
HU sits, where it gets its wake-up and where it sends text to the cluster DIS.
The gateway forwards some Motor and Comfort values onto it, but not necessarily
all of the ones we want. Agreed plan (D8): give the vehicle MCU **two CAN channels**:

| Channel | Bus | Mode | Why |
|---|---|---|---|
| CAN 1 | Infotainment | Active (transmit + receive) | Wake-up, DIS text, gateway-forwarded values |
| CAN 2 | Motor or Comfort (whichever carries missing values) | Listen-only | Picks up signals the gateway does not forward, without ever writing to that bus |

The vehicle service does not care which channel a signal came from; the DBC
(one per bus later) says where to find it. On the bench, one channel is enough.

---

## 4. Software layers (Linux side)

```
┌──────────────────────────────────────────────────────────────────────┐
│ HMI  – the existing QML screens (Theme, Icons, *Screen.qml)          │
│        + a thin "Backend" layer that replaces Sim.qml                 │
├──────────────────────────────────────────────────────────────────────┤
│ Services (separate processes, talk over D-Bus)                       │
│  vehicle   media    radio    phone    nav      audio    system       │
│  (MCU link,(MPD/    (tuner   (BlueZ + (MapLibre (PipeWire (power,     │
│  signals)  GStreamer,driver)  oFono:  + Valhalla + Wire-   updates,   │
│            BT A2DP)           HFP,PBAP)on OSM)   Plumber)  settings)  │
├──────────────────────────────────────────────────────────────────────┤
│ OS   – Yocto-built embedded Linux, systemd, read-only root,          │
│        A/B partitions for safe updates (RAUC or SWUpdate)             │
├──────────────────────────────────────────────────────────────────────┤
│ Hardware – SoM, display, audio, BT/Wi-Fi, GNSS, tuner, MCU link      │
└──────────────────────────────────────────────────────────────────────┘

MCU firmware (separate, bare-metal or Zephyr):
  power state machine · CAN receive/filter/decode · knob & keys ·
  DIS/cluster messages · watchdog of the SoM · link protocol to Linux
```

All open source, in line with the project rule:

| Service | Built on | Notes |
|---|---|---|
| vehicle | own code | Reads the MCU link, publishes named signals (`speed`, `coolantTemp`, …). The CAN message mapping lives in a DBC-style file, not in code. |
| audio | PipeWire + WirePlumber | Source switching, ducking media for nav prompts and calls, EQ. |
| media | MPD or GStreamer, BlueZ A2DP | USB library, BT streaming; exposes MPRIS. |
| phone | BlueZ + oFono | Hands-free (HFP), contacts and call list (PBAP), echo cancellation via PipeWire. |
| radio | own driver for the tuner module | FM/DAB+, RDS/DLS text, presets. |
| navigation | MapLibre Native (Qt plugin) + Valhalla routing + OpenStreetMap data, all offline | Fits the red line-art style with a custom map style. |
| system | own code | Power states with the MCU, settings storage, logging, updates. |

Why D-Bus: BlueZ, oFono, PipeWire, MPRIS and systemd already speak it, Qt has
native support, and each service can be restarted or tested on its own.

---

## 5. How the existing UI carries over

The mockup was built so this step is small:

1. **Keep every screen and the Theme as they are.** They are the HMI.
2. **Replace `Sim.qml` with a Backend** that exposes the same property names
   (`speed`, `rpm`, `track`, `volume`, …) but fills them from the D-Bus services.
3. **Keep `Sim.qml` as the "simulation backend"**, selectable at start, so the
   UI keeps running on any desktop PC without hardware.
4. **Knob and keys** already map to arrow/Enter/Esc events; the MCU delivers the
   real knob as the same events, so navigation logic does not change.
5. **Launcher**: PySide6 is fine on a PC. On a Pi 3B+/4 a small C++ launcher
   boots faster and saves RAM, which matters more on the smaller board. The QML stays identical.

Start-up targets to design for (proposal): UI visible < 8 s after ignition,
audio resumes < 5 s, reverse camera < 2 s (would need an MCU/early-boot fast path).

---

## 6. Next steps

1. Done for testing: test DBC and simulator in `hu-can/`.
   Later: log the three real buses and replace the test DBC with real messages.
2. Bench rig: Pi 4 (or 3B+) + CAN HAT + 7" screen, running the mockup UI with a
   vehicle service that replays recorded CAN logs.
3. Replace `Sim.qml` with the real Backend, keeping Sim as the desktop mode.
4. Write requirements per function and map them to these blocks.

---

## 7. Open questions for Alex

None open right now.
