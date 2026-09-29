#!/usr/bin/env python3
"""R80 restbus panel: a tester GUI for the headunit's inputs.

The panel *is* the restbus: it sends every message of hu-can/r80_test.dbc
through the BoAt gateway at its cycle time (same engine as boat/restbus.py),
and lets a tester

  * change any signal value live (sliders / spin boxes, enums as drop-downs),
  * switch single messages off (missing sender) or the whole bus (bus sleep),
  * hand the values to the 60 s drive cycle and take them back,
  * operate the HU controls that are wired to the MCU: knob, push, tilt,
    hard keys and the dimming override (through the MCU emulator).

    python3 boat/restbus_panel.py --address localhost:50061
    ./hu-virtual.sh panel           # same, with the env's gateway address

Don't run it next to `hu-virtual.sh drive|restbus`: two restbus nodes would
send the same IDs.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "mcu_emu"))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QPushButton, QSlider, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from hu.dbc import Database  # noqa: E402
from mcuctl import call as mcu_call  # noqa: E402
from restbus import DBC, DEFAULTS, DriveCycle, Restbus  # noqa: E402

COLS = ["Send", "Message", "ID", "Cycle", "Signal", "Value", "Unit", "Payload"]
C_SEND, C_MSG, C_ID, C_CYCLE, C_SIG, C_VAL, C_UNIT, C_PAYLOAD = range(len(COLS))


class ValueEditor(QWidget):
    """Enum -> combo box; numeric -> slider + spin box on the signal's own raw grid."""

    def __init__(self, sig, on_change):
        super().__init__()
        self.sig = sig
        self.on_change = on_change
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        self.combo = self.spin = self.slider = None
        if sig.choices:
            self.combo = QComboBox()
            for raw, name in sorted(sig.choices.items()):
                self.combo.addItem(f"{name}  ({raw})", name)
            self.combo.currentIndexChanged.connect(lambda _i: self.on_change(self.value()))
            lay.addWidget(self.combo)
            return
        lo, hi = self.limits()
        decimals = max(0, len(f"{sig.factor:g}".split(".")[1]) if "." in f"{sig.factor:g}" else 0)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(sig.factor)
        self.spin.setMinimumWidth(110)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, round((hi - lo) / sig.factor))
        self.slider.setMinimumWidth(160)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)

    def limits(self):
        s = self.sig
        lo, hi = min(s.minimum, s.maximum), max(s.minimum, s.maximum)
        if lo == hi:  # DBC without a range: use what the raw bits can hold
            raw_lo = -(1 << (s.length - 1)) if s.signed else 0
            raw_hi = (1 << (s.length - 1)) - 1 if s.signed else (1 << s.length) - 1
            lo, hi = sorted((raw_lo * s.factor + s.offset, raw_hi * s.factor + s.offset))
        return lo, hi

    def _from_slider(self, v):
        lo, _ = self.limits()
        self.spin.blockSignals(True)
        self.spin.setValue(lo + v * self.sig.factor)
        self.spin.blockSignals(False)
        self.on_change(self.value())

    def _from_spin(self, v):
        lo, _ = self.limits()
        self.slider.blockSignals(True)
        self.slider.setValue(round((v - lo) / self.sig.factor))
        self.slider.blockSignals(False)
        self.on_change(self.value())

    def value(self):
        return self.combo.currentData() if self.combo else self.spin.value()

    def show_value(self, v):
        """Display v without reporting it back as a tester change."""
        for w in (self.combo, self.spin, self.slider):
            if w:
                w.blockSignals(True)
        if self.combo:
            i = self.combo.findData(v)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        else:
            lo, _ = self.limits()
            self.spin.setValue(float(v))
            self.slider.setValue(round((float(v) - lo) / self.sig.factor))
        for w in (self.combo, self.spin, self.slider):
            if w:
                w.blockSignals(False)


class Panel(QMainWindow):
    def __init__(self, rb: Restbus, db: Database, address: str):
        super().__init__()
        self.rb, self.db = rb, db
        self.drive = None
        self.driven = set(DriveCycle()(0.0))
        self.setWindowTitle(f"R80 restbus panel  -  BoAt gateway {address}")
        self.resize(1320, 820)

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.addLayout(self._toolbar())
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._table())
        split.addWidget(self._hu_controls())
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        v.addWidget(split, 1)

        self.status = QLabel()
        self.statusBar().addPermanentWidget(self.status, 1)
        self.timer = QTimer(self, interval=200, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    # ---- layout ------------------------------------------------------------
    def _toolbar(self):
        h = QHBoxLayout()
        self.filter = QLineEdit(placeholderText="Filter messages / signals / IDs…")
        self.filter.textChanged.connect(self.apply_filter)
        self.btn_drive = QPushButton("Drive cycle", checkable=True)
        self.btn_drive.setToolTip("Hand speed, rpm, gear, odometer, fuel, … to the 60 s drive cycle")
        self.btn_drive.toggled.connect(self.set_drive)
        self.btn_sleep = QPushButton("Bus sleep", checkable=True)
        self.btn_sleep.setToolTip("Stop all messages: the MCU sees the bus go to sleep and shuts the HU down")
        self.btn_sleep.toggled.connect(self.set_sleep)
        btn_all = QPushButton("All messages on")
        btn_all.clicked.connect(lambda: self.set_all(True))
        btn_reset = QPushButton("Reset values")
        btn_reset.clicked.connect(self.reset_values)
        h.addWidget(self.filter, 1)
        for b in (self.btn_drive, self.btn_sleep, btn_all, btn_reset):
            h.addWidget(b)
        return h

    def _table(self):
        rows = [(m, s) for m in self.db.messages for s in m.signals]
        t = self.table = QTableWidget(len(rows), len(COLS))
        t.setHorizontalHeaderLabels(COLS)
        t.verticalHeader().setVisible(False)
        t.setSelectionMode(QTableWidget.NoSelection)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.Monospace)
        self.rows = []
        for r, (m, s) in enumerate(rows):
            rm = self.rb.by_name[m.name]
            send = QCheckBox()
            send.setChecked(rm.enabled)
            send.toggled.connect(lambda on, n=m.name: self.set_message(n, on))
            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(8, 0, 0, 0)
            cl.addWidget(send)
            t.setCellWidget(r, C_SEND, cell)
            ident = f"0x{m.frame_id:08X} ext" if m.extended else f"0x{m.frame_id:03X}"
            for c, text in ((C_MSG, m.name), (C_ID, ident), (C_CYCLE, f"{m.cycle_ms} ms"),
                            (C_SIG, s.name), (C_UNIT, s.unit)):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.ItemIsEnabled)
                if c == C_ID:
                    it.setFont(mono)
                t.setItem(r, c, it)
            ed = ValueEditor(s, lambda val, n=s.name: self.rb.set(**{n: val}))
            ed.show_value(self.rb.values.get(s.name, DEFAULTS.get(s.name, 0)))
            t.setCellWidget(r, C_VAL, ed)
            pl = QTableWidgetItem()
            pl.setFlags(Qt.ItemIsEnabled)
            pl.setFont(mono)
            t.setItem(r, C_PAYLOAD, pl)
            self.rows.append({"msg": m, "sig": s, "send": send, "editor": ed, "payload": pl})
        hh = t.horizontalHeader()
        for c in range(len(COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(C_VAL, QHeaderView.Stretch)
        t.verticalHeader().setDefaultSectionSize(34)
        return t

    def _hu_controls(self):
        box = QGroupBox("HU controls (via MCU)")
        g = QGridLayout(box)
        r = 0

        def btn(text, cmd, row, col, span=1):
            b = QPushButton(text)
            b.clicked.connect(lambda: self.mcu(cmd))
            g.addWidget(b, row, col, 1, span)
            return b

        g.addWidget(QLabel("Knob"), r, 0, 1, 3)
        r += 1
        btn("⟲ turn", {"cmd": "knob", "value": -1}, r, 0)
        btn("push", {"cmd": "push"}, r, 1)
        btn("turn ⟳", {"cmd": "knob", "value": 1}, r, 2)
        r += 1
        btn("◀ tilt", {"cmd": "tilt", "value": -1}, r, 0)
        btn("tilt ▶", {"cmd": "tilt", "value": 1}, r, 2)
        r += 1
        g.addWidget(QLabel("Keys"), r, 0, 1, 3)
        r += 1
        keys = ["HOME", "BACK", "NAV", "MEDIA", "RADIO", "PHONE", "CAR", "SETUP", "MUTE", "VOL_DOWN", "VOL_UP"]
        for i, k in enumerate(keys):
            btn(k.replace("_", " ").title(), {"cmd": "button", "name": k}, r + i // 3, i % 3)
        r += (len(keys) + 2) // 3
        g.addWidget(QLabel("Display dimming"), r, 0, 1, 3)
        r += 1
        self.dim_auto = QCheckBox("auto (LightState)")
        self.dim_auto.setChecked(True)
        self.dim = QSlider(Qt.Horizontal)
        self.dim.setRange(0, 100)
        self.dim.setValue(100)
        self.dim.setEnabled(False)
        self.dim_auto.toggled.connect(self._dim_changed)
        self.dim.valueChanged.connect(self._dim_changed)
        g.addWidget(self.dim_auto, r, 0, 1, 3)
        r += 1
        g.addWidget(self.dim, r, 0, 1, 3)
        r += 1
        self.mcu_state = QLabel("MCU: –")
        self.mcu_state.setWordWrap(True)
        g.addWidget(self.mcu_state, r, 0, 1, 3)
        g.setRowStretch(r + 1, 1)
        return box

    # ---- actions -----------------------------------------------------------
    def mcu(self, cmd):
        try:
            rep = mcu_call(cmd)
            if not rep.get("ok"):
                self.statusBar().showMessage(f"MCU: {rep.get('error')}", 4000)
        except OSError as e:
            self.statusBar().showMessage(f"MCU emulator not reachable ({e})", 4000)

    def _dim_changed(self, *_):
        self.dim.setEnabled(not self.dim_auto.isChecked())
        self.mcu({"cmd": "dim", "level": "auto" if self.dim_auto.isChecked() else self.dim.value()})

    def set_message(self, name, on):
        (self.rb.start_message if on else self.rb.stop_message)(name)

    def set_all(self, on):
        self.btn_sleep.setChecked(not on)
        for row in self.rows:
            row["send"].setChecked(on)

    def set_sleep(self, asleep):
        for row in self.rows:
            row["send"].blockSignals(True)
            row["send"].setChecked(not asleep and self.rb.by_name[row["msg"].name].enabled)
            row["send"].setEnabled(not asleep)
            row["send"].blockSignals(False)
        self.rb.paused = asleep

    def set_drive(self, on):
        self.drive = DriveCycle() if on else None
        if self.drive:  # continue from the current odometer / trip / fuel
            self.drive.odo = float(self.rb.values["Odometer"])
            self.drive.trip = float(self.rb.values["TripDistance"])
            self.drive.fuel = float(self.rb.values["FuelLevel"])
            self.drive.last = 0.0
            self.drive_t0 = None
        for row in self.rows:
            row["editor"].setEnabled(not (on and row["sig"].name in self.driven))

    def reset_values(self):
        self.btn_drive.setChecked(False)
        self.rb.set(**DEFAULTS)

    def apply_filter(self, text):
        text = text.lower()
        for r, row in enumerate(self.rows):
            m, s = row["msg"], row["sig"]
            hay = f"{m.name} {s.name} {m.frame_id:x} 0x{m.frame_id:03x}".lower()
            self.table.setRowHidden(r, bool(text) and text not in hay)

    # ---- periodic ----------------------------------------------------------
    def refresh(self):
        import time
        if self.drive:
            now = time.monotonic()
            if self.drive_t0 is None:
                self.drive_t0 = now
            self.rb.set(**self.drive(now - self.drive_t0))
        vals = dict(self.rb.values)
        dim_off = QColor("#888")
        for row in self.rows:
            m, s = row["msg"], row["sig"]
            if self.drive and s.name in self.driven:
                row["editor"].show_value(vals[s.name])
            live = self.rb.by_name[m.name].enabled and not self.rb.paused
            row["payload"].setText(self.rb.by_name[m.name].pack(vals).hex(" ").upper())
            row["payload"].setForeground(QColor() if live else dim_off)
        self.status.setText(f"sent {self.rb.sent} frames  ·  {self.rb.errors} send errors"
                            + ("  ·  BUS ASLEEP" if self.rb.paused else "")
                            + ("  ·  drive cycle" if self.drive else ""))
        if not hasattr(self, "_mcu_tick"):
            self._mcu_tick = 0
        self._mcu_tick += 1
        if self._mcu_tick % 5 == 1:  # MCU state once a second
            try:
                st = mcu_call({"cmd": "status"})
                dim = st.get("dim") or ["–", False]
                self.mcu_state.setText(
                    f"MCU: power <b>{st['power']}</b>, link {'up' if st['link_up'] else 'down'}, "
                    f"display {dim[0]} % {'night' if dim[1] else 'day'}"
                    + (", shutting down" if st.get("shutdown_pending") else ""))
            except OSError:
                self.mcu_state.setText("MCU emulator not running")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", default=None, help="Gateway address (default: BOAT_HOST, then localhost:50051)")
    ap.add_argument("--dbc", default=str(DBC), help="DBC for ranges, enums and units")
    ap.add_argument("--iface", default="vcan_info", help="interface for the Infotainment bus")
    ap.add_argument("--screenshot", metavar="PNG", help="save the window after 2 s and quit")
    a = ap.parse_args()
    if a.screenshot and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication(sys.argv)
    rb = Restbus(bus_map={"Infotainment": a.iface}, address=a.address).start()
    win = Panel(rb, Database(a.dbc), a.address or os.environ.get("BOAT_HOST", "localhost:50051"))
    win.show()
    if a.screenshot:
        QTimer.singleShot(2000, lambda: (win.grab().save(a.screenshot), app.quit()))
    code = app.exec()
    rb.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
