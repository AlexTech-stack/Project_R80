# AGENTS.md

Instructions for coding agents working in this repository.
Read this whole file before you change anything. Follow every rule in it.
If a rule here conflicts with what you think is best, follow the rule and tell the owner.

## 1. What this project is

- Project R80 builds a new headunit (hardware and software) and centre console
  for one heavily modified 2005 Audi A3 Sportback (8PA, PQ35 platform).
- The owner is Alex (GitHub: `AlexTech-stack`).
- The project is at an early stage. There is one headunit software (`hu/`) with
  three run modes, all started with `./r80`:
  - `demo`: only the UI, on fake data. No services, no D-Bus.
  - `virtual`: the whole headunit on a PC without target hardware; `dev/` stands in
    for the MCU and the phone, BoAt for the car (`test/boat/`).
  - `bench`: the headunit on the Raspberry Pi bench (`bench/pi/`, `docs/bench-pi.md`).
- `hu-can/` holds a made-up test CAN database. There is no real one yet.
- `docs/architecture/` holds the architecture draft (v0.3).
- `companion-android/` is the R80 Companion app on the driver's phone (D11).
- `hardware/` is an empty placeholder.

## 2. Repository layout

```
README.md                         project overview, quick start, licences
LICENSE                           MIT (software)
AGENTS.md                         this file
CLAUDE.md                         extra notes for Claude; imports this file
.github/workflows/ci.yml          GitHub Actions CI; each job calls a script in ci/
.github/workflows/canary.yml      nightly BoAt canary (BoAt master + latest release), not blocking
ci/check_static.sh                static checks (py_compile, repo rules, DBC, simulator, screenshots)
ci/check_rules.py                 checks the rules of this file that a script can check
ci/run_boat_sil.sh                BoAt smoke tests of the virtual mode (--install: pinned BoAt release)
ci/boat.version                   the BoAt release CI tests against
ci/dut/                           emulated aarch64 DUT for CI: Dockerfile, start script, private bus config
ci/fetch_boat_gateway.py          gets boat_gateway for a BoAt commit from BoAt's CI image (no Docker)
ci/boat_report.py                 BoAt reports as Markdown (CI job summaries)
ci/build_android.sh               builds and unit-tests the companion app (companion-android/)
docs/architecture/HU_architecture_v0.3.md   architecture and decisions D1 to D14
docs/companion-protocol.md        phone (R80 Companion app) <-> HU link protocol (D11)
docs/companion-protocol-examples.jsonl  protocol examples both sides test against
docs/bench-pi.md                  the Raspberry Pi bench: setup and operation
docs/bench-measurements.md        start-up time and memory on the bench (./r80 bench measure)
docs/screenshots/                 every UI screen, rendered by ./r80 demo screenshots
docs/ui/, docs/images/            UI vision and car reference; pictures for the READMEs
companion-android/                R80 Companion, the Android app on the driver's phone (D11, Kotlin);
                                  tools/make_icons.py: the app's icons from hu/ui/qml/Icons.qml
r80                               the one entry point: ./r80 demo | virtual <cmd> | bench <cmd>
hu/                               the headunit software (target software: runs unchanged on the Pi)
  services/                       the services, each with its config file
    mcu_link.py                   MCU <-> Linux UART protocol (placeholder)
    dbc.py                        small DBC decoder, no dependencies
    vehicled.py                   vehicle service, publishes D-Bus de.r80.Vehicle
    mediad.py                     media service (GStreamer), D-Bus de.r80.Media
    audiod.py, audio.ini          audio service (volume, mute, D9), D-Bus de.r80.Audio, and its config
    warnd.py, warnings.ini        vehicle warnings (D10), D-Bus de.r80.Warnings, and its rules
    tripd.py, trip.ini            trip computer (D10), D-Bus de.r80.Trip, and its config
    companion_link.py             companion app <-> HU protocol (D11, docs/companion-protocol.md)
    navd.py, nav.ini              navigation service and the companion link (D11): guidance, weather, car status, remote
    sysd.py, system.ini           system and settings service (D12), D-Bus de.r80.System, and the settings' schema
    saver.py                      a service's part in the shutdown: register with sysd, save, report
    removable.py                  USB sticks for mediad through udisks2 (mount read-only, gone)
    browse.py                     mediad's browse tree: folders, artists, albums, all tracks
    btmedia.py                    music from the phone for mediad: its AVRCP player in BlueZ
    phoned.py                     phone service (D13): calls over hands-free, D-Bus de.r80.Phone
    phonebook.py, vcard.py        the phone's contacts and call history (PBAP via obexd), the copy per phone
    callaudio.py                  Bluetooth sound on PipeWire: call and phone-music stages, levels, mic mute
    dlt.py                        the services' log: DLT (Diagnostic Log and Trace) through libdlt, Python logging
    dlt.conf, dlt-daemon.sh       the HU's own DLT daemon (COVESA dlt-daemon): files on the HU, DLT Viewer on TCP 3490
    dltclient.py                  reads DLT (protocol version 1) from the daemon or a file; control messages
    diagnostics.py                Settings -> Diagnostics: warnings and errors per service (sysd)
  ui/                             Qt 6 / QML UI, launched with PySide6
    run.py                        the launcher: live (D-Bus backends), --demo, --screenshots
    backend.py                    the R80.Backend QML singletons, one per service, over D-Bus
    covers.py                     cover art tinted in the accent colour (image://cover)
    hu.qmlproject                 Qt Design Studio project (open this in Design Studio)
    qml/main.qml                  window, screen switching, knob/key handling
    qml/Theme.qml                 all colours, fonts and sizes
    qml/Sim.qml                   the data the screens show: from R80.Backend; live "–" while a service is missing, demo: fake
    qml/Icons.qml                 self-drawn line icons as SVG path data
    qml/ManeuverIcon.qml          navigation maneuver arrows, drawn in code (D11)
    qml/*Screen.qml               one file per screen
    qml/MediaBrowser.qml          the media browse list (folders, artists, albums, tracks)
    qml/PhoneConsent.qml          the first time a phone connects: copy its contacts?
    qml/Logo.qml                  the placeholder "R80" brand mark
    qml-demo/R80/Backend/         demo stand-ins for the backend.py singletons (available: false)
    fonts/                        B612 and OSP-DIN with their licence files
hu-can/
  r80_test.dbc                    test CAN database (generated, do not hand-edit)
  tools/make_dbc.py               generates r80_test.dbc from one table
  tools/r80_can_sim.py            drive-cycle simulator (candump log or live CAN)
  sample_drive_60s.log            60 s sample drive, candump format
dev/                              PC stand-ins for the virtual mode (PC only)
  hu-virtual.sh                   up | drive | restbus | panel | phone | phonepanel | tunnel | ui | test | status | logs | down
  mcu_emu/                        MCU emulator and its control client
  phone_emu/                      phone emulator and phone panel (GUI): companion app stand-ins; stand-ins
                                  for PipeWire's telephony, obexd (PBAP) and BlueZ's AVRCP player
  media_tags.py                   test media: ID3 tags with generated covers, the test library
  udisks_emu.py                   stand-in for udisks2 with USB sticks (folders), for the tests
test/boat/                        BoAt restbus node, tester panel and the BoAt tests (PC only; list in dev/README.md)
bench/pi/                         Raspberry Pi bench: kiosk script, systemd units, CAN tunnel, PC helpers,
                                  PipeWire / WirePlumber settings, the built-in Bluetooth's SCO routing,
                                  measure.py (start-up time and memory, ./r80 bench measure)
hardware/                         hardware designs later; CERN-OHL-P-2.0
```

## 3. How to run and check things

Install Python dependencies once:

```bash
python3 -m pip install PySide6 cantools python-can
```

All run modes go through `./r80` (`./r80 --help`).

UI on fake data (demo mode):

```bash
./r80 demo                         # window, 1280 x 768
./r80 demo screenshots /tmp/shots  # render every screen to PNG, then exit (default: docs/screenshots)
```

- Use `--screenshots` to check any UI change. Open the PNGs and look at them.
- On a headless Debian/Ubuntu machine, `--screenshots` also needs:
  `sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1 libglib2.0-0t64 libdbus-1-3 libgssapi-krb5-2 libx11-6`
  (Debian 12 / Ubuntu 22.04: `libglib2.0-0` instead of `libglib2.0-0t64`).

Test CAN database and simulator:

```bash
python3 hu-can/tools/make_dbc.py                     # regenerate hu-can/r80_test.dbc
python3 hu-can/tools/r80_can_sim.py --log drive.log  # write a candump log
```

Virtual headunit (only on Alex's PC; needs BoAt, vcan and sudo):

```bash
./r80 virtual drive   # buses, BoAt gateway, MCU emulator, the services, drive cycle
./r80 virtual ui      # UI window on top (live)
./r80 virtual up && ./r80 virtual panel   # tester panel instead of the drive cycle
./r80 virtual up && ./r80 virtual test    # run the BoAt tests
./r80 virtual down
```

Raspberry Pi bench (`docs/bench-pi.md`): `./r80 bench install|start|stop|restart|status|logs|update`
on the Pi, `./r80 bench tunnel` on the PC.

CI (GitHub Actions, `.github/workflows/ci.yml`) runs on every push to every branch.
It runs the static checks on x86_64 and on aarch64 in Debian 13 (like the Pi bench),
so an x86-only dependency fails CI (section 8).
Its jobs only call scripts in `ci/`, so you can run the same checks locally:

```bash
ci/check_static.sh            # py_compile, repo rules, DBC and simulator drift, screenshots
SKIP_UI=1 ci/check_static.sh  # same without the screenshots
```

CI also runs the BoAt tests with the BoAt release pinned in `ci/boat.version`
(`ci/run_boat_sil.sh --install`). To move to a newer BoAt, change that file and push.
A second job runs them with the DUT (`dev/mcu_emu/` and the services in `hu/services/`) in a
Debian 13 container per CPU, arm64 (QEMU-emulated, like the Pi) and amd64, while BoAt
stays on the x86 host (`ci/run_boat_sil.sh --install --dut-arch=arm64`; needs docker,
and qemu-user-static for arm64).
The `boat-canary` workflow runs the same tests nightly against BoAt `master` and BoAt's
latest release. It does not block anything. When it fails and the cause is in BoAt,
follow section 7.

The companion app has JVM unit tests (`ci/build_android.sh`, CI job `android`; needs JDK 21,
Gradle 9.8 and the Android SDK). There is no unit test suite for the Python side yet. Before you commit:

1. Run `ci/check_static.sh`, or at least `python3 -m py_compile` on every Python file you changed.
2. If you changed QML, run `./r80 demo screenshots <dir>` and check the images. If the screens
   changed, also update `docs/screenshots` (`./r80 demo screenshots`).
3. If you changed `hu-can/tools/make_dbc.py`, regenerate `r80_test.dbc` and commit both.
4. If you changed anything in `hu/`, `dev/` or `test/boat/` and you can run BoAt, run `ci/run_boat_sil.sh`
   (or `./r80 virtual test`). If you cannot run it, say so and check the `boat-sil` CI job instead.

## 4. Git rules

- Larger features or changes go on a feature branch named after the work
  (for example `Media_Application`). Small, focused changes (a doc fix, a one-file
  change) go directly to `master`, without a branch or pull request.
- Do NOT create a branch per commit. Open a pull request only when Alex asks for one;
  Alex merges the pull requests and deletes branches. Delete a branch only when he
  asks.
- Write short, clear commit messages that say what changed and why.
- Never force-push `master`. Never rewrite published history.
- Never commit secrets, tokens, or personal data.
- Run `git pull` before you start and before you push.

## 5. Naming and branding

- Avoid the name "Audi" and the Audi logo wherever possible.
- Name Audi only when the text is directly about the target car
  (for example: "2005 Audi A3 Sportback 8PA").
- Never put the Audi rings in the UI, in images or in icons.
- Do not add trademark disclaimers or explanations about why the logo is missing.
- The brand mark is a placeholder ("R80"). When docs mention it, use this wording:
  "The brand mark is a placeholder ("R80"). Swap `qml/Logo.qml` if you want something else."

## 6. Licences and third-party material

- Software is MIT (root `LICENSE`).
- Hardware designs in `hardware/` (schematics, PCBs, console CAD) are CERN-OHL-P-2.0.
- Use only open-source or self-written frameworks, libraries, fonts, icons and images.
  Do not add proprietary SDKs, closed binaries, or assets with unclear licences.
- Bundled fonts keep their own licence files next to them. Never delete those files.
- Never commit OpenStreetMap data (`*.osm`, `*.osm.pbf`, `*.mbtiles`, tiles). It is ODbL.
- Icons and car drawings are drawn in code. Keep it that way; do not import icon sets.

## 7. BoAt (Alex's test framework)

- BoAt is a separate project by Alex. On Alex's PC it lives at `~/BoAt`
  (`/home/testuser/BoAt`). The virtual mode (`dev/`, `test/boat/`) uses it for the restbus and the tests.
- BoAt (gateway, restbus, tester panel, tests) runs on the test PC (x86_64) only.
  It never runs on the Raspberry Pi or the final headunit: those are the DUT.
- NEVER change, patch or "fix" anything in BoAt. Not even a one-line fix.
- Do not create, edit or delete any file in the BoAt repository or in `~/BoAt`
  (no notes, no git operations there). Read it only. To look at other BoAt versions,
  use a separate clone (as `ci/run_boat_sil.sh --install` does) or the GitHub API.
- NEVER work around a BoAt bug silently in this repo.
- When you find a BoAt issue, check the BoAt GitHub issues (open and closed) and the
  newer BoAt releases and `master`. If it is not already reported or fixed, open an issue
  in `AlexTech-stack/BoAt` with:
  1. What you did (commands, inputs, versions).
  2. What you expected to happen.
  3. What actually happened (exact error text or output).
- Then tell Alex about the issue.

## 8. Technical constraints

- The final headunit hardware is not chosen. It is almost certainly ARM.
  Development is benched on a Raspberry Pi 3B+ or 4.
- Keep all software portable. Put hardware-specific code in a thin, separate layer.
  No Pi-specific code outside that layer. No x86-only dependencies.
- Code under `hu/` is target software. It must not import BoAt, `dev/` (`mcu_emu/`,
  `phone_emu/`) or `test/boat/`.
- The CAN database is a made-up test DBC. Rules for it: classic CAN only (no CAN FD),
  one signal per message, 11-bit standard IDs plus one 29-bit extended ID (`0x18FF0100`).
- Edit the DBC through `hu-can/tools/make_dbc.py`, never by hand.
- The car has three CAN networks: Motor, Infotainment, Comfort. The headunit sits on
  Infotainment; the MCU's second channel listens only (decision D8). The HU must never
  send on Motor or Comfort.
- The MCU link protocol in `hu/services/mcu_link.py` is a placeholder. Keep all
  framing in that one file. Do not treat it as final.
- No Android Auto and no CarPlay. Do not add them.
- Navigation: the phone navigates, the HU only displays its guidance (D11). Do not add
  offline routing or a map renderer on the HU without asking Alex. Keep the companion
  link format in `hu/services/companion_link.py`, `companion-android/.../Protocol.kt` and
  `docs/companion-protocol.md` in step; both sides test against
  `docs/companion-protocol-examples.jsonl`.
- The companion app: Android 14+ (minSdk 34), no Google Play services, only open-source
  dependencies. Captured notifications contain the driver's streets: never commit them;
  only the derived arrow fingerprints go into `maneuver_icons.json`. The phone's position
  (weather, where the car is parked) stays on the phone: the HU gets the weather and the
  altitude, never coordinates; screenshots that show a position are not committed.
- The app looks like the HU: its fonts come from `hu/ui/fonts` (assets), its icons are
  generated from `hu/ui/qml/Icons.qml` (`companion-android/tools/make_icons.py`; add new
  icons there, never draw them in the app), its colours are the HU's accent colours.
- Phone (D13): calls go through PipeWire's own Bluetooth telephony service, not oFono.
  Contacts and call history are the driver's personal data: copied per phone only with
  consent, kept on the HU (mode 0600), never logged and never committed; tests use made-up
  phonebooks only. Phone sound (calls, phone music) keeps the phone at full level and sets
  the level on the HU's own PipeWire stages (`bench/pi/r80-pipewire.conf`).
- The stock instrument cluster stays (decision D1).
- Logging (D14): the services and the UI log through `hu/services/dlt.py` (Python `logging`, one DLT
  application per service, a context per part), not with `print`. Pick the level: error for what
  the HU did wrong, warning for what is off but handled, info for what happens. Log lines leave the
  car (the export): never phone numbers, contact or device names, streets; Bluetooth addresses
  only through `dlt.address()`.
- The architecture decisions D1 to D14 are in `docs/architecture/HU_architecture_v0.3.md`.
  Do not contradict them. If a change needs a different decision, ask Alex first.

## 9. Code conventions

- UI: Qt 6 QML (6.5 or newer), launched with PySide6. Design size is 1280 x 768.
- Put colours, fonts and sizes in `hu/ui/qml/Theme.qml`. Do not hard-code colours in screens.
- Visual style: black background, monochrome line art in the accent colour (red by default).
  See `docs/ui/UI_vision_V01.png`.
- The screens read their data only from `hu/ui/qml/Sim.qml`. Sim takes it from the
  R80.Backend singletons. In the live UI a service that is not there (yet) shows nothing:
  numbers NaN (show them through `Fmt.num` / `Fmt.known`: "–"), texts and lists empty. Only in
  demo mode (`System.demo`, the stand-ins) does Sim show its fake data. Never show fake
  values in the live UI.
  When you add or rename a Property, Signal or Slot in `hu/ui/backend.py`, add it to its
  demo stand-in in `hu/ui/qml-demo/R80/Backend/` too (`ci/check_rules.py` checks this).
- D-Bus property names in `vehicled.py` are the DBC signal names.
- Python: 3.9+, standard library first, type hints welcome, match the style of the file you edit.
- Keep changes small and focused. Do not reformat files you did not need to change.
- Update the matching README when you change how something is run or what a folder contains.

## 10. When you are unsure

- Do not guess about the real car, the real CAN bus, or hardware choices. Ask Alex.
- Do not delete files, folders or branches unless Alex asked for it.
- Report what you changed, what you checked, and what you could not check.
