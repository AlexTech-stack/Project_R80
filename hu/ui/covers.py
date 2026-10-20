"""Cover art tinted in the accent colour, for QML's Image (image://cover/...).

The UI is monochrome line art (AGENTS.md 9), so a cover is drawn in the accent
colour only: its brightness becomes the alpha of a plain accent-coloured image,
dark parts fade into the black background. Done with QImage operations, not a
shader, so it looks the same with every scene graph backend (also the software
one of the offscreen screenshots).

    Image { source: "image://cover/" + accentHex + "/" + encodeURIComponent(path) }
"""
from __future__ import annotations

from urllib.parse import unquote

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider


class CoverProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, ident: str, size: QSize, requested: QSize) -> QImage:
        accent, _, path = ident.partition("/")
        img = QImage(unquote(path))
        if img.isNull():
            return QImage()
        if requested.isValid() and requested.width() > 0 and requested.height() > 0:
            img = img.scaled(requested, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
        out.fill(QColor("#" + accent))
        out.setAlphaChannel(img.convertToFormat(QImage.Format_Grayscale8))
        size.setWidth(out.width())
        size.setHeight(out.height())
        return out
