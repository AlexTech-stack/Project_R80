#!/usr/bin/env python3
"""Start-up time and memory of the headunit on the bench (architecture §5: UI < 8 s after
power on, audio < 5 s). Run on the Pi with the HU running; prints a Markdown report.

    bench/pi/measure.py                 boot, HU start, memory, CPU over 10 s
    bench/pi/measure.py --cpu-s 30      ... CPU over 30 s
    bench/pi/measure.py --restart       restart the HU first and time that start (warm caches)

Where the numbers come from:
- boot: systemd (`systemd-analyze`, the units' start times), seconds since the kernel started;
- the HU's start: its DLT log (hu/services/dltclient.py): the timestamps count from boot too.
  The daemon's "Daemon launched", each service's first line and its "serving ..." line (on
  D-Bus from then on), the UI's "start-up: ..., first frame" line, mediad's "source ..."
  line (the music is loaded); taken from the last start of the DLT daemon;
- memory: /proc/<pid>/smaps_rollup (PSS: each process's share of shared pages, so the sum is
  what they take together), the system's MemAvailable and swap;
- CPU: /proc/<pid>/stat over --cpu-s seconds.
Standard library only; Linux only (it is a bench tool).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "hu" / "services"))
import dltclient as dc  # noqa: E402

TRACE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "r80" / "dlt" / "trace"
SERVICES = {"VEH": "vehicled", "MED": "mediad", "AUD": "audiod", "WRN": "warnd", "TRP": "tripd",
            "NAV": "navd", "SYS": "sysd", "PHN": "phoned", "HMI": "UI"}
HU_PROCS = [("dlt-daemon", r"^dlt-daemon "), ("mcu_emu", r"mcu_emu\.py"), ("vehicled", r"services/vehicled\.py"),
            ("mediad", r"services/mediad\.py"), ("audiod", r"services/audiod\.py"), ("warnd", r"services/warnd\.py"),
            ("tripd", r"services/tripd\.py"), ("navd", r"services/navd\.py"), ("sysd", r"services/sysd\.py"),
            ("phoned", r"services/phoned\.py"), ("UI", r"hu/ui/run\.py")]


def run(*cmd) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def uptime() -> float:
    return float(Path("/proc/uptime").read_text().split()[0])


def unit_start(unit: str, user: bool = False) -> float | None:
    """When a unit became active, in s since boot (systemd's monotonic clock)."""
    out = run("systemctl", *(["--user"] if user else []), "show", unit, "-p", "ActiveEnterTimestampMonotonic",
              "-p", "ExecMainStartTimestampMonotonic")
    vals = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    for k in ("ExecMainStartTimestampMonotonic", "ActiveEnterTimestampMonotonic"):
        if vals.get(k, "0") not in ("0", ""):
            return int(vals[k]) / 1e6
    return None


# ---- the boot -------------------------------------------------------------------
def boot_report() -> list[str]:
    out = ["## Boot", ""]
    first = run("systemd-analyze").splitlines()
    out += [f"- {first[0].strip()}" if first else "- systemd-analyze: no answer"]
    target = run("systemctl", "get-default").strip()
    out.append(f"- default target: `{target}`")
    rows = [("graphical.target", False), ("multi-user.target", False), ("network-online.target", False),
            ("user@1000.service", False), ("wayvnc.service", False), ("r80-can.service", False),
            ("r80-hu.service", False), ("r80-hu-desktop.service", True)]
    out += ["", "| unit | active after boot |", "|---|---|"]
    for unit, user in rows:
        t = unit_start(unit, user)
        if t is not None:
            out.append(f"| {unit} | {t:.1f} s |")
    blame = run("systemd-analyze", "blame").splitlines()[:8]
    if blame:
        out += ["", "Slowest units (`systemd-analyze blame`):", "", "```"] + [b.strip() for b in blame] + ["```"]
    return out


# ---- the HU's start, from its DLT log -------------------------------------------
def dlt_messages() -> list:
    files = sorted(TRACE.glob("*.dlt"), key=lambda f: f.stat().st_mtime)
    msgs = []
    for f in files:
        msgs += dc.read_file(f)
    starts = [i for i, m in enumerate(msgs) if m.apid == "DLTD" and "Daemon launched" in m.text]
    return msgs[starts[-1]:] if starts else msgs


def hu_report() -> list[str]:
    msgs = dlt_messages()
    out = ["## Headunit start (DLT log, s since boot)", ""]
    if not msgs:
        return out + [f"No DLT files in {TRACE}."]
    t0 = msgs[0].timestamp
    out.append(f"- DLT daemon launched: {t0:.2f} s")
    out += ["", "| service | first line | ready (serving on D-Bus) |", "|---|---|---|"]
    for apid, name in SERVICES.items():
        own = [m for m in msgs if m.apid == apid and m.kind == dc.TYPE_LOG]
        first = own[0].timestamp if own else None
        ready = next((m.timestamp for m in own if m.text.startswith("serving ") or m.text.startswith("start-up:")), None)
        def s(v):
            return "-" if v is None else f"{v:.2f} s"
        out.append(f"| {name} | {s(first)} | {s(ready)} |")
    ui = next((m for m in msgs if m.apid == "HMI" and m.text.startswith("start-up:")), None)
    music = next((m for m in msgs if m.apid == "MED" and m.text.startswith("source ")), None)
    out.append("")
    if ui:
        out.append(f"- UI: {ui.text} → first frame at **{ui.timestamp:.2f} s** since boot")
    else:
        out.append("- UI: no start-up line yet (an older UI, or no first frame)")
    if music:
        out.append(f"- music loaded (mediad's source line) at {music.timestamp:.2f} s")
    return out


# ---- memory and CPU ---------------------------------------------------------------
def processes() -> list[tuple[int, str]]:
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            continue
        if cmd:
            out.append((int(d.name), cmd))
    return out


def smaps(pid: int) -> dict:
    vals = {}
    try:
        for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
            m = re.match(r"(\w+):\s+(\d+) kB", line)
            if m:
                vals[m[1]] = int(m[2])
    except OSError:
        pass
    return vals


def ticks(pid: int) -> int:
    try:
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(f[11]) + int(f[12])
    except (OSError, IndexError, ValueError):
        return 0


def meminfo() -> dict:
    return {k: int(v.split()[0]) for k, v in (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())}


def memory_cpu_report(cpu_s: float) -> list[str]:
    procs = processes()
    hu = []
    for name, pattern in HU_PROCS:
        for pid, cmd in procs:
            if re.search(pattern, cmd) and "measure.py" not in cmd:
                hu.append((name, pid))
                break
    hu_pids = {pid for _, pid in hu}
    before = {pid: ticks(pid) for pid, _ in procs}
    busy0 = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
    time.sleep(cpu_s)
    busy1 = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
    hz = os.sysconf("SC_CLK_TCK")

    def cpu(pid):
        return (ticks(pid) - before.get(pid, 0)) / hz / cpu_s * 100

    out = ["## Memory and CPU", "",
           f"CPU over {cpu_s:g} s; 100 % = one core of {os.cpu_count()}. PSS and swap in MB.", "",
           "| process | PSS | RSS | swap | CPU |", "|---|---|---|---|---|"]
    total = [0, 0, 0]
    for name, pid in hu:
        s = smaps(pid)
        total[0] += s.get("Pss", 0)
        total[1] += s.get("Swap", 0)
        total[2] += cpu(pid)
        out.append(f"| {name} | {s.get('Pss', 0) / 1024:.1f} | {s.get('Rss', 0) / 1024:.1f} | "
                   f"{s.get('Swap', 0) / 1024:.1f} | {cpu(pid):.1f} % |")
    out.append(f"| **headunit together** | **{total[0] / 1024:.1f}** | | **{total[1] / 1024:.1f}** | **{total[2]:.1f} %** |")
    missing = [n for n, _ in HU_PROCS if n not in dict(hu)]
    if missing:
        out.append(f"\nNot running: {', '.join(missing)}.")
    others = sorted(((smaps(pid).get("Pss", 0), pid, cmd) for pid, cmd in procs if pid not in hu_pids), reverse=True)[:8]
    out += ["", "Largest other processes (the desktop, PipeWire, ...):", "", "| process | PSS |", "|---|---|"]
    for pss, pid, cmd in others:
        out.append(f"| `{cmd.split()[0].rsplit('/', 1)[-1]}` ({pid}) | {pss / 1024:.1f} |")
    mi = meminfo()
    d = [b - a for a, b in zip(busy0, busy1)]
    idle = (d[3] + d[4]) / max(1, sum(d)) * 100
    out += ["", f"- system: {mi['MemTotal'] // 1024} MB, available {mi['MemAvailable'] // 1024} MB, "
            f"swap used {(mi['SwapTotal'] - mi['SwapFree']) // 1024} MB of {mi['SwapTotal'] // 1024} MB",
            f"- all CPUs idle {idle:.0f} % over {cpu_s:g} s; load {Path('/proc/loadavg').read_text().split()[0]}"]
    return out


def restart_hu():
    user = (Path.home() / ".config/systemd/user/r80-hu-desktop.service").is_file()
    cmd = ["systemctl", "--user", "restart", "r80-hu-desktop"] if user else ["sudo", "systemctl", "restart", "r80-hu"]
    subprocess.run(cmd, check=True)
    t0 = uptime()
    for _ in range(120):                         # until the UI says it drew its first frame
        time.sleep(0.5)
        ui = next((m for m in dlt_messages() if m.apid == "HMI" and m.text.startswith("start-up:")), None)
        if ui and ui.timestamp > t0 - 1:
            break
    time.sleep(5)                                # let the services settle before memory and CPU
    return t0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpu-s", type=float, default=10.0, help="how long to sample the CPU (default 10 s)")
    ap.add_argument("--restart", action="store_true", help="restart the HU first and time that start")
    a = ap.parse_args()
    lines = [f"# R80 bench: start-up and memory, {time.strftime('%Y-%m-%d %H:%M')}", "",
             f"{Path('/proc/device-tree/model').read_text().strip(chr(0)) if Path('/proc/device-tree/model').exists() else os.uname().machine}, "
             f"up {uptime() / 60:.0f} min", ""]
    if a.restart:
        t0 = restart_hu()
        lines += [f"HU restarted at {t0:.2f} s since boot (warm: files in the page cache).", ""]
    else:
        lines += boot_report() + [""]
    lines += hu_report() + [""] + memory_cpu_report(a.cpu_s)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
