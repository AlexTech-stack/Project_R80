#!/usr/bin/env python3
"""Launch the R80 headunit UI mockup.

    python3 run.py                 # windowed, 1280x768
    python3 run.py --fullscreen
    python3 run.py --screenshots out/   # render every screen to PNGs and exit
"""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--screenshots", metavar="DIR", help="save a PNG of every screen into DIR and quit")
    args = ap.parse_args()

    if args.screenshots and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor, QFont
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow  # noqa: F401  (gives the root window grabWindow())

    app = QGuiApplication(sys.argv)
    app.setApplicationName("R80 Headunit mockup")
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "main.qml")))
    if not engine.rootObjects():
        sys.exit(1)
    win = engine.rootObjects()[0]
    if args.fullscreen:
        win.showFullScreen()

    if args.screenshots:
        out = Path(args.screenshots)
        out.mkdir(parents=True, exist_ok=True)
        shots = ["home", "navigation", "media", "radio", "phone", "vehicle",
                 "cluster", "clock", "settings", "call"]
        state = {"i": 0, "images": []}

        def step():
            i = state["i"]
            if i > 0:
                name = shots[i - 1]
                img = win.grabWindow()
                img.save(str(out / f"{i:02d}_{name}.png"))
                state["images"].append(img)
            if i == len(shots):
                make_sheet(state["images"], out / "overview.png")
                app.quit()
                return
            name = shots[i]
            if name == "call":
                win.setProperty("current", "home")
                win.setProperty("demoCall", True)
            else:
                win.setProperty("current", name)
            state["i"] += 1
            QTimer.singleShot(1500, step)

        def make_sheet(images, path):
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

        QTimer.singleShot(1200, step)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
