#!/usr/bin/env python3
"""R80 phone panel: a tester GUI that plays the driver's phone (R80 Companion app) towards
hu-navd, without a real phone, Google Maps or fake GPS (PC only).

  * connect to navd's local socket or over TCP (tcp:HOST:PORT, navd --tcp, e.g. the Pi bench),
    disconnect cleanly (bye), drop the link without a word, or go silent (no heartbeats)
    to provoke a link loss,
  * play a route (phone_emu/*.json) at a set speed or at the HU's vehicle speed, pause,
    jump to any point,
  * send any guidance by hand: every maneuver, direction and roundabout exit, distance,
    street, text, remaining distance and time; presets for edge cases (rerouting, long
    signpost, unknown arrow, arrival, ...); guidance ended; raw lines, also broken ones,
  * see everything sent and received.

    python3 phone_emu/phone_panel.py                       # navd of the virtual HU
    python3 phone_emu/phone_panel.py --target tcp:200.200.0.102:47800
    dev/hu-virtual.sh phonepanel                           # same as the first, with the env's socket

One phone at a time: connecting replaces a phone that is connected to navd (also a real one).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton, QSlider, QSpinBox, QSplitter, QVBoxLayout,
    QWidget,
)

from phone_emu import DEFAULT_SOCKET, Phone, RoutePlayer, cl, vehicle_speed  # noqa: E402

# name -> fields of the manual form; edge cases a real drive rarely gives on demand
PRESETS = {
    "Turn right, 350 m": dict(maneuver="turn", modifier="right", distance=350, street="Hauptstraße"),
    "Roundabout, exit to the left": dict(maneuver="roundabout", modifier="left", distance=170, street="Hunklinge"),
    "Roundabout, 3rd exit": dict(maneuver="roundabout", exit=3, distance=120, street="B27"),
    "Motorway exit right": dict(maneuver="off_ramp", modifier="slight_right", distance=1200,
                                street="Ausfahrt 4 / KA-Beiertheim / Stadion / ZKM / Europahalle"),
    "Fork, keep left": dict(maneuver="fork", modifier="slight_left", distance=2300, street="Durlacher Allee"),
    "U-turn": dict(maneuver="uturn", distance=10, street="Richtung Hunklinge"),
    "Long signpost text": dict(maneuver="turn", modifier="right", distance=80,
                               street="Pragstraße Richtung A8 A81 B10 B27 Karlsruhe / Heilbronn / Vaihingen/Enz / "
                                      "Ludwigsburg / S-Zentrum / S-Feuerbach"),
    "Unknown arrow (not in the app's table)": dict(maneuver="unknown", distance=200, street="Musterstraße"),
    "Rerouting (no arrow, no distance)": dict(maneuver="unknown", distance=-1, street="",
                                              text="Route wird neu berechnet…"),
    "Destination on the left": dict(maneuver="arrive", modifier="left", distance=0, street="Schlossweg 8"),
    "No remaining time/distance": dict(maneuver="continue", modifier="straight", distance=1500,
                                       street="Ludwigsburger Str.", remaining_m=-1, remaining_s=-1),
}


class Panel(QMainWindow):
    def __init__(self, target: str):
        super().__init__()
        self.setWindowTitle("R80 phone panel")
        self.phone: Phone | None = None
        self.seen = 0                      # received messages already logged
        self.player: RoutePlayer | None = None
        self.playing = False
        self.last_sent = None
        self.last_tick = time.monotonic()

        left = QVBoxLayout()
        left.addWidget(self._connection(target))
        left.addWidget(self._route())
        left.addWidget(self._manual())
        left.addStretch(1)
        lw = QWidget(); lw.setLayout(left); lw.setMinimumWidth(460)

        self.log = QPlainTextEdit(readOnly=True)
        self.log.setFont(QFont("Monospace", 9))
        self.log.setMaximumBlockCount(2000)
        split = QSplitter(); split.addWidget(lw); split.addWidget(self.log)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        self.resize(1200, 760)

        self.timer = QTimer(self, interval=250, timeout=self.tick)
        self.timer.start()
        self.load_route(self.route_box.currentText())
        self.show_state()

    # ---- building the window ---------------------------------------------------
    def _connection(self, target):
        g = QGroupBox("Link to the headunit")
        f = QFormLayout(g)
        self.target = QLineEdit(target)
        self.target.setToolTip("navd's local socket, or tcp:HOST:PORT for navd --tcp (e.g. the Pi bench)")
        self.device = QLineEdit("Phone panel")
        f.addRow("HU", self.target)
        f.addRow("Device", self.device)
        row = QHBoxLayout()
        for text, slot in (("Connect", self.connect_hu), ("Disconnect (bye)", self.disconnect_hu),
                           ("Drop (no bye)", self.drop_hu)):
            b = QPushButton(text); b.clicked.connect(slot); row.addWidget(b)
        f.addRow(row)
        self.silent = QCheckBox("Go silent: no heartbeats (navd drops the link after link_timeout_s)")
        self.silent.toggled.connect(self.set_silent)
        f.addRow(self.silent)
        self.state = QLabel(); self.state.setWordWrap(True)
        f.addRow("State", self.state)
        return g

    def _route(self):
        g = QGroupBox("Route (as the navigation app would show it)")
        grid = QGridLayout(g)
        self.route_box = QComboBox()
        self.route_box.addItems(sorted(p.name for p in HERE.glob("*.json")))
        self.route_box.currentTextChanged.connect(self.load_route)
        self.speed = QSpinBox(minimum=0, maximum=250, value=50, suffix=" km/h")
        self.follow = QCheckBox("HU's vehicle speed")
        self.follow.setToolTip("VehicleSpeed from hu-vehicled (drive cycle or tester panel); else the speed set here")
        self.play_btn = QPushButton("Play"); self.play_btn.clicked.connect(self.toggle_play)
        restart = QPushButton("Restart"); restart.clicked.connect(lambda: self.seek(0))
        self.pos = QSlider(Qt.Horizontal); self.pos.sliderMoved.connect(self.seek)
        self.where = QLabel(); self.where.setWordWrap(True)
        grid.addWidget(QLabel("File"), 0, 0); grid.addWidget(self.route_box, 0, 1, 1, 3)
        grid.addWidget(QLabel("Speed"), 1, 0); grid.addWidget(self.speed, 1, 1); grid.addWidget(self.follow, 1, 2, 1, 2)
        grid.addWidget(self.play_btn, 2, 0); grid.addWidget(restart, 2, 1); grid.addWidget(self.pos, 2, 2, 1, 2)
        grid.addWidget(self.where, 3, 0, 1, 4)
        return g

    def _manual(self):
        g = QGroupBox("Send by hand (pauses the route)")
        f = QFormLayout(g)
        self.preset = QComboBox(); self.preset.addItem("— preset —"); self.preset.addItems(PRESETS)
        self.preset.activated.connect(self.apply_preset)
        self.source = QComboBox(); self.source.addItems(["google_maps", "osmand"])
        self.maneuver = QComboBox(); self.maneuver.addItems(cl.MANEUVERS)
        self.modifier = QComboBox(); self.modifier.addItems(["(none)", *cl.MODIFIERS])
        self.exit = QSpinBox(minimum=0, maximum=99, specialValueText="(none)")
        self.distance = QDoubleSpinBox(minimum=-1, maximum=999999, decimals=0, value=350,
                                       specialValueText="(none)", suffix=" m")
        self.street = QLineEdit("Hauptstraße")
        self.text = QLineEdit(); self.text.setPlaceholderText("the app's own instruction text (optional)")
        self.rem_m = QDoubleSpinBox(minimum=-1, maximum=9999999, decimals=0, value=8300,
                                    specialValueText="(none)", suffix=" m")
        self.rem_s = QDoubleSpinBox(minimum=-1, maximum=999999, decimals=0, value=720,
                                    specialValueText="(none)", suffix=" s")
        f.addRow("Preset", self.preset)
        f.addRow("Source", self.source)
        f.addRow("Maneuver", self.maneuver)
        f.addRow("Direction", self.modifier)
        f.addRow("Exit", self.exit)
        f.addRow("Distance", self.distance)
        f.addRow("Street", self.street)
        f.addRow("Text", self.text)
        f.addRow("Remaining", self._row(self.rem_m, self.rem_s))
        send = QPushButton("Send guidance"); send.clicked.connect(self.send_manual)
        ended = QPushButton("Guidance ended"); ended.clicked.connect(lambda: self.send(cl.guidance_ended(), pause=True))
        f.addRow(self._row(send, ended))
        self.raw = QLineEdit('{"type":"guidance","active":true}')
        self.raw.setToolTip("sent exactly as typed plus a newline: broken JSON, unknown types, ...")
        raw_btn = QPushButton("Send raw line"); raw_btn.clicked.connect(self.send_raw)
        f.addRow("Raw", self._row(self.raw, raw_btn))
        return g

    @staticmethod
    def _row(*widgets):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            h.addWidget(x)
        return w

    # ---- link -------------------------------------------------------------------
    def connected(self) -> bool:
        return self.phone is not None and not self.phone.closed_by_hu.is_set()

    def connect_hu(self):
        self.drop_hu(quiet=True)
        self.phone = Phone(self.target.text().strip(), device=self.device.text().strip() or "Phone panel")
        self.seen = 0
        try:
            hu = self.phone.connect(timeout=3.0)
        except OSError as e:
            self.note(f"cannot connect to {self.target.text()}: {e}")
            self.phone = None
            self.show_state()
            return
        self.phone.heartbeats = not self.silent.isChecked()
        self.note(f"connected to {self.target.text()}" if hu else "connected, but no hello from the HU")
        self.last_sent = None
        self.show_state()

    def disconnect_hu(self):
        if self.phone:
            self.phone.close(bye=True)
            self.note("→ bye, closed")
            self.phone = None
        self.show_state()

    def drop_hu(self, quiet=False):
        if self.phone:
            self.phone.close()
            if not quiet:
                self.note("link dropped without bye")
            self.phone = None
        self.show_state()

    def set_silent(self, on):
        if self.phone:
            self.phone.heartbeats = not on
        self.note("silent: no more heartbeats" if on else "heartbeats again")

    def send(self, msg: dict, pause=False):
        if pause and self.playing:
            self.toggle_play()
        if not self.connected():
            self.note("not connected")
            return
        try:
            self.phone.send(msg)
            self.note("→ " + cl.encode(msg).decode().strip())      # as it goes out on the wire
        except (OSError, cl.ProtocolError) as e:
            self.note(f"send failed: {e}")

    def send_raw(self):
        if not self.connected():
            self.note("not connected")
            return
        try:
            self.phone.send_raw(self.raw.text().encode() + b"\n")
            self.note("→ raw " + self.raw.text())
        except OSError as e:
            self.note(f"send failed: {e}")

    # ---- manual guidance --------------------------------------------------------
    def apply_preset(self, index):
        p = PRESETS.get(self.preset.itemText(index))
        if not p:
            return
        self.maneuver.setCurrentText(p["maneuver"])
        self.modifier.setCurrentText(p.get("modifier") or "(none)")
        self.exit.setValue(p.get("exit", 0))
        self.distance.setValue(p.get("distance", -1))
        self.street.setText(p.get("street", ""))
        self.text.setText(p.get("text", ""))
        self.rem_m.setValue(p.get("remaining_m", 8300))
        self.rem_s.setValue(p.get("remaining_s", 720))

    def send_manual(self):
        opt = lambda v: None if v < 0 else v  # noqa: E731
        mod = self.modifier.currentText()
        msg = cl.guidance(self.source.currentText(), self.maneuver.currentText(),
                          None if mod == "(none)" else mod, self.exit.value() or None,
                          distance_m=opt(self.distance.value()), street=self.street.text() or None,
                          text=self.text.text() or None, remaining_m=opt(self.rem_m.value()),
                          remaining_s=opt(self.rem_s.value()))
        self.send(msg, pause=True)

    # ---- route ------------------------------------------------------------------
    def load_route(self, name):
        if not name:
            return
        self.player = RoutePlayer(json.loads((HERE / name).read_text()))
        self.pos.setRange(0, int(self.player.total))
        self.seek(0)

    def toggle_play(self):
        self.playing = not self.playing
        self.play_btn.setText("Pause" if self.playing else "Play")
        self.last_tick = time.monotonic()
        self.last_sent = None

    def seek(self, metres):
        if self.player:
            self.player.driven = float(metres)
            self.pos.setValue(int(metres))
            self.last_sent = None
            self.show_route()

    def show_route(self):
        p = self.player
        g = p.guidance()
        m = g["maneuver"]
        what = " ".join(str(x) for x in (m["type"], m.get("modifier") or "", f"exit {m['exit']}" if m.get("exit") else "") if x)
        self.where.setText(f"{p.driven / 1000:.2f} / {p.total / 1000:.2f} km · leg {p.leg_index() + 1}/{len(p.legs)}: "
                           f"{what} in {g['distance_m']:.0f} m → {g['street']}")

    # ---- the clock ----------------------------------------------------------------
    def tick(self):
        now = time.monotonic()
        dt, self.last_tick = now - self.last_tick, now
        if self.playing and self.player:
            kmh = vehicle_speed() if self.follow.isChecked() else None
            self.player.advance((self.speed.value() if kmh is None else kmh) / 3.6 * dt)
            self.pos.setValue(int(self.player.driven))
            self.show_route()
            if self.connected():
                msg = self.player.guidance()
                if msg != self.last_sent:
                    self.send(msg)
                    self.last_sent = msg
            if self.player.arrived:
                self.toggle_play()
                self.note("route arrived (send 'Guidance ended' to clear the HU)")
        if self.phone:
            new = self.phone.received[self.seen:]
            self.seen += len(new)
            for m in new:
                if m["type"] != cl.HEARTBEAT:
                    self.note("← " + json.dumps({k: v for k, v in m.items() if v is not None}, ensure_ascii=False))
            if self.phone.closed_by_hu.is_set():
                self.note("the HU closed the link")
                self.phone.close()
                self.phone = None
        self.show_state()

    def show_state(self):
        if not self.phone:
            self.state.setText("not connected")
            return
        hello = next((m for m in self.phone.received if m["type"] == cl.HELLO), None)
        hb = sum(1 for m in self.phone.received if m["type"] == cl.HEARTBEAT)
        self.state.setText(f"connected to {hello['app']} {hello['version']}, heartbeat every {hello['heartbeat_s']} s, "
                           f"{hb} heartbeats received" + (" · SILENT" if self.silent.isChecked() else "")
                           if hello else "connected, waiting for the HU's hello")

    def note(self, text):
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    def closeEvent(self, e):
        self.drop_hu(quiet=True)
        super().closeEvent(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default=str(DEFAULT_SOCKET), help="navd's local socket, or tcp:HOST:PORT")
    ap.add_argument("--screenshot", metavar="PNG", help="render the window once and quit (docs, checks)")
    a = ap.parse_args()
    app = QApplication(sys.argv[:1])
    w = Panel(a.target)
    w.show()
    if a.screenshot:
        QTimer.singleShot(800, lambda: (w.grab().save(a.screenshot), app.quit()))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
