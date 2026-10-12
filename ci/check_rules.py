#!/usr/bin/env python3
"""Check the AGENTS.md rules that a script can check. Exit 1 if any rule is broken.

    python3 ci/check_rules.py

- hu-virtual/hu/ (target software) does not import BoAt, mcu_emu/ or boat/   (AGENTS.md 8)
- no OpenStreetMap data is committed                                       (AGENTS.md 6)
- every property, function and signal of hu-mockup/qml/Sim.qml also exists
  in hu-virtual/hu/ui/qml/Sim.qml                                         (AGENTS.md 9)
- no hard-coded colours in QML outside Theme.qml: hex, named ("black") or  (AGENTS.md 9)
  Qt.rgba() with literal numbers; "transparent" is allowed

Standard library only, so it runs before any dependency is installed.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Top-level modules that only exist on the PC: BoAt's SDK/CLI, the MCU emulator, the BoAt nodes.
PC_ONLY_MODULES = {"boat", "boat_cli", "mcu_emu", "mcuctl", "restbus", "restbus_panel"}
PC_ONLY_PATHS = ("mcu_emu", "boat")
OSM_PATTERNS = ("*.osm", "*.osm.pbf", "*.pbf", "*.mbtiles")
SIM_MOCKUP = ROOT / "hu-mockup/qml/Sim.qml"
SIM_VIRTUAL = ROOT / "hu-virtual/hu/ui/qml/Sim.qml"
HEX_COLOUR = re.compile(r"[\"']#[0-9a-fA-F]{3,8}[\"']")
# A quoted word on the right of a colour property (color, fillColor, border.color, ...).
COLOUR_PROP = re.compile(r"\b\w*[cC]olou?r\s*:(.*)")
QUOTED_WORD = re.compile(r"[\"']([A-Za-z]+)[\"']")
LITERAL_RGBA = re.compile(r"Qt\.(rgba|hsla|hsva)\(\s*[\d.]")

errors: list[str] = []


def tracked(*patterns: str) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z", "--", *patterns], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [ROOT / p for p in out.split("\0") if p]


def check_target_imports() -> None:
    for f in tracked("hu-virtual/hu/*.py"):
        rel = f.relative_to(ROOT)
        tree = ast.parse(f.read_text(encoding="utf-8"), str(rel))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for n in names:
                if n.split(".")[0] in PC_ONLY_MODULES:
                    errors.append(f"{rel}:{node.lineno}: target code imports PC-only module '{n}'")
            # sys.path tricks that reach into the PC-only folders
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if any(re.search(rf"(^|[/\\]){p}([/\\]|$)", node.value) for p in PC_ONLY_PATHS):
                    errors.append(f"{rel}:{node.lineno}: target code refers to PC-only path '{node.value}'")


def check_osm() -> None:
    for f in tracked(*OSM_PATTERNS):
        errors.append(f"{f.relative_to(ROOT)}: OpenStreetMap data must not be committed")
    for f in tracked("*"):
        if "tiles" in f.relative_to(ROOT).parts[:-1] and f.suffix.lower() in {".png", ".pbf", ".mvt"}:
            errors.append(f"{f.relative_to(ROOT)}: map tiles must not be committed")


def sim_names(path: Path) -> set[str]:
    text = re.sub(r"//.*", "", path.read_text(encoding="utf-8"))
    names = set(re.findall(r"^\s*(?:readonly\s+)?property\s+[\w<>.]+\s+(\w+)", text, re.M))
    names |= set(re.findall(r"^\s*(?:function|signal)\s+(\w+)", text, re.M))
    return {n for n in names if not n.startswith("_")}


def check_sim_parity() -> None:
    missing = sorted(sim_names(SIM_MOCKUP) - sim_names(SIM_VIRTUAL))
    for n in missing:
        errors.append(f"{SIM_VIRTUAL.relative_to(ROOT)}: missing '{n}' (exists in {SIM_MOCKUP.relative_to(ROOT)})")


def check_qml_colours() -> None:
    for f in tracked("*.qml"):
        if f.name == "Theme.qml":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//")[0]
            prop = COLOUR_PROP.search(code)
            named = [w for w in QUOTED_WORD.findall(prop.group(1)) if w != "transparent"] if prop else []
            if HEX_COLOUR.search(code) or named or LITERAL_RGBA.search(code):
                errors.append(f"{f.relative_to(ROOT)}:{i}: hard-coded colour outside Theme.qml")


def main() -> int:
    for check in (check_target_imports, check_osm, check_sim_parity, check_qml_colours):
        before = len(errors)
        check()
        print(f"  {'ok  ' if len(errors) == before else 'FAIL'} {check.__name__}")
    for e in errors:
        print(f"    {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
