"""What Settings -> System -> Diagnostics shows: the warnings and errors of the DLT log.

hu-sysd feeds it every message it reads from the HU's DLT daemon (hu/services/dltclient.py);
no D-Bus here, so tests can use it.

    d = Diagnostics(["HMI", "VEH", ...], keep=50)
    d.message(m)          # a dltclient.Message; True if what the page shows changed
    d.apps()              # [{"id", "description", "level", "running", "errors", "warnings"}] in that order
    d.entries             # the newest first: {"time", "app", "context", "level", "text"}, at most keep
    d.clear()             # counters and list back to zero (the files keep everything)

Errors are fatal and error messages, warnings the warning ones, counted since sysd started
(the daemon also hands over what it buffered before). Levels: "default" (the daemon's
ContextLogLevel: info), "off", "fatal", ... "verbose"; an application whose contexts differ
shows its MAIN context's level.
"""
from __future__ import annotations

import time
from collections import deque

import dltclient as dc

DAEMON = "DLTD"          # the daemon's own messages (buffer overflow, clients); DA1: control responses


def level_name(level: int) -> str:
    return dc.LEVELS[level] if 0 <= level < len(dc.LEVELS) else "default"


class Diagnostics:
    def __init__(self, order: list[str], keep: int = 50):
        self.order = list(order)
        self.keep = keep
        self.entries: deque = deque(maxlen=keep)
        self.known: dict[str, dict] = {}            # apid -> {"description", "level", "running"}
        self.counts: dict[str, list[int]] = {}      # apid -> [errors, warnings]

    def _app(self, apid: str) -> dict:
        if apid not in self.known:
            self.known[apid] = {"description": "", "level": -1, "running": False}
        return self.known[apid]

    def message(self, m: dc.Message, now: float | None = None) -> bool:
        if m.kind == dc.TYPE_CONTROL:
            if m.service == dc.GET_LOG_INFO and m.subtype == dc.CONTROL_RESPONSE and m.status in (6, 7):
                return self.log_info(dc.log_info(m.data, m.big_endian))
            return False
        if m.kind != dc.TYPE_LOG:
            return False
        if m.apid == DAEMON:
            return self.daemon_note(m.text)
        if not 1 <= m.level <= 3:
            return False
        c = self.counts.setdefault(m.apid, [0, 0])
        c[0 if m.level <= 2 else 1] += 1
        self._app(m.apid)["running"] = True
        self.entries.appendleft({"time": now if now is not None else (m.time if m.time > 0 else time.time()),
                                 "app": m.apid, "context": m.ctid, "level": dc.LEVELS[m.level], "text": m.text})
        return True

    def daemon_note(self, text: str) -> bool:
        """The daemon says when an application comes and goes."""
        for word, running in (("registered for PID", True), ("Unregistered ApID", False)):
            if word in text and "'" in text:
                apid = text.split("'")[1]
                if apid and self._app(apid)["running"] != running:
                    self.known[apid]["running"] = running
                    return True
        return False

    def log_info(self, info: dict) -> bool:
        changed = False
        for apid, a in info.items():
            ctxs = a["contexts"]
            level = ctxs["MAIN"]["level"] if "MAIN" in ctxs else next((c["level"] for c in ctxs.values()), -1)
            description = (a["description"] or ctxs.get("MAIN", {}).get("description")   # libdlt 3.0 sends no app description
                           or self._app(apid)["description"])
            new = {"description": description, "level": level, "running": True}
            if self._app(apid) != new:
                self.known[apid] = new
                changed = True
        return changed

    def clear(self):
        self.entries.clear()
        self.counts.clear()

    def apps(self) -> list[dict]:
        ids = [a for a in self.order] + sorted(a for a in self.known if a not in self.order)
        out = []
        for apid in ids:
            k = self.known.get(apid, {"description": "", "level": -1, "running": False})
            e, w = self.counts.get(apid, [0, 0])
            out.append({"id": apid, "description": k["description"] or apid, "level": level_name(k["level"]),
                        "running": k["running"], "errors": e, "warnings": w})
        return out
