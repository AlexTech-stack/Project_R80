# R80 Headunit – Architecture (v0.3)

Status: v0.3, last updated 2026-10-21 with Alex's decisions D1 to D14 (see §0). §4 to §6 say what is built
in `hu/` (runs on a PC and on the Raspberry Pi bench, started with `./r80`) and what is still a proposal.

## 0. Decisions so far (2026-09-28)

| # | Topic | Decision |
|---|---|---|
| D1 | Instrument cluster | Keep the stock cluster for now. The HU may send text to its DIS; the Drive screen stays an extra view on the HU. |
| D2 | Phone projection | No Android Auto, no CarPlay. A deeper Android phone link may come later but is out of scope for now. Since 2026-10-14 the R80 Companion app is that link (D11); projection stays out. |
| D3 | Audio | HU outputs to a separate DSP amplifier; no power amp on the HU board. |
| D4 | Compute platform | Bench development on a Raspberry Pi 3B+ or 4, upgrade only if needed. Final hardware is chosen once the software nears feature completion; almost certainly ARM-based. The software must therefore stay portable (no Pi-specific code outside a thin hardware layer). |
| D5 | Vehicle data | All vehicle values (speed, rpm, ignition, lights, range, odometer, temperatures, pressures, …) are available on CAN. No diagnostic polling or extra sensors planned. |
| D6 | CAN database | No real message list yet. Development uses a made-up test DBC: classic CAN, one signal per message, standard IDs plus one extended ID. See `hu-can/`. |
| D7 | Car networks | The car has three CAN networks: Motor (powertrain), Infotainment, Comfort. Which one carries each signal at the HU is not yet known. |
| D8 | CAN channels | Agreed for now (2026-09-29): vehicle MCU gets two CAN channels, CAN 1 active on Infotainment, CAN 2 listen-only on Motor or Comfort. Revisit once real bus logs exist. |
| D9 | Audio and volume | Agreed 2026-10-13: one audio service (`audiod`) owns all audio: master volume, one volume per source (media, navigation, phone, radio), mute, and how sources affect each other. A navigation prompt lowers music; a call (from ringing on) pauses media and mutes radio, media resumes afterwards; while the HU is off, media is paused (2026-10-20). The last volume is remembered and capped at startup. Volume is handled in the HU for now (the DSP amp of D3 is not chosen) and does not depend on CAN signals. The numbers live in a config file, not in code. UI: volume shown on every screen, master volume popup from it, per-source volumes under Settings → Audio. |
| D10 | Vehicle warnings and trip computer | Agreed 2026-10-14: a warning service (`warnd`) watches the CAN signals and shows as many warnings as possible, even where the stock cluster (D1) shows the same. Thresholds, hysteresis and timing live in a file, not in code; the first values are placeholders, not the real car's. Severity says how soon the driver has to act: *warning* within seconds (tyre pressure falling fast, oil pressure gone; warning chime, banner until acknowledged), *information* within minutes or hours, the car can still reach a workshop or fuel (tyre pressure low, range low; information chime, banner until acknowledged), *notice* not dangerous, some time soon (service due or overdue; silent). For tyre pressure the speed of a drop counts: a fast drop is a warning even while the value is still fine. Oil pressure has a static limit only (it falls fast on every lift-off). The chimes are generated in code; the information chime follows the chime volume and mute, the warning chime is audible even when muted. A trip computer (`tripd`) keeps a trip since start (resets itself after more than 2 h with the ignition off) and a long-term trip (reset by hand); consumption comes from the car's own value for now. |
| D11 | Navigation | Agreed 2026-10-14: the phone navigates, the HU displays. A full offline navigation on the HU is not built: it would be the most resource-hungry part of the device, always worse than the phone's, and a readable map in the HU's style is a project of its own. An own Android app (R80 Companion, in this repo, Android 14 and newer) reads the turn-by-turn guidance of the phone's navigation app (Google Maps' navigation notification first, OsmAnd's interface as a second source) and sends it over Bluetooth RFCOMM to the HU (`docs/companion-protocol.md`). A navigation service (`navd`) publishes it; the UI shows the next maneuver, distance, street and arrival in its own style. Navigation needs the phone; that is accepted. The voice prompts come from the phone. Later: a reduced overview map drawn by the HU itself (main roads only), more phone sensors, and extending the HU's UI from the phone (concept open). A pointer towards the destination is dropped for now: there is no easy way to get the destination's coordinates. |
| D12 | System and settings | Agreed 2026-10-15: a system service (`sysd`) keeps the user's settings and saves them, so they survive a restart; what each setting may be (type, range, default) lives in a file, not in code. It also coordinates the shutdown: when the MCU announces off, the services save their state, then the MCU gets its acknowledgement, and on the target Linux powers off cleanly before the MCU cuts the power (off on the bench). Display brightness at night follows the car's dimmer as the base, with the user's brightness setting on top (like modern devices). English only, no language setting, at least until feature complete. The HU always starts on Home. Logging and software updates come later. |
| D13 | Phone | Agreed 2026-10-20: a phone service (`phoned`) does calls over Bluetooth hands-free on PipeWire's own telephony service (no oFono): ringing with caller ID, answer, reject, end, dial, microphone mute; one phone at a time, the one that connected last. Contacts and call history are copied from the phone (PBAP) and kept on the HU per phone, only with the driver's consent (asked the first time a phone connects; Settings → Phone syncs again or deletes the copy); favourites are local to the HU. Phone sound keeps the phone at full level; the HU sets the level itself on PipeWire stages of its own (calls: phone volume plus a call boost; music from the phone: the media volume). Music from the phone is a media source (A2DP + AVRCP): the phone plays and keeps the queue. |
| D14 | Logging and diagnostics | Agreed 2026-10-21: the HU logs with DLT (AUTOSAR Diagnostic Log and Trace), protocol version 1 so DLT Viewer and the COVESA tools read it: the HU runs the COVESA dlt-daemon (ECU ID `R80`), every service and the UI is a DLT application with contexts per part, and log levels can be changed from outside (DLT Viewer, Settings → Diagnostics) and are kept. The daemon keeps a 16 MB ring of files on the HU. Settings → Diagnostics shows the warnings and errors per service and exports the files onto a USB stick; the stick, mounted read-only for music, is mounted writable only for that (the music from it stops for a few seconds). Logs never hold personal data (D13). The vehicle MCU's own log can join later as a second ECU (AUTOSAR CP Dlt). |

Car: Audi A3 Sportback 8PA, 2005 (PQ35 platform), heavily modified.
Starting point: the QML mockup v0.3 (now the UI in `hu/ui/`).

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
| Connectivity | BT 5 + Wi-Fi combo module; optional LTE modem | Hands-free, music streaming, updates, weather. No projection (D2). Call audio (SCO) must reach Linux reliably: a fast HCI link (USB, or UART with flow control and enough baud rate), or SCO over PCM straight into the DSP (D3), which also suits echo cancellation. The Pi 3B's built-in Bluetooth (UART) drops calls and A2DP under load (bench, 2026-10-20). |
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
│  (MCU link,(MPD/    (tuner   (BlueZ + (guidance (PipeWire (power,     │
│  signals)  GStreamer,driver)  oFono:  from the   + Wire-   updates,   │
│            BT A2DP)           HFP,PBAP)phone app)Plumber)  settings)  │
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
| audio | own code (`audiod`, D9); PipeWire as the output | Built: master and per-source volumes, mute, ducking for navigation prompts and chimes, call rules; tone controls stored until the DSP (D3) is chosen. |
| media | own code (`mediad`), GStreamer | Built: the Library (the HU's own music folder) and USB sticks via udisks2 (read-only, plugged in = plays), music from the phone (A2DP + AVRCP, D13), resume per source at start, browsing (folders, artists, albums) with a queue, playback, gain from audiod, tags and covers (cached on the HU, shown tinted). Planned: AUX only if the DSP has an input. No SD card slot (an internal library instead). |
| vehicle info | own code (`warnd`, `tripd`, D10) | Built: warnings with chimes, trip computer. |
| phone | own code (`phoned`, D13) on PipeWire's Bluetooth telephony, BlueZ obexd (PBAP) | Built: calls (HFP: caller ID, answer, reject, end, dial, microphone mute), contacts and call history copied per phone with consent, local favourites, the call's own PipeWire stage at the phone volume plus a call boost. Planned: echo cancellation (a PipeWire filter in the call stage), messages (MAP). |
| radio | own driver for the tuner module | Planned: FM/DAB+, RDS/DLS text, presets (tuner not chosen). |
| navigation | own code (`navd`), guidance from the R80 Companion app over BlueZ RFCOMM (D11) | Built: the phone's navigation app routes; the HU shows its guidance in the line-art style. Later: a small overview map drawn by the HU. |
| system | own code (`sysd`, D12) | Built: settings storage, shutdown coordination with the MCU, display brightness, system information. Later: software updates. |
| logging | COVESA dlt-daemon and libdlt (D14) | Built: one DLT log for the services and the UI (`hu/services/dlt.py`), a 16 MB ring of files on the HU, DLT Viewer over TCP 3490; sysd reads it as a client for Settings → Diagnostics (warnings and errors per service, log level per service) and the export onto a USB stick. Later: the system's own log (PipeWire, BlueZ, kernel) through `dlt-system`, the MCU's log as a second ECU. |

Why D-Bus: BlueZ, oFono, PipeWire, MPRIS and systemd already speak it, Qt has
native support, and each service can be restarted or tested on its own.

---

## 5. How the existing UI carries over

Done as planned:

1. **Every screen and the Theme stayed.** They are the HMI.
2. **A backend replaces the simulated data**: `hu/ui/qml/Sim.qml` keeps the
   mockup's property names and fills them from the D-Bus services (`hu/ui/backend.py`).
3. **The simulation stays in the same Sim.qml**: where a service is missing, Sim falls
   back to its simulated values. The demo mode (`./r80 demo`, Qt Design Studio) loads
   stand-ins for the backends (`hu/ui/qml-demo/`) that are never available, so the UI
   runs on any PC without the services.
4. **Knob and keys** arrive from the MCU as the same events as the keyboard.

Still open: a small C++ launcher instead of PySide6 boots faster and saves RAM on a small
board; the QML stays identical. Start-up targets to design for (proposal): UI visible
< 8 s after ignition, audio resumes < 5 s, reverse camera < 2 s (would need an MCU /
early-boot fast path).

---

## 6. Next steps

Done:
- Test DBC and drive simulator (`hu-can/`); BoAt restbus and tests in CI (host, arm64 and
  amd64 containers).
- Services for vehicle, media, audio (D9), warnings and trip (D10), navigation with the
  R80 Companion app (D11), system and settings (D12), with the UI on them.
- Media complete for local files: tags and covers, the Library and USB sticks, resume
  per source, browsing (folders, artists, albums) with a queue.
- Phone (D13): calls over hands-free, contacts and call history with consent, local
  favourites, music from the phone; stand-ins for PipeWire's telephony, obexd and BlueZ's
  player in the virtual environment.
- Logging and diagnostics (D14): one DLT log, Settings → Diagnostics, export onto a stick.
- One product, three run modes (`./r80 demo | virtual | bench`).
- Raspberry Pi 3B bench: CAN tunnel from the test PC, headless display over VNC, the
  phone over real Bluetooth, USB sticks (`docs/bench-pi.md`).

Next:
1. Bench: a USB Bluetooth adapter instead of the Pi 3B's built-in one, then the long call
   and phone-music tests; echo cancellation for the car's speakers and microphone.
2. Startup time and memory on the Pi against the targets of §5 (UI < 8 s).
3. Software updates (D12); the system's own log (PipeWire, BlueZ, kernel) into DLT.
4. Radio with a simulated tuner behind a thin hardware layer (needs: FM only or FM + DAB+).
5. Log the three real buses and replace the test DBC with the real messages (also: DIS
   text to the cluster, the dimmer input).
6. Hardware: vehicle MCU and its firmware, the DSP amplifier (D3), the tuner, the final
   board (D4).
7. Requirements per function.

---

## 7. Open questions for Alex

None open right now. Waiting for the real car: which bus carries each signal (D7), the
cluster's DIS text messages and the dimmer signal (terminal 58d).
