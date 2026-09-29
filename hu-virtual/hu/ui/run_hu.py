#!/usr/bin/env python3
"""Run the R80 headunit UI mockup on real vehicle data from hu-vehicled.

Loads the unchanged mockup QML (hu-mockup/qml) with one file swapped: Sim.qml
comes from hu-virtual/hu/ui/qml and takes vehicle values from D-Bus. Knob and
button events from the MCU become the same key presses the mockup already
handles, and the display blanks while the MCU reports power off.

    python3 hu/ui/run_hu.py                          # uses ../hu-mockup of this repo
    python3 hu/ui/run_hu.py --screenshot out.png     # grab one frame after 3 s and quit
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_MOCKUP = Path(os.environ.get("R80_MOCKUP", HERE.parents[2] / "hu-mockup"))

# MCU input -> key the mockup's main.qml already understands
BUTTON_KEYS = {"HOME": "Escape", "BACK": "Escape", "NAV": "1", "MEDIA": "2", "RADIO": "3",
               "PHONE": "4", "CAR": "5", "SETUP": "8"}

POWER_OVERLAY = b"""
import QtQuick
import R80.Backend 1.0
Rectangle {
    anchors.fill: parent
    z: 1000
    color: "black"
    visible: opacity > 0
    opacity: Vehicle.linkUp && (Vehicle.power === "off" || Vehicle.power === "shutdown") ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 600 } }
    MouseArea { anchors.fill: parent }   // swallow input while the display is off
}
"""


def overlay_dir(mockup: Path) -> Path:
    """Mockup qml/ with Sim.qml replaced, as symlinks in a temp dir."""
    root = Path(tempfile.mkdtemp(prefix="r80-hu-"))
    (root / "qml").mkdir()
    for f in (mockup / "qml").iterdir():
        src = HERE / "qml" / f.name if (HERE / "qml" / f.name).exists() else f
        (root / "qml" / f.name).symlink_to(src.resolve())
    (root / "fonts").symlink_to((mockup / "fonts").resolve())
    return root


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mockup", default=str(DEFAULT_MOCKUP), help="path to hu-mockup/")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--system", action="store_true", help="talk to hu-vehicled on the system bus")
    ap.add_argument("--screen", default=None, help="start on this screen (home, cluster, vehicle, ...)")
    ap.add_argument("--screenshot", metavar="PNG", help="save one frame after 3 s and quit")
    a = ap.parse_args()
    mockup = Path(a.mockup).expanduser()
    if not (mockup / "qml" / "main.qml").exists():
        sys.exit(f"mockup not found at {mockup} (use --mockup or R80_MOCKUP)")
    if a.screenshot and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication, QKeyEvent
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, qmlRegisterSingletonInstance
    from PySide6.QtQuick import QQuickItem  # noqa: F401

    sys.path.insert(0, str(HERE))
    from backend import Vehicle

    app = QGuiApplication(sys.argv)
    app.setApplicationName("R80 Headunit (virtual)")
    vehicle = Vehicle(system_bus=a.system)
    qmlRegisterSingletonInstance(Vehicle, "R80.Backend", 1, 0, "Vehicle", vehicle)

    root = overlay_dir(mockup)
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(root / "qml" / "main.qml")))
    if not engine.rootObjects():
        sys.exit(1)
    win = engine.rootObjects()[0]
    if a.screen:
        win.setProperty("current", a.screen)
    if a.fullscreen:
        win.showFullScreen()

    comp = QQmlComponent(engine)
    comp.setData(POWER_OVERLAY, QUrl.fromLocalFile(str(root / "qml" / "PowerOverlay.qml")))
    overlay = comp.create()
    if overlay is None:
        sys.exit("power overlay failed: " + comp.errorString())
    overlay.setParentItem(win.contentItem())
    overlay.setParent(win)

    def key(name):
        k = getattr(Qt.Key, f"Key_{name}")
        for t in (QEvent.KeyPress, QEvent.KeyRelease):
            QGuiApplication.postEvent(win, QKeyEvent(t, k, Qt.NoModifier))

    def on_input(kind, value):
        if vehicle.power in ("off", "shutdown"):
            return
        if kind == "knob":
            for _ in range(abs(value)):
                key("Down" if value > 0 else "Up")
        elif kind == "tilt":
            key("Right" if value > 0 else "Left")
        elif kind == "push":
            key("Return")
        elif kind.startswith("button:"):
            b = kind.split(":", 1)[1]
            if b in BUTTON_KEYS:
                key(BUTTON_KEYS[b])
            elif b in ("VOL_UP", "VOL_DOWN"):
                vehicle.volumeStep.emit(1 if b == "VOL_UP" else -1)
            elif b == "MUTE":
                vehicle.muteToggled.emit()

    vehicle.input.connect(on_input)

    if a.screenshot:
        def grab():
            win.grabWindow().save(a.screenshot)
            app.quit()
        QTimer.singleShot(3000, grab)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
