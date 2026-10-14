# AGENTS.md

Instructions for coding agents working in this repository.
Read this whole file before you change anything. Follow every rule in it.
If a rule here conflicts with what you think is best, follow the rule and tell the owner.

## 1. What this project is

- Project R80 builds a new headunit (hardware and software) and centre console
  for one heavily modified 2005 Audi A3 Sportback (8PA, PQ35 platform).
- The owner is Alex (GitHub: `AlexTech-stack`).
- The project is at an early stage:
  - `hu-mockup/` is a clickable UI mockup. All its data is fake.
  - `hu-can/` holds a made-up test CAN database. There is no real one yet.
  - `docs/architecture/` holds the architecture draft (v0.3).
  - `hu-virtual/` runs the headunit software on a PC without target hardware.
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
ci/run_boat_sil.sh                BoAt smoke tests of hu-virtual/ (--install: pinned BoAt release)
ci/boat.version                   the BoAt release CI tests against
ci/dut/                           emulated aarch64 DUT for CI: Dockerfile, start script, private bus config
ci/fetch_boat_gateway.py          gets boat_gateway for a BoAt commit from BoAt's CI image (no Docker)
ci/boat_report.py                 BoAt reports as Markdown (CI job summaries)
docs/architecture/HU_architecture_v0.3.md   architecture and decisions D1 to D11
docs/companion-protocol.md        phone (R80 Companion app) <-> HU link protocol (D11)
hu-mockup/                        Qt 6 / QML UI mockup, launched with PySide6
  run.py                          launcher, also renders screenshots headless
  hu-mockup.qmlproject            Qt Design Studio project (open this in Design Studio)
  qml/main.qml                    window, screen switching, knob/key handling
  qml/Theme.qml                   all colours, fonts and sizes
  qml/Sim.qml                     fake vehicle/media/radio/phone/nav data
  qml/Icons.qml                   self-drawn line icons as SVG path data
  qml/*Screen.qml                 one file per screen
  qml/Logo.qml                    the placeholder "R80" brand mark
  fonts/                          B612 and OSP-DIN with their licence files
hu-can/
  r80_test.dbc                    test CAN database (generated, do not hand-edit)
  tools/make_dbc.py               generates r80_test.dbc from one table
  tools/r80_can_sim.py            drive-cycle simulator (candump log or live CAN)
  sample_drive_60s.log            60 s sample drive, candump format
hu-virtual/
  hu-virtual.sh                   up | drive | restbus | panel | ui | test | status | logs | down
  hu/                             target software (runs unchanged on the Pi)
    mcu_link.py                   MCU <-> Linux UART protocol (placeholder)
    dbc.py                        small DBC decoder, no dependencies
    vehicled.py                   vehicle service, publishes D-Bus de.r80.Vehicle
    mediad.py                     media service (GStreamer), D-Bus de.r80.Media
    audiod.py, audio.ini          audio service (volume, mute, D9), D-Bus de.r80.Audio, and its config
    warnd.py, warnings.ini        vehicle warnings (D10), D-Bus de.r80.Warnings, and its rules
    tripd.py, trip.ini            trip computer (D10), D-Bus de.r80.Trip, and its config
    companion_link.py             companion app <-> HU protocol (D11, docs/companion-protocol.md)
    navd.py, nav.ini              navigation service (D11), D-Bus de.r80.Nav, and its timing
    ui/run_hu.py, ui/backend.py   UI launcher and QML backend over D-Bus
    ui/qml/Sim.qml                replaces hu-mockup/qml/Sim.qml at runtime
  mcu_emu/                        MCU emulator and its control client (PC only)
  phone_emu/                      phone emulator: companion app stand-in and demo route (PC only)
  boat/                           BoAt restbus node, tester panel and the 6 BoAt tests (PC only)
hardware/                         hardware designs later; CERN-OHL-P-2.0
```

## 3. How to run and check things

Install Python dependencies once:

```bash
python3 -m pip install PySide6 cantools python-can
```

UI mockup:

```bash
python3 hu-mockup/run.py                           # window, 1280 x 768
python3 hu-mockup/run.py --screenshots /tmp/shots  # render every screen to PNG, then exit
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
cd hu-virtual
./hu-virtual.sh drive   # buses, BoAt gateway, MCU emulator, vehicled, drive cycle
./hu-virtual.sh ui      # UI window on top
./hu-virtual.sh up && ./hu-virtual.sh panel   # tester panel instead of the drive cycle
./hu-virtual.sh up && ./hu-virtual.sh test   # run the 6 BoAt tests
./hu-virtual.sh down
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs on every push to every branch.
It runs the static checks on x86_64 and on aarch64 in Debian 13 (like the Pi bench),
so an x86-only dependency fails CI (section 8).
Its jobs only call scripts in `ci/`, so you can run the same checks locally:

```bash
ci/check_static.sh            # py_compile, repo rules, DBC and simulator drift, screenshots
SKIP_UI=1 ci/check_static.sh  # same without the screenshots
```

CI also runs the 6 BoAt smoke tests with the BoAt release pinned in `ci/boat.version`
(`ci/run_boat_sil.sh --install`). To move to a newer BoAt, change that file and push.
A second job runs them with the DUT (`mcu_emu/`, `hu/vehicled.py`, `hu/mediad.py`, `hu/audiod.py`, `hu/warnd.py`, `hu/tripd.py`, `hu/navd.py`) in a
Debian 13 container per CPU, arm64 (QEMU-emulated, like the Pi) and amd64, while BoAt
stays on the x86 host (`ci/run_boat_sil.sh --install --dut-arch=arm64`; needs docker,
and qemu-user-static for arm64).
The `boat-canary` workflow runs the same tests nightly against BoAt `master` and BoAt's
latest release. It does not block anything. When it fails and the cause is in BoAt,
follow section 7.

There is no unit test suite yet. Before you commit:

1. Run `ci/check_static.sh`, or at least `python3 -m py_compile` on every Python file you changed.
2. If you changed QML, run `run.py --screenshots` and check the images.
3. If you changed `hu-can/tools/make_dbc.py`, regenerate `r80_test.dbc` and commit both.
4. If you changed anything in `hu-virtual/` and you can run BoAt, run `ci/run_boat_sil.sh`
   (or `./hu-virtual.sh test`). If you cannot run it, say so and check the `boat-sil` CI job instead.

## 4. Git rules

- Larger features or changes go on a feature branch named after the work
  (for example `Media_Application`). Small, focused changes may still go directly
  to `master`.
- Do NOT create a branch per commit. Do NOT open pull requests. Alex merges or
  deletes the feature branches himself.
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
  (`/home/testuser/BoAt`). `hu-virtual/` uses it for the restbus and the tests.
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
- Code under `hu-virtual/hu/` is target software. It must not import BoAt,
  `mcu_emu/`, `phone_emu/` or `boat/`.
- The CAN database is a made-up test DBC. Rules for it: classic CAN only (no CAN FD),
  one signal per message, 11-bit standard IDs plus one 29-bit extended ID (`0x18FF0100`).
- Edit the DBC through `hu-can/tools/make_dbc.py`, never by hand.
- The car has three CAN networks: Motor, Infotainment, Comfort. The headunit sits on
  Infotainment; the MCU's second channel listens only (decision D8). The HU must never
  send on Motor or Comfort.
- The MCU link protocol in `hu-virtual/hu/mcu_link.py` is a placeholder. Keep all
  framing in that one file. Do not treat it as final.
- No Android Auto and no CarPlay. Do not add them.
- Navigation: the phone navigates, the HU only displays its guidance (D11). Do not add
  offline routing or a map renderer on the HU without asking Alex. Keep the companion
  link format in `hu/companion_link.py` and `docs/companion-protocol.md`, in step.
- The stock instrument cluster stays (decision D1).
- The architecture decisions D1 to D11 are in `docs/architecture/HU_architecture_v0.3.md`.
  Do not contradict them. If a change needs a different decision, ask Alex first.

## 9. Code conventions

- UI: Qt 6 QML (6.5 or newer), launched with PySide6. Design size is 1280 x 768.
- Put colours, fonts and sizes in `hu-mockup/qml/Theme.qml`. Do not hard-code colours in screens.
- Visual style: black background, monochrome line art in the accent colour (red by default).
  See `hu-mockup/docs/UI_vision_V01.png`.
- `hu-virtual/hu/ui/qml/Sim.qml` must keep the same property names as
  `hu-mockup/qml/Sim.qml`. If you add or rename a property in one, update the other
  and `hu-virtual/hu/ui/backend.py`.
- D-Bus property names in `vehicled.py` are the DBC signal names.
- Python: 3.9+, standard library first, type hints welcome, match the style of the file you edit.
- Keep changes small and focused. Do not reformat files you did not need to change.
- Update the matching README when you change how something is run or what a folder contains.

## 10. When you are unsure

- Do not guess about the real car, the real CAN bus, or hardware choices. Ask Alex.
- Do not delete files, folders or branches unless Alex asked for it.
- Report what you changed, what you checked, and what you could not check.
