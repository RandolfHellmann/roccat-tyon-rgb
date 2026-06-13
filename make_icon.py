# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Randolf Hellmann
"""Generate tyon.ico — a clean app icon (rounded accent tile + mouse glyph).

Renders several sizes with Qt and packs them into a PNG-compressed .ico so the
icon stays crisp from the taskbar (16 px) to large tiles (256 px).
"""
import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ACCENT = "#5A8DEE"
ACCENT_LO = "#3F6FD0"


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = float(size)

    # rounded tile with a vertical accent gradient
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0.0, QColor("#6E9CF2"))
    grad.setColorAt(1.0, QColor(ACCENT_LO))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(QRectF(s * 0.06, s * 0.06, s * 0.88, s * 0.88),
                      s * 0.22, s * 0.22)

    # mouse body
    w, h = s * 0.42, s * 0.60
    cx, top = s / 2, s * 0.20
    body = QRectF(cx - w / 2, top, w, h)
    p.setBrush(QColor(255, 255, 255, 240))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(body, w * 0.46, w * 0.40)

    # button split line
    p.setPen(QPen(QColor(ACCENT_LO), max(1.0, s * 0.012)))
    p.drawLine(QPointF(cx, body.top() + s * 0.035), QPointF(cx, top + h * 0.34))

    # scroll wheel (accent)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ACCENT))
    ww = s * 0.052
    p.drawRoundedRect(QRectF(cx - ww / 2, body.top() + s * 0.075, ww, s * 0.12),
                      ww / 2, ww / 2)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def main():
    QApplication([])  # required for QImage painting on some platforms
    sizes = [256, 128, 64, 48, 32, 16]
    pngs = [(sz, png_bytes(render(sz))) for sz in sizes]

    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(pngs))      # ICONDIR
    offset = 6 + 16 * len(pngs)
    entries, blobs = bytearray(), bytearray()
    for sz, data in pngs:
        b = sz if sz < 256 else 0                    # 0 means 256
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    out += entries + blobs

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tyon.ico")
    with open(path, "wb") as fh:
        fh.write(out)
    print(f"wrote {path} ({len(out)} bytes, {len(pngs)} sizes)")


if __name__ == "__main__":
    main()
