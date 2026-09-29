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
docs/architecture/HU_architecture_v0.3.md   architecture and decisions D1 to D8
hu-mockup/                        Qt 6 / QML UI mockup, launched with PySide6
  run.py                          launcher, also renders screenshots headless
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
  hu-virtual.sh                   up | drive | restbus | ui | test | status | logs | down
  hu/                             target software (runs unchanged on the Pi)
    mcu_link.py                   MCU <-> Linux UART protocol (placeholder)
    dbc.py                        small DBC decoder, no dependencies
    vehicled.py                   vehicle service, publishes D-Bus de.r80.Vehicle
    ui/run_hu.py, ui/backend.py   UI launcher and QML backend over D-Bus
    ui/qml/Sim.qml                replaces hu-mockup/qml/Sim.qml at runtime
  mcu_emu/                        MCU emulator and its control client (PC only)
  boat/                           BoAt restbus node and the 6 BoAt tests (PC only)
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
  `sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1`.

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
./hu-virtual.sh up && ./hu-virtual.sh test   # run the 6 BoAt tests
./hu-virtual.sh down
```

There is no CI and no unit test suite yet. Before you commit:

1. Run `python3 -m py_compile` on every Python file you changed.
2. If you changed QML, run `run.py --screenshots` and check the images.
3. If you changed `hu-can/tools/make_dbc.py`, regenerate `r80_test.dbc` and commit both.
4. If you changed anything in `hu-virtual/` and you can run BoAt, run `./hu-virtual.sh test`.
   If you cannot run it, say so in your report.

## 4. Git rules

- Commit and push directly to `master`.
- Do NOT create feature branches. Do NOT open pull requests. Do NOT create a branch per commit.
  (This holds while the project is starting. Alex will say when it changes.)
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
- NEVER change, patch or "fix" anything in BoAt. Not even a one-line fix.
- NEVER work around a BoAt bug silently in this repo.
- When you find a BoAt issue, add an entry to `~/BoAt/test/foundIssues.md` with:
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
  `mcu_emu/` or `boat/`.
- The CAN database is a made-up test DBC. Rules for it: classic CAN only (no CAN FD),
  one signal per message, 11-bit standard IDs plus one 29-bit extended ID (`0x18FF0100`).
- Edit the DBC through `hu-can/tools/make_dbc.py`, never by hand.
- The car has three CAN networks: Motor, Infotainment, Comfort. The headunit sits on
  Infotainment; the MCU's second channel listens only (decision D8). The HU must never
  send on Motor or Comfort.
- The MCU link protocol in `hu-virtual/hu/mcu_link.py` is a placeholder. Keep all
  framing in that one file. Do not treat it as final.
- No Android Auto and no CarPlay. Do not add them.
- The stock instrument cluster stays (decision D1).
- The architecture decisions D1 to D8 are in `docs/architecture/HU_architecture_v0.3.md`.
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
