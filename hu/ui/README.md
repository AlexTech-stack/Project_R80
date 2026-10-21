# R80 Headunit – UI

The headunit's UI for the Audi A3 Sportback (8PA, 2005) project: Qt 6 / QML, launched
with PySide6. Everything runs on Linux with open-source parts only.

The same QML runs in all three modes (see the [root README](../../README.md)):

- **live** (`./r80 virtual ui`, the Pi bench): `run.py` registers the R80.Backend
  singletons from `backend.py`, which talk to the services over D-Bus.
- **demo** (`./r80 demo`, Qt Design Studio): `qml-demo/R80/Backend/` stands in for
  them. Every stand-in says `available: false` (and `System.demo: true`), so `qml/Sim.qml`
  shows its fake data. In the live UI a service that is not there yet shows "–" instead.

![Overview](../../docs/screenshots/overview.png)

## Run it

Needs Python 3.9+ and Qt 6 via PySide6 (LGPL):

```bash
python3 -m pip install PySide6        # once
./r80 demo                            # demo, window, 1280 x 768 (from the repo root)
./r80 demo --fullscreen
./r80 demo screenshots                # render every screen to docs/screenshots and quit
python3 hu/ui/run.py                  # live: needs the services (./r80 virtual up)
python3 hu/ui/run.py --screenshot x.png   # one frame after 3 s, live (or with --demo)
```

The QML is plain Qt 6 (6.5 or newer), so it also runs with the distro's Qt tools
without Python, e.g. on Debian/Ubuntu:

```bash
sudo apt install qml6 qml6-module-qtquick qml6-module-qtquick-shapes qml6-module-qtquick-window qml6-module-qtqml-workerscript
qml6 -I hu/ui/qml-demo hu/ui/qml/main.qml   # demo; the binary may be called `qml` on other distros
```

### Qt Design Studio

Open `hu.qmlproject` in Qt Design Studio (made for 4.8). It puts `qml-demo/` on the
import path, so every screen renders in the 2D view with the fake data from
`qml/Sim.qml`, and Live Preview / Run starts `qml/main.qml`; no services or D-Bus
needed. `run.py` and `./r80` do not use the project file.

## Controls (MMI-style)

| Input | Action |
|---|---|
| Mouse / touch | tap anything |
| Mouse wheel, ↑ / ↓ | turn the control knob |
| ← / → | push the knob sideways (tune, tabs, sliders) |
| Enter / Space | press the knob |
| Esc / Backspace / H | back to home (in the media browse list: up one level) |
| 1 – 8 | jump to Navigation, Media, Radio, Phone, Vehicle, Drive, Clock, Settings |
| Volume (header, right of the temperature) | click: master volume popup; knob or slider changes it, Mute button, press or Esc closes |
| C | simulate an incoming call (demo only; live calls come from the phone) |
| W | simulate vehicle warnings (banner, header indicator, Vehicle → Warnings) |
| N | cycle the navigation states: guidance, phone link lost, no route, no phone, rerouting, long signpost, destination on the left (D11) |
| F11 | toggle fullscreen |

## Screens

Home, Navigation (turn-by-turn guidance from the phone, D11: maneuver, distance,
street, arrival; no map), Media (sources as tabs, cover, up next; Browse: folders,
artists, albums, all tracks; Bluetooth: the phone's music), Radio (FM dial),
Phone (favourites/recent/contacts from the phone's copy, a contact's numbers and the
favourite switch, keypad, call popup; the first time a phone connects the HU asks whether
to copy its contacts), Vehicle (status, trip, tyres,
service), Drive (virtual cluster), Clock & Weather (the weather and the altitude come
from the phone, the R80 Companion app; "–" without it), Settings. Under
Settings → Display you can change brightness and the accent colour (red, amber,
white, ice blue) live; Settings → Phone keeps, syncs or deletes the copy of the
phone's contacts (D13) and allows or stops the app's remote ("Remote from the app"); Settings → System shows what runs (live: the values
of `hu-sysd`, D12); Settings → Diagnostics shows the log's warnings and errors per
service, sets a service's log level with the knob and exports the log onto a USB stick (D14).
The UI logs into DLT as application `HMI`, Qt's and QML's own messages as its context `QML`.

The master volume is shown in the header on every screen, right of the outside
temperature; clicking it opens the volume popup. Settings → Audio has one volume
per source (media, navigation, phone, radio, chimes) above the tone settings (D9, D10).

Vehicle warnings (D10): an unacknowledged *warning* (filled) or *information*
(outlined) shows as a banner below the header until OK or a knob press; a
*notice* shows for 5 s only. The header shows a warning triangle with the count
(bright while one is open); clicking it opens Vehicle → Warnings, the full list.
Vehicle → Trip shows two trips, "since start" (starts over after 2 h with the
ignition off) and "long-term", each with its own Reset.

## Layout of the code

```
run.py                 launcher: live, --demo, --screenshots
backend.py             R80.Backend singletons (Vehicle, Media, Audio, Warnings, Trip, Nav, System) over D-Bus
covers.py              image://cover: a track's cover tinted in the accent colour (live only)
hu.qmlproject          Qt Design Studio project
qml/main.qml           window, header, screen switching, knob/key handling
qml/Theme.qml          colours, fonts, sizes (single place to restyle)
qml/Sim.qml            the screens' data: from R80.Backend; live: "–" while a service is missing; demo: fake
qml/Icons.qml          ~60 self-drawn line icons as SVG path data (24x24)
qml/*Screen.qml        one file per screen
qml/MediaBrowser.qml   media browse list: folders, artists, albums, tracks (knob, press, back)
qml/PhoneConsent.qml   the first time a phone connects: copy its contacts?
qml/CarFront.qml, CarSide.qml   self-drawn car line art
qml/VolumeBadge.qml, VolumePopup.qml   master volume in the header and its popup
qml/WarningBanner.qml  vehicle warning banner (D10)
qml/ManeuverIcon.qml   large line-art arrow per navigation maneuver (D11)
qml/Fmt.qml            distance and duration formatting
qml-demo/R80/Backend/  demo stand-ins for the backend.py singletons (ci/check_rules.py keeps them complete)
fonts/                 B612 (OFL/EPL) and OSP-DIN (OFL) with licence files
../../docs/ui/UI_vision_V01.png   the visual direction this UI follows
../../docs/ui/car_blueprint_reference.png  A3 8PA blueprint (AI-generated by Alex) used for the car drawings
```

## Notes

- Design resolution is 1280 x 768 (5:3, the proportions of the vision sheet); the
  window scales to any size.
- New backend Property, Signal or Slot in `backend.py`: add it to its stand-in in
  `qml-demo/R80/Backend/` too, and to `qml/Sim.qml` its fake value for demo mode and
  "unknown" (NaN, empty) for the live UI while the service is missing.
- The brand mark is a placeholder ("R80"). Swap `qml/Logo.qml` if you want something else.
- No third-party icon sets or images: icons, car drawings, maneuver arrows and the
  placeholder cover art are drawn in code. A track's own cover (live) is shown tinted
  in the accent colour, so the screen stays monochrome.
