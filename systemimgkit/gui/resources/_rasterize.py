#!/usr/bin/env python3
"""Rasterize the SystemImgKit icon SVG to PNGs at standard sizes.

Uses PySide6's QSvgRenderer (no external rsvg-convert/inkscape needed).
Run from the .venv:
    .venv/bin/python systemimgkit/gui/resources/_rasterize.py
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QByteArray, QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "icon.svg")
SIZES = [16, 22, 24, 32, 48, 64, 128, 256]
# The hicolor set under data/icons/hicolor/<size>x<size>/apps/systemimgkit.png
# is what `systemimgkit install-icons` copies into the user data dir (and what
# the .desktop entry references). Keep it in sync with the SVG so a redrawn
# icon actually reaches the launcher/menu without a manual copy.
DATA_HICOLOR = os.path.normpath(
    os.path.join(HERE, "..", "..", "data", "icons", "hicolor"))


def main() -> int:
    if not os.path.isfile(SVG):
        print(f"missing {SVG}", file=sys.stderr)
        return 1
    data = open(SVG, "rb").read()
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        print("QSvgRenderer could not parse icon.svg", file=sys.stderr)
        return 1

    for px in SIZES:
        img = QImage(QSize(px, px), QImage.Format_ARGB32)
        img.fill(0)  # transparent
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        renderer.render(p)
        p.end()
        # 1) qrc-facing raster set: gui/resources/icon-<px>.png
        out = os.path.join(HERE, f"icon-{px}.png")
        img.save(out, "PNG")
        print("wrote", out)
        # 2) hicolor set for install-icons / .desktop: data/icons/hicolor/<px>x<px>/apps/
        hdir = os.path.join(DATA_HICOLOR, f"{px}x{px}", "apps")
        os.makedirs(hdir, exist_ok=True)
        hout = os.path.join(hdir, "systemimgkit.png")
        img.save(hout, "PNG")
        print("wrote", hout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
