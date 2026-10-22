#!/usr/bin/env python3
"""hu-syslogd: the system's own log (the systemd journal) in the HU's DLT log (decision D14).

The kernel, BlueZ, PipeWire, NetworkManager, the HU's own system units and systemd's failed
units log to the journal, not to DLT. syslogd follows the journal (journalctl -o json), takes
the lines of the sources in syslog.ini, cleans them and writes them as the DLT application OS,
one context per source (KERN, BT, PW, NET, UNIT, SYSD; its own lines: MAIN). So they are in the
same log, the same files, the same export and on the same Diagnostics page as the services'.

Cleaning (the DLT log leaves the car): Bluetooth addresses keep only their last two bytes,
long digit runs become "<number>", lines that name a device or network are left out, quoted
names of a source with mask_quoted become '…'. The same line within repeat_s is written once
and then counted. A source's level (syslog.ini) is its context's level, which DLT Viewer and
Settings -> Diagnostics can change while it runs; lines below it are not even cleaned.

Lines from before syslogd started (the boot, a restart) start with their time since boot
("[+4.2 s] "). The position in the journal is kept in --state, so a restart neither repeats
nor loses lines. --journal-file reads JSON lines from a file instead (the virtual mode and the
tests: the PC's journal is not the HU's). The logic (SystemLog) has no journal and no clock,
so tests can feed it entries with their own time.
"""
from __future__ import annotations

import argparse
import configparser
import fnmatch
import json
import logging
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import dlt

DEFAULT_CONFIG = Path(__file__).resolve().parent / "syslog.ini"
SYSTEM_CONFIG = Path("/etc/r80/syslog.ini")
SAVE_EVERY_S = 5.0                      # the journal position, at most this often
RESTART_S = 5.0                         # journalctl ended: start it again after this long
OLD_S = 2.0                             # a line older than this when read gets its time since boot
LEFT_OUT = "(left out: the line holds a name)"
# journal PRIORITY (syslog: 0 emerg ... 7 debug) -> logging level
PRIORITY = {0: logging.CRITICAL, 1: logging.CRITICAL, 2: logging.CRITICAL, 3: logging.ERROR,
            4: logging.WARNING, 5: logging.INFO, 6: logging.INFO, 7: logging.DEBUG}
# AA:BB:CC:DD:EE:FF, also with _ (BlueZ's dev_AA_BB_...) or -
ADDRESS = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}([:_-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")

log = dlt.context("MAIN", "Journal reader")


class ConfigError(ValueError):
    pass


@dataclass
class Source:
    name: str
    match: list[tuple[str, str]]        # (field, pattern), any one fits
    level: int
    context: str
    description: str
    mask_quoted: bool = False
    logger: logging.Logger = field(default=None, repr=False)

    def fits(self, entry: dict) -> bool:
        return any(isinstance(entry.get(f), str) and fnmatch.fnmatchcase(entry[f], p) for f, p in self.match)


def load_config(extra: str | None = None) -> dict:
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str                                 # journal fields are upper case
    files = [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else [])
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in files if f.is_file()])
    if not cp.has_section("syslog"):
        raise ConfigError("[syslog] is missing")
    for s in cp.sections():
        if s != "syslog" and not s.startswith("source "):
            raise ConfigError(f"unknown section [{s}]")
    unknown = set(cp.options("syslog")) - {"repeat_s", "number_digits", "drop"}
    if unknown:
        raise ConfigError(f"[syslog] unknown key(s): {', '.join(sorted(unknown))}")

    def num(key, lo, hi):
        try:
            v = float(cp.get("syslog", key))
        except (configparser.Error, ValueError) as e:
            raise ConfigError(f"[syslog] {key}: {e}") from None
        if not lo <= v <= hi:
            raise ConfigError(f"[syslog] {key} = {v:g} is outside {lo}..{hi}")
        return v
    drop = []
    for line in cp.get("syslog", "drop", fallback="").splitlines():
        if line.strip():
            try:
                drop.append(re.compile(line.strip()))
            except re.error as e:
                raise ConfigError(f"[syslog] drop: {line.strip()!r}: {e}") from None

    sources, contexts = [], set()
    for s in cp.sections():
        if not s.startswith("source "):
            continue
        sec = cp[s]
        unknown = set(sec) - {"match", "level", "context", "description", "mask_quoted"}
        if unknown:
            raise ConfigError(f"[{s}] unknown key(s): {', '.join(sorted(unknown))}")
        match = []
        for m in sec.get("match", "").split(","):
            f, eq, p = m.strip().partition("=")
            if not eq or not f or not p:
                raise ConfigError(f"[{s}] match: {m.strip()!r} is not FIELD=pattern")
            match.append((f, p))
        level = dlt.NAMES_TO_LOGGING.get(sec.get("level", ""))
        if level is None or sec.get("level") == "off":
            raise ConfigError(f"[{s}] level: {sec.get('level')!r} (fatal, error, warning, info, debug, verbose)")
        ctx = sec.get("context", "")
        if not 1 <= len(ctx) <= 4 or not ctx.isalnum() or ctx == "MAIN" or ctx in contexts:
            raise ConfigError(f"[{s}] context: {ctx!r} (1 to 4 letters or digits, not MAIN, once)")
        contexts.add(ctx)
        try:
            mask = sec.getboolean("mask_quoted", fallback=False)
        except ValueError as e:
            raise ConfigError(f"[{s}] mask_quoted: {e}") from None
        sources.append(Source(s.split(None, 1)[1], match, level, ctx, sec.get("description", ctx), mask))
    if not sources:
        raise ConfigError("no [source ...] section")
    digits = int(num("number_digits", 5, 20))
    return {"repeat_s": num("repeat_s", 0, 3600), "drop": drop, "sources": sources,
            "number": re.compile(r"(?<![\w.])\+?\d(?:[ -]?\d){%d,}(?![\w.])" % (digits - 1))}


def short_address(m: re.Match) -> str:
    parts = re.split(r"[:_-]", m.group(0))
    return dlt.address(":".join(parts).upper())


class SystemLog:
    """Journal entries in, DLT lines out: write(source, level, text) for every line to log."""

    def __init__(self, cfg: dict, write, boot_id: str = ""):
        self.cfg = cfg
        self.write = write
        self.boot_id = boot_id
        self.seen: dict[tuple[str, str], list] = {}     # (context, text) -> [first time, level, repeats, prefix]
        self.latest = (-1e9, -1e9)                      # (the newest entry's time, when it came)

    def clean(self, src: Source, text: str) -> str:
        if any(d.search(text) for d in self.cfg["drop"]):
            return LEFT_OUT
        text = ADDRESS.sub(short_address, text)
        text = self.cfg["number"].sub("<number>", text)
        if src.mask_quoted:
            text = QUOTED.sub(lambda m: m.group(0)[0] + "…" + m.group(0)[0], text)
        return text

    def entry(self, e: dict, now: float):
        """One journal entry (journalctl -o json) at monotonic time now."""
        src = next((s for s in self.cfg["sources"] if s.fits(e)), None)
        if src is None:
            return
        try:
            level = PRIORITY.get(int(e.get("PRIORITY", 6)), logging.INFO)
        except (TypeError, ValueError):
            level = logging.INFO
        if not (src.logger.isEnabledFor(level) if src.logger is not None else level >= src.level):
            return
        text = e.get("MESSAGE", "")
        if isinstance(text, list):                     # not UTF-8: journalctl gives the bytes
            text = bytes(b & 0xFF for b in text if isinstance(b, int)).decode("utf-8", "replace")
        if not isinstance(text, str):
            return
        text = self.clean(src, text.rstrip())
        t = now
        try:
            if e.get("_BOOT_ID", self.boot_id) == self.boot_id:
                t = min(now, int(e["__MONOTONIC_TIMESTAMP"]) / 1e6)
        except (KeyError, TypeError, ValueError):
            pass
        self.latest = (t, now)
        key = (src.context, text)
        seen = self.seen.get(key)
        if seen is not None and t - seen[0] < self.cfg["repeat_s"]:
            seen[2] += 1
            return
        if seen is not None:
            self.repeated(src, key, seen)
        prefix = f"[+{t:.1f} s] " if now - t > OLD_S else ""
        self.seen[key] = [t, level, 0, prefix]
        self.write(src, level, prefix + text)

    def repeated(self, src: Source, key, seen):
        if seen[2]:
            more = "once more" if seen[2] == 1 else f"{seen[2]} more times"
            self.write(src, seen[1], f"{seen[3]}{key[1]} (and {more} in {self.cfg['repeat_s']:g} s)")

    def tick(self, now: float):
        """Every second or so: the repeats whose time is up. While it catches up on older lines
        (they keep coming, older than OLD_S), the time is theirs, not now."""
        t, came = self.latest
        clock = t if now - came < 1.0 and now - t > OLD_S else now
        by_ctx = {s.context: s for s in self.cfg["sources"]}
        for key, seen in list(self.seen.items()):
            if clock - seen[0] >= self.cfg["repeat_s"]:
                self.repeated(by_ctx[key[0]], key, seen)
                del self.seen[key]


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip().replace("-", "")
    except OSError:
        return ""


def run(cfg: dict, state: Path, journal_file: str | None):
    for s in cfg["sources"]:
        s.logger = dlt.context(s.context, s.description, s.level)
    syslog = SystemLog(cfg, lambda s, level, text: s.logger.log(level, text), boot_id())
    cursor, saved = None, None
    try:
        cursor = saved = state.read_text().strip() or None
    except OSError:
        pass

    def save():
        nonlocal saved
        if cursor and cursor != saved:
            try:
                state.parent.mkdir(parents=True, exist_ok=True)
                tmp = state.with_suffix(".new")
                tmp.write_text(cursor + "\n")
                tmp.replace(state)
                saved = cursor
            except OSError as e:
                log.warning(f"could not save the journal position to {state}: {e}")

    def stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)

    if journal_file:
        Path(journal_file).touch()
        log.info(f"reading the journal from {journal_file} (not the system's)")
    else:
        log.info(f"following the journal from {'where it was left' if cursor else 'the start of this boot'}; "
                 f"sources {', '.join(s.context for s in cfg['sources'])}")
    last_save = time.monotonic()
    try:
        while True:
            if journal_file:
                cmd = ["tail", "-n", "+1", "-F", journal_file]
            else:
                cmd = ["journalctl", "-b", "-f", "-o", "json", "-n", "all"] + ([f"--after-cursor={cursor}"] if cursor else [])
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
            except OSError as e:
                log.error(f"cannot start {cmd[0]}: {e}")
                time.sleep(RESTART_S)
                continue
            sel = selectors.DefaultSelector()
            sel.register(proc.stdout, selectors.EVENT_READ)
            buf = b""
            while True:
                ready = sel.select(timeout=1.0)
                now = time.monotonic()
                if ready:
                    data = os.read(proc.stdout.fileno(), 65536)
                    if not data:
                        break
                    *lines, buf = (buf + data).split(b"\n")
                    for line in lines:
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(e, dict):
                            syslog.entry(e, now)
                            if isinstance(e.get("__CURSOR"), str):
                                cursor = e["__CURSOR"]
                syslog.tick(now)
                if not journal_file and now - last_save >= SAVE_EVERY_S:
                    save()
                    last_save = now
            err = proc.stderr.read().decode("utf-8", "replace").strip()
            proc.wait()
            log.error(f"{cmd[0]} ended ({proc.returncode}): {err[:200] or 'no message'}; again in {RESTART_S:g} s")
            time.sleep(RESTART_S)
    finally:
        if not journal_file:
            save()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/syslog.ini and /etc/r80/syslog.ini")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    ap.add_argument("--state", default=str(state_home / "r80" / "syslog.cursor"), help="where the journal position is kept")
    ap.add_argument("--journal-file", help="read journal entries (JSON lines) from this file instead of the journal")
    a = ap.parse_args()
    dlt.app("OS", "System log (journal)", "syslogd")
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[syslogd] bad config: {e}")
    run(cfg, Path(a.state), a.journal_file)


if __name__ == "__main__":
    main()
