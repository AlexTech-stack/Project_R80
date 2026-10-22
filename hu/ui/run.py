#!/usr/bin/env python3
"""Launch the R80 headunit UI. Usually started through ./r80 at the repo root.

Live (default): the real R80.Backend singletons from backend.py, so Sim.qml takes its
values from the services over D-Bus. Knob and button events from the MCU become the
key presses main.qml already handles, and the display blanks while the MCU reports
power off.
Demo (--demo, --screenshots): qml-demo/ stands in for R80.Backend; every backend says
available:false and Sim.qml shows its fake data. No services, no D-Bus.

    python3 hu/ui/run.py                          # live, windowed, 1280x768
    python3 hu/ui/run.py --fullscreen --system    # live on the system bus, full screen
    python3 hu/ui/run.py --demo                   # fake data
    python3 hu/ui/run.py --screenshots out/       # demo: every screen to PNGs, then quit
    python3 hu/ui/run.py --screenshot out.png     # one frame after 3 s, then quit
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path



def now() -> float:
    """Seconds since boot (Linux), else a monotonic clock."""
    return time.clock_gettime(time.CLOCK_BOOTTIME) if hasattr(time, "CLOCK_BOOTTIME") else time.monotonic()


def _process_start() -> float:
    """When this process started, on the now() clock (Linux: from /proc, also counted from
    boot). Else now: then the Python start itself is not counted."""
    try:
        start_ticks = int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19])
        return start_ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, AttributeError):
        return now()


STARTED = _process_start()           # for the start-up times in the log (live mode)

HERE = Path(__file__).resolve().parent

# MCU input -> key main.qml already understands
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

SHOTS = ["home", "navigation", "nav_stale", "nav_nophone", "nav_reroute", "nav_signpost", "nav_arrive", "media",
         "media_browse", "media_album", "radio", "phone", "phone_contact", "vehicle", "cluster", "clock", "settings", "call",
         "volume", "audio", "phone_settings", "system", "diagnostics", "trip", "warning", "warnings",
         "software_update"]


def register_backends(system_bus: bool):
    """Create the D-Bus backends and register them as the R80.Backend singletons."""
    from PySide6.QtQml import qmlRegisterSingletonInstance
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parent / "services"))
    import dlt
    dlt.app("HMI", "User interface", "ui")
    log_qt_messages(dlt.context("QML", "Qt and QML messages"))
    import backend
    objs = {}
    for name in ("Vehicle", "Media", "Audio", "Warnings", "Trip", "Nav", "System", "Phone"):
        cls = getattr(backend, name)
        objs[name] = cls(system_bus=system_bus)
        qmlRegisterSingletonInstance(cls, "R80.Backend", 1, 0, name, objs[name])
    return objs


def log_qt_messages(log):
    """Qt's and QML's own messages (binding errors, console.log) into the DLT log."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    levels = {QtMsgType.QtDebugMsg: log.debug, QtMsgType.QtInfoMsg: log.info, QtMsgType.QtWarningMsg: log.warning,
              QtMsgType.QtCriticalMsg: log.error, QtMsgType.QtFatalMsg: log.critical}

    def handler(kind, ctx, text):
        where = f"{Path(ctx.file).name}:{ctx.line}: " if ctx.file else ""
        levels.get(kind, log.info)(where + text)
    qInstallMessageHandler(handler)


def add_power_overlay(engine, win):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent
    comp = QQmlComponent(engine)
    comp.setData(POWER_OVERLAY, QUrl.fromLocalFile(str(HERE / "qml" / "PowerOverlay.qml")))   # base URL for its imports
    overlay = comp.create()
    if overlay is None:
        sys.exit("power overlay failed: " + comp.errorString())
    overlay.setParentItem(win.contentItem())
    overlay.setParent(win)


def connect_mcu_input(vehicle, win):
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QGuiApplication, QKeyEvent

    def focus_item(item):
        for child in item.childItems():
            if child.hasFocus():
                return focus_item(child) or child
        return None

    def key(name):
        # Deliver straight to the item holding keyboard focus (main.qml's `display`).
        # Posting to the window would drop the key whenever the HU window is not the
        # active one, e.g. while the tester clicks in the restbus panel; the real
        # knob doesn't care which window has the desktop's focus either.
        k = getattr(Qt.Key, f"Key_{name}")
        target = focus_item(win.contentItem())
        for t in (QEvent.KeyPress, QEvent.KeyRelease):
            ev = QKeyEvent(t, k, Qt.NoModifier)
            if target:
                QCoreApplication.sendEvent(target, ev)
            else:
                QGuiApplication.postEvent(win, ev)

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


def run_screenshots(app, win, out: Path):
    """Step through every screen (demo flags of main.qml), save PNGs and an overview sheet."""
    from PySide6.QtCore import Q_ARG, QMetaObject, QObject, QTimer
    out.mkdir(parents=True, exist_ok=True)
    state = {"i": 0, "images": []}

    def step():
        i = state["i"]
        if i > 0:
            img = win.grabWindow()
            img.save(str(out / f"{i:02d}_{SHOTS[i - 1]}.png"))
            state["images"].append(img)
        if i == len(SHOTS):
            make_sheet(state["images"], out / "overview.png")
            app.quit()
            return
        name = SHOTS[i]
        if not name.startswith("nav_"):
            win.setProperty("demoNav", "live")
        if name == "call":
            win.setProperty("current", "home")
            win.setProperty("demoCall", True)
        elif name == "volume":
            win.setProperty("current", "media")
            win.setProperty("demoVolume", True)
        elif name == "warning":
            win.setProperty("current", "home")
            win.setProperty("demoWarnings", True)
        elif name == "warnings":
            win.setProperty("current", "vehicle")
            QTimer.singleShot(300, lambda: win.findChild(QObject, "vehicleScreen").setProperty("tab", 4))
        elif name.startswith("nav_"):
            win.setProperty("current", "navigation")
            win.setProperty("demoNav", name[4:])
        elif name == "trip":
            win.setProperty("demoWarnings", False)
            win.setProperty("current", "vehicle")
            QTimer.singleShot(300, lambda: win.findChild(QObject, "vehicleScreen").setProperty("tab", 1))
        elif name == "system":
            win.setProperty("demoVolume", False)
            win.setProperty("current", "settings")
            QTimer.singleShot(300, lambda: win.findChild(QObject, "settingsScreen").setProperty("cat", 5))
        elif name == "diagnostics":
            win.setProperty("demoVolume", False)
            win.setProperty("current", "settings")

            def diagnostics():
                screen = win.findChild(QObject, "settingsScreen")
                screen.setProperty("cat", 7)
                screen.setProperty("inPanel", True)
                screen.setProperty("item", 2)               # the media service, its level switch
            QTimer.singleShot(300, diagnostics)
        elif name in ("media_browse", "media_album"):
            win.setProperty("demoWarnings", False)
            win.setProperty("current", "media")

            def call(method, *args):
                screen = win.findChild(QObject, "mediaScreen")
                QMetaObject.invokeMethod(screen, method, *[Q_ARG("QVariant", x) for x in args])
            # each list answers asynchronously, so give every step a moment
            steps = ([("openBrowser",), ("knob", 2)] if name == "media_browse"     # the menu, "Albums" selected
                     else [("press",), ("knob", 4), ("press",)])                    # Albums -> the 5th album
            for k, todo in enumerate(steps):
                QTimer.singleShot(300 + 300 * k, lambda st=todo: call(*st))
        elif name == "phone_contact":
            win.setProperty("current", "phone")

            def contact():
                screen = win.findChild(QObject, "phoneScreen")
                screen.setProperty("tab", 2)
                QTimer.singleShot(200, lambda: QMetaObject.invokeMethod(screen, "press"))
            QTimer.singleShot(300, contact)
        elif name == "phone_settings":
            win.setProperty("demoVolume", False)
            win.setProperty("current", "settings")
            QTimer.singleShot(300, lambda: win.findChild(QObject, "settingsScreen").setProperty("cat", 3))
        elif name == "software_update":
            win.setProperty("demoWarnings", False)
            win.setProperty("current", "settings")
            QTimer.singleShot(300, lambda: win.findChild(QObject, "settingsScreen").setProperty("cat", 6))
        elif name == "audio":
            win.setProperty("demoVolume", False)
            win.setProperty("current", "settings")
            QTimer.singleShot(300, lambda: win.findChild(QObject, "settingsScreen").setProperty("cat", 2))
        else:
            win.setProperty("current", name)
        state["i"] += 1
        # after the warnings, their notice banner stays up for 5 s (WarningBanner.qml)
        QTimer.singleShot(6000 if name == "software_update" else 1500, step)

    QTimer.singleShot(1200, step)


def make_sheet(images, path: Path):
    from PySide6.QtGui import QColor, QImage, QPainter
    cols = 3
    w, h = images[0].width(), images[0].height()
    s = 0.5
    tw, th, gap = int(w * s), int(h * s), 16
    rows = (len(images) + cols - 1) // cols
    sheet = QImage(cols * tw + (cols + 1) * gap, rows * th + (rows + 1) * gap, QImage.Format_RGB32)
    sheet.fill(QColor("#141414"))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    for k, img in enumerate(images):
        r, c = divmod(k, cols)
        p.drawImage(gap + c * (tw + gap), gap + r * (th + gap), img.scaled(tw, th))
    p.end()
    sheet.save(str(path))


def log_startup(win, steps: dict):
    """Live mode: how long the start took, into the DLT log (HMI MAIN): Python and PySide6
    up, the backends, QML loaded, the first frame on the display (docs/bench-pi.md)."""
    import dlt
    log = dlt.context("MAIN")
    done = {"frame": False}

    def first_frame():
        if done["frame"]:
            return
        done["frame"] = True
        steps["first frame"] = now()
        parts = ", ".join(f"{k} {v - STARTED:.2f} s" for k, v in steps.items())
        log.info(f"start-up: {parts} (since the UI process started)")
    win.frameSwapped.connect(first_frame)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="fake data from qml-demo/, no services needed")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--system", action="store_true", help="live: talk to the services on the system bus")
    ap.add_argument("--screen", default=None, help="start on this screen (home, cluster, vehicle, ...)")
    ap.add_argument("--screenshot", metavar="PNG", help="save one frame after 3 s and quit")
    ap.add_argument("--screenshots", metavar="DIR", help="demo: save a PNG of every screen into DIR and quit")
    a = ap.parse_args()
    demo = a.demo or bool(a.screenshots)

    if (a.screenshot or a.screenshots) and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow  # noqa: F401  (gives the root window grabWindow())

    steps = {"Qt imported": now()}
    app = QGuiApplication(sys.argv)
    app.setApplicationName("R80 Headunit" + (" (demo)" if demo else ""))
    backends = None if demo else register_backends(a.system)
    steps["backends"] = now()

    engine = QQmlApplicationEngine()
    if not demo:
        from covers import CoverProvider            # register_backends put HERE on sys.path
        engine.addImageProvider("cover", CoverProvider())
    if demo:
        engine.addImportPath(str(HERE / "qml-demo"))      # demo stand-ins for R80.Backend
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "main.qml")))
    if not engine.rootObjects():
        sys.exit(1)
    win = engine.rootObjects()[0]
    steps["QML loaded"] = now()
    if not demo:
        log_startup(win, steps)
    if a.screen:
        win.setProperty("current", a.screen)
    if a.fullscreen:
        win.showFullScreen()

    if backends:
        add_power_overlay(engine, win)
        connect_mcu_input(backends["Vehicle"], win)

    if a.screenshots:
        run_screenshots(app, win, Path(a.screenshots))
    elif a.screenshot:
        def grab():
            win.grabWindow().save(a.screenshot)
            app.quit()
        QTimer.singleShot(3000, grab)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
