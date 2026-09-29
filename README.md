# Project R80

A headunit (hardware and software) and centre console for a modified
2005 Audi A3 Sportback (8PA, PQ35 platform).

Current state: a clickable UI mockup running on Linux, a made-up test CAN database with
a drive simulator, and the first architecture drafts. Real bus logs, hardware designs
and the production software come later.

## Folders

| Folder | What is in it |
|---|---|
| [`hu-mockup/`](hu-mockup/) | Qt 6 / QML UI mockup (v0.3, runs via PySide6), 1280 x 768, all data simulated. See its README to run it. |
| [`hu-can/`](hu-can/) | Test CAN database (`r80_test.dbc`, classic CAN, 22 messages), generator and drive simulator, sample candump log. |
| [`docs/architecture/`](docs/architecture/) | Headunit architecture (v0.3): vehicle MCU + Linux module, CAN channels, power states. |
| [`hu-virtual/`](hu-virtual/) | Virtual HU test environment: BoAt restbus on vcan, MCU emulator, `vehicled` D-Bus service driving the mockup, BoAt smoke tests. |
| [`hardware/`](hardware/) | Placeholder for hardware designs (PCBs, console). Licensed CERN-OHL-P-2.0. |

## For coding agents

Rules for AI coding agents are in [`AGENTS.md`](AGENTS.md); [`CLAUDE.md`](CLAUDE.md) imports it and adds Claude-specific notes.

## Quick start

```bash
python3 -m pip install PySide6 cantools python-can
python3 hu-mockup/run.py                          # UI mockup in a window
python3 hu-mockup/run.py --screenshots /tmp/shots # render every screen headless
python3 hu-can/tools/r80_can_sim.py --log drive.log
```

## Licences

- **Software** (everything outside `hardware/`): MIT, see [`LICENSE`](LICENSE).
- **Hardware designs** (`hardware/`: schematics, PCB layouts, console CAD):
  CERN Open Hardware Licence v2 Permissive, see [`hardware/LICENSE`](hardware/LICENSE).
- **Fonts** in `hu-mockup/fonts/` keep their own licences (B612: OFL/EPL, OSP-DIN: OFL),
  see the licence files next to them.
- Map data (OpenStreetMap, ODbL) is not stored in this repository.

The brand mark in the UI is a placeholder ("R80"). Swap `hu-mockup/qml/Logo.qml` if you want something else.
