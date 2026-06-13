# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Randolf Hellmann
"""Reusable widgets, theme, and icon factory for the Tyon GUI.

Kept separate from tyon_gui.py so the window/page logic stays readable. This
module depends only on PySide6 (no device imports), so it is safe to import
anywhere. Key-name mappings return tyon_rgb HID_KEY *names* (plain strings),
which the GUI hands to the device layer.
"""
from __future__ import annotations

import json
import math
import os

from PySide6.QtCore import (
    Property, QPointF, QPropertyAnimation, QRectF, QSize, Qt, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QFontMetricsF, QIcon,
    QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGraphicsDropShadowEffect, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

# ---------------------------------------------------------------------
#   Palette
# ---------------------------------------------------------------------

COL = {
    "bg":        "#0E1014",   # window background
    "rail":      "#0A0C10",   # nav rail (slightly darker)
    "content":   "#12151B",   # content area
    "card":      "#181B22",   # cards / surfaces
    "card2":     "#1E222B",   # raised controls inside cards
    "border":    "#272C36",
    "border2":   "#333a47",
    "text":      "#E7E9ED",
    "muted":     "#8A92A0",
    "faint":     "#5b626f",
    "accent":    "#5A8DEE",   # cool, restrained chrome accent
    "accentHi":  "#74A0F3",
    "accentLo":  "#3F6FD0",
    "ok":        "#46C98B",
    "danger":    "#FF6B6B",
    "warn":      "#F2B544",
}


# ---------------------------------------------------------------------
#   Icon factory  (simple, original line icons drawn with QPainter)
# ---------------------------------------------------------------------

def make_icon(name: str, color: str, size: int = 22, stroke: float = 1.9) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color), stroke)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = size
    c = s / 2.0

    if name == "light":            # sun / lighting
        r = s * 0.18
        p.drawEllipse(QPointF(c, c), r, r)
        for i in range(8):
            a = math.radians(i * 45)
            r1, r2 = r + s * 0.10, r + s * 0.22
            p.drawLine(QPointF(c + math.cos(a) * r1, c + math.sin(a) * r1),
                       QPointF(c + math.cos(a) * r2, c + math.sin(a) * r2))
    elif name == "pointer":        # precision target
        r = s * 0.30
        p.drawEllipse(QPointF(c, c), r, r)
        for a in (0, 90, 180, 270):
            ar = math.radians(a)
            p.drawLine(QPointF(c + math.cos(ar) * (r - 2), c + math.sin(ar) * (r - 2)),
                       QPointF(c + math.cos(ar) * (r + s * 0.12),
                               c + math.sin(ar) * (r + s * 0.12)))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(c, c), s * 0.05, s * 0.05)
    elif name == "buttons":        # mouse silhouette
        w, h = s * 0.46, s * 0.66
        rect = QRectF(c - w / 2, c - h / 2, w, h)
        p.drawRoundedRect(rect, w * 0.5, w * 0.42)
        p.drawLine(QPointF(c, rect.top() + 2), QPointF(c, c - h * 0.02))
    elif name == "macro":          # lightning bolt
        poly = QPolygonF([
            QPointF(c + s * 0.10, s * 0.16),
            QPointF(c - s * 0.18, c + s * 0.04),
            QPointF(c - s * 0.01, c + s * 0.04),
            QPointF(c - s * 0.10, s * 0.84),
            QPointF(c + s * 0.20, c - s * 0.02),
            QPointF(c + s * 0.02, c - s * 0.02),
        ])
        p.drawPolygon(poly)
    elif name == "games":          # gamepad
        w, h = s * 0.60, s * 0.34
        rect = QRectF(c - w / 2, c - h / 2, w, h)
        p.drawRoundedRect(rect, h * 0.5, h * 0.5)
        # d-pad
        dx = c - w * 0.28
        p.drawLine(QPointF(dx, c - h * 0.16), QPointF(dx, c + h * 0.16))
        p.drawLine(QPointF(dx - h * 0.16, c), QPointF(dx + h * 0.16, c))
        # buttons
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(c + w * 0.22, c - h * 0.10), s * 0.04, s * 0.04)
        p.drawEllipse(QPointF(c + w * 0.32, c + h * 0.10), s * 0.04, s * 0.04)
    elif name == "info":           # info circle
        r = s * 0.32
        p.drawEllipse(QPointF(c, c), r, r)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(c, c - r * 0.42), stroke * 0.7, stroke * 0.7)
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(c, c - r * 0.05), QPointF(c, c + r * 0.5))
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------
#   Mouse glyph (decorative, header)
# ---------------------------------------------------------------------

class MouseGlyph(QWidget):
    """A small top-down schematic of the mouse for the header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 54)
        self._accent = QColor(COL["accent"])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        body = QRectF(w * 0.16, 3, w * 0.68, h - 6)
        p.setPen(QPen(QColor(COL["border2"]), 1.6))
        p.setBrush(QColor(COL["card2"]))
        p.drawRoundedRect(body, w * 0.34, w * 0.30)
        # split line
        p.setPen(QPen(QColor(COL["border2"]), 1.2))
        p.drawLine(QPointF(w / 2, body.top() + 2), QPointF(w / 2, body.top() + h * 0.36))
        # scroll wheel (accent)
        p.setPen(Qt.NoPen)
        p.setBrush(self._accent)
        p.drawRoundedRect(QRectF(w / 2 - 2.2, body.top() + 7, 4.4, 10), 2.2, 2.2)


# ---------------------------------------------------------------------
#   Interactive mouse diagram (visual button picker)
# ---------------------------------------------------------------------

class MouseDiagram(QWidget):
    """Interactive top-down schematic of the Tyon. Every assignable button is
    drawn as its own shape on the mouse; clicking a shape (or its label)
    selects and highlights it. Emits ``selected(name)`` and can be driven from
    outside via :meth:`set_selected`.

    Original vector artwork drawn with QPainter — no product photos, so it is
    safe to ship under MIT. Layout follows the real Tyon: the two main clicks,
    the scroll wheel, the two-way Dorsal-Fin rocker behind the wheel, the two
    top-seam button pairs, and the thumb cluster (X-Celerator paddle, two thumb
    buttons and the thumb pedal) on the left flank.
    """

    selected = Signal(str)

    # name: (x, y, w, h, label-side, kind). The rect is in fractions of the
    # silhouette's bounding box (x may be negative → the thumb flank sticks out
    # to the left of the body). label-side ∈ {L, R, T, S}; kind drives drawing.
    BUTTONS = {
        "left":              (0.040, 0.000, 0.455, 0.300, "L", "click"),
        "right":             (0.505, 0.000, 0.455, 0.300, "R", "click"),
        "middle":            (0.420, 0.055, 0.160, 0.160, "T", "wheel"),
        "fin_left":          (0.330, 0.255, 0.170, 0.080, "S", "fin"),
        "fin_right":         (0.500, 0.255, 0.170, 0.080, "S", "fin"),
        "left_forward":      (0.040, 0.305, 0.150, 0.075, "L", "btn"),
        "left_back":         (0.030, 0.405, 0.150, 0.075, "L", "btn"),
        "right_forward":     (0.810, 0.305, 0.150, 0.075, "R", "btn"),
        "right_back":        (0.820, 0.405, 0.150, 0.075, "R", "btn"),
        "thumb_paddle_up":   (-0.150, 0.455, 0.165, 0.070, "L", "btn"),
        "thumb_paddle_down": (-0.150, 0.535, 0.165, 0.070, "L", "btn"),
        "thumb_forward":     (-0.175, 0.640, 0.185, 0.070, "L", "btn"),
        "thumb_back":        (-0.175, 0.720, 0.185, 0.070, "L", "btn"),
        "thumb_pedal":       (-0.150, 0.800, 0.185, 0.070, "L", "btn"),
    }

    def __init__(self, buttons, parent=None):
        super().__init__(parent)
        self._labels = {name: label for name, label in buttons}
        self._assign: dict[str, str] = {}
        self._selected: str | None = None
        self._hover: str | None = None
        self._hits: dict = {}
        self._body_path = QPainterPath()
        self.setMinimumSize(360, 480)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # -- public API --
    def set_selected(self, name):
        if name != self._selected:
            self._selected = name
            self.update()

    def set_assignments(self, mapping):
        self._assign = dict(mapping)
        self.update()

    # -- geometry --
    def _body_rect(self) -> QRectF:
        w, h = self.width(), self.height()
        bw = min(0.40 * w, 0.56 * h)        # gaming-mouse aspect (length 1.6×)
        bh = bw * 1.6
        if bh > 0.88 * h:
            bh = 0.88 * h
            bw = bh / 1.6
        cx, cy = 0.58 * w, 0.50 * h          # shift right → room for the thumb
        return QRectF(cx - bw / 2, cy - bh / 2, bw, bh)

    def _shape(self, body: QRectF, name: str) -> QRectF:
        x, y, sw, sh, _side, _kind = self.BUTTONS[name]
        return QRectF(body.left() + x * body.width(),
                      body.top() + y * body.height(),
                      sw * body.width(), sh * body.height())

    @staticmethod
    def _distribute(items, ymin, ymax, gap) -> dict:
        """items: [(desired_y, name)] → {name: y}, kept in order and ≥gap apart."""
        items = sorted(items)
        out, prev = {}, ymin - gap
        for y, name in items:
            y = max(y, prev + gap)
            out[name] = y
            prev = y
        if items and prev > ymax:                  # overflow → shift the stack up
            shift = prev - ymax
            prev = ymin - gap
            for y, name in items:
                y = max(out[name] - shift, prev + gap)
                out[name] = y
                prev = y
        return out

    def _layout(self) -> dict:
        w, h = self.width(), self.height()
        body = self._body_rect()
        gap, boxh = 0.012 * w, 0.046 * h
        shapes = {n: self._shape(body, n) for n in self.BUTTONS if n in self._labels}
        left_x = max(0.02 * w, body.left() - 0.20 * body.width() - gap)
        right_x = body.right() + gap
        l_items = [(shapes[n].center().y(), n) for n, s in self.BUTTONS.items()
                   if n in self._labels and s[4] == "L"]
        r_items = [(shapes[n].center().y(), n) for n, s in self.BUTTONS.items()
                   if n in self._labels and s[4] == "R"]
        ly_l = self._distribute(l_items, 0.05 * h, 0.97 * h, boxh)
        ly_r = self._distribute(r_items, 0.05 * h, 0.97 * h, boxh)
        out = {}
        for name, s in self.BUTTONS.items():
            if name not in self._labels:
                continue
            shape, side = shapes[name], s[4]
            if side == "L":
                cy = ly_l[name]
                lab = QRectF(0.02 * w, cy - boxh / 2, left_x - 0.02 * w, boxh)
            elif side == "R":
                cy = ly_r[name]
                lab = QRectF(right_x, cy - boxh / 2, 0.98 * w - right_x, boxh)
            elif side == "T":
                lab = QRectF(shape.center().x() - 0.13 * w,
                             body.top() - 0.012 * h - boxh, 0.26 * w, boxh)
            else:  # S — stacked on the shell just below the fin
                frac = 0.360 if name == "fin_left" else 0.470
                lab = QRectF(body.left() + 0.16 * body.width(),
                             body.top() + frac * body.height(),
                             0.68 * body.width(), boxh)
            out[name] = (shape, lab, side)
        return out

    # -- painting --
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        self._hits = self._layout()
        self._draw_body(p, self._body_rect())
        # draw unselected first, then hover, then the selected button on top
        order = [n for n in self._hits if n not in (self._hover, self._selected)]
        order += [n for n in (self._hover, self._selected)
                  if n and n in self._hits]
        for name in order:
            shape, lab, side = self._hits[name]
            self._draw_button(p, name, shape)
            self._draw_label(p, name, shape, lab, side)
        p.end()

    def _state(self, name) -> str:
        if name == self._selected:
            return "sel"
        if name == self._hover:
            return "hov"
        return "off"

    def _draw_body(self, p: QPainter, body: QRectF):
        L, R, T, B = body.left(), body.right(), body.top(), body.bottom()
        W, H = body.width(), body.height()
        cx = (L + R) / 2

        # rounded gaming-mouse silhouette (narrow nose, broad palm)
        path = QPainterPath()
        path.moveTo(cx, T)
        path.cubicTo(cx + 0.36 * W, T, cx + 0.52 * W, T + 0.12 * H,
                     cx + 0.50 * W, T + 0.40 * H)
        path.cubicTo(cx + 0.48 * W, T + 0.74 * H, cx + 0.38 * W, B, cx, B)
        path.cubicTo(cx - 0.38 * W, B, cx - 0.48 * W, T + 0.74 * H,
                     cx - 0.50 * W, T + 0.40 * H)
        path.cubicTo(cx - 0.52 * W, T + 0.12 * H, cx - 0.36 * W, T, cx, T)
        path.closeSubpath()
        self._body_path = path

        grad = QLinearGradient(0, T, 0, B)
        grad.setColorAt(0.0, QColor("#2A3140"))
        grad.setColorAt(0.55, QColor("#1E2330"))
        grad.setColorAt(1.0, QColor("#15171F"))
        p.setPen(QPen(QColor("#3E4658"), 2))
        p.setBrush(grad)
        p.drawPath(path)

        # blue base glow along the lower rim (echoes the Tyon's RGB strip)
        p.save()
        p.setClipPath(path)
        gg = QLinearGradient(0, T + 0.78 * H, 0, B)
        c0 = QColor(COL["accent"]); c0.setAlpha(0)
        c1 = QColor(COL["accent"]); c1.setAlpha(70)
        gg.setColorAt(0.0, c0)
        gg.setColorAt(1.0, c1)
        p.setPen(Qt.NoPen)
        p.setBrush(gg)
        p.drawRect(QRectF(L, T + 0.78 * H, W, 0.22 * H))
        p.restore()

        # click area: centre split + a curved separator from the palm
        p.setPen(QPen(QColor("#454D60"), 1.4))
        p.drawLine(QPointF(cx, T + 0.03 * H), QPointF(cx, T + 0.30 * H))
        sep = QPainterPath()
        sep.moveTo(L + 0.12 * W, T + 0.30 * H)
        sep.quadTo(cx, T + 0.37 * H, R - 0.12 * W, T + 0.30 * H)
        p.setBrush(Qt.NoBrush)
        p.drawPath(sep)

    def _draw_button(self, p: QPainter, name: str, shape: QRectF):
        kind = self.BUTTONS[name][5]
        st = self._state(name)
        if kind == "click":                       # highlight the click half only
            if st == "off":
                return
            p.save()
            p.setClipPath(self._body_path)
            col = QColor(COL["accent"])
            col.setAlpha(150 if st == "sel" else 70)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRect(shape)
            p.restore()
            return
        if st == "sel":
            fill, stroke = QColor(COL["accent"]), QColor(COL["accentHi"])
        elif st == "hov":
            fill, stroke = QColor("#37425A"), QColor(COL["accentHi"])
        else:
            fill = QColor(COL["accentLo"]) if kind == "wheel" else QColor("#2C323F")
            stroke = QColor("#4A5266")
        rad = shape.height() * 0.45
        p.setPen(QPen(stroke, 1.5))
        p.setBrush(fill)
        p.drawRoundedRect(shape, rad, rad)
        if kind == "wheel":                       # a couple of scroll ridges
            p.setPen(QPen(QColor(255, 255, 255, 55), 1.0))
            for f in (0.32, 0.5, 0.68):
                yy = shape.top() + shape.height() * f
                p.drawLine(QPointF(shape.left() + 3, yy), QPointF(shape.right() - 3, yy))

    def _draw_label(self, p: QPainter, name: str, shape: QRectF, lab: QRectF, side):
        st = self._state(name)
        if st == "sel":
            leader_c, txt_c = QColor(COL["accent"]), QColor(COL["text"])
        elif st == "hov":
            leader_c, txt_c = QColor(COL["accentHi"]), QColor(COL["text"])
        else:
            leader_c, txt_c = QColor(COL["faint"]), QColor(COL["muted"])
        if side == "L":
            p1 = QPointF(lab.right(), lab.center().y())
            p2 = QPointF(shape.left(), shape.center().y())
            align = Qt.AlignRight
        elif side == "R":
            p1 = QPointF(lab.left(), lab.center().y())
            p2 = QPointF(shape.right(), shape.center().y())
            align = Qt.AlignLeft
        elif side == "T":
            p1 = QPointF(lab.center().x(), lab.bottom())
            p2 = QPointF(shape.center().x(), shape.top())
            align = Qt.AlignHCenter
        else:  # S
            p1 = QPointF(lab.center().x(), lab.top())
            p2 = QPointF(shape.center().x(), shape.bottom())
            align = Qt.AlignHCenter
        pen = QPen(leader_c, 2.0 if st == "sel" else 1.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if side in ("L", "R"):
            midx = p1.x() + (10 if side == "L" else -10)
            p.drawLine(p1, QPointF(midx, p1.y()))
            p.drawLine(QPointF(midx, p1.y()), p2)
        else:
            p.drawLine(p1, p2)
        f = QFont(p.font())
        f.setPointSizeF(8.8)
        f.setBold(st == "sel")
        p.setFont(f)
        p.setPen(txt_c)
        p.drawText(lab, int(align | Qt.AlignVCenter), self._labels.get(name, name))

    # -- interaction --
    def _hit_test(self, pos: QPointF):
        # discrete buttons first (so the wheel wins over the click area), then
        # the big click regions, then the labels.
        small = [n for n in self._hits if self.BUTTONS[n][5] != "click"]
        clicks = [n for n in self._hits if self.BUTTONS[n][5] == "click"]
        for n in small:
            if self._hits[n][0].contains(pos):
                return n
        for n in clicks:
            if self._hits[n][0].contains(pos) and self._body_path.contains(pos):
                return n
        for n in self._hits:
            if self._hits[n][1].contains(pos):
                return n
        return None

    def mouseMoveEvent(self, e):
        name = self._hit_test(e.position())
        if name != self._hover:
            self._hover = name
            self.setCursor(Qt.PointingHandCursor if name else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, e):
        name = self._hit_test(e.position())
        if name:
            self._selected = name
            self.update()
            self.selected.emit(name)

    def leaveEvent(self, _):
        if self._hover is not None:
            self._hover = None
            self.setCursor(Qt.ArrowCursor)
            self.update()


# ---------------------------------------------------------------------
#   Photo-based mouse map (uses the user's own photos when present)
# ---------------------------------------------------------------------

class MousePhotoMap(QWidget):
    """Interactive button map drawn over real photos of the mouse (a top view
    and a left-side view). Same public API as :class:`MouseDiagram`, so the
    buttons page can use either. Each button gets a clickable pin; clicking it
    selects the button and highlights the pin.

    The photos are the user's own pictures of their own device, shipped under
    the repo's MIT licence — so this stays copyright-clean.
    """

    selected = Signal(str)

    # hotspot centres as fractions (0..1) of each photo's displayed rectangle
    TOP = {
        "left":          (0.3652, 0.1177),
        "right":         (0.7195, 0.1111),
        "middle":        (0.5466, 0.1892),
        "fin_left":      (0.5121, 0.4696),
        "fin_right":     (0.5963, 0.4696),
        "left_forward":  (0.1615, 0.1083),
        "left_back":     (0.1140, 0.1970),
        "right_forward": (0.8750, 0.1150),
        "right_back":    (0.9000, 0.2050),
    }
    SIDE = {
        "thumb_paddle_up":   (0.4432, 0.1471),
        "thumb_paddle_down": (0.4419, 0.2731),
        "thumb_forward":     (0.3254, 0.3842),
        "thumb_back":        (0.5750, 0.3391),
        "thumb_pedal":       (0.4956, 0.9094),
    }
    # Optional leader labels (button → label anchor). Buttons not listed show
    # their name only on hover; listed ones draw a line to a placed label.
    LEADERS = {
        "left":              (0.3647, 0.0528),
        "right":             (0.6975, 0.0356),
        "middle":            (0.5484, 0.2632),
        "fin_left":          (0.3712, 0.4762),
        "fin_right":         (0.7472, 0.4669),
        "left_forward":      (0.0772, 0.0554),
        "left_back":         (0.0513, 0.1454),
        "right_forward":     (0.9353, 0.0660),
        "right_back":        (0.9872, 0.1652),
        "thumb_paddle_up":   (0.4396, 0.0332),
        "thumb_paddle_down": (0.4469, 0.4317),
        "thumb_forward":     (0.2726, 0.4931),
        "thumb_back":        (0.6372, 0.4624),
        "thumb_pedal":       (0.4977, 0.7417),
    }

    def __init__(self, buttons, top_path, side_path, parent=None):
        super().__init__(parent)
        self._labels = {name: label for name, label in buttons}
        self._assign: dict[str, str] = {}
        self._selected: str | None = None
        self._hover: str | None = None
        self._hits: dict = {}
        self._label_boxes: dict = {}
        self._top = QPixmap(str(top_path))
        self._side = QPixmap(str(side_path))
        self._pins = dict(self.TOP); self._pins.update(self.SIDE)
        self._photo = {n: "top" for n in self.TOP}
        self._photo.update({n: "side" for n in self.SIDE})
        self._labelpos = {n: None for n in self._pins}
        for n, lp in self.LEADERS.items():
            px, py = self._pins.get(n, lp)
            if abs(lp[0] - px) > 0.012 or abs(lp[1] - py) > 0.012:
                self._labelpos[n] = (lp[0], lp[1])
        self._load_map(top_path)        # optional assets/button_map.json override
        self.setMinimumSize(360, 520)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _load_map(self, top_path):
        """Override pin/label positions from assets/button_map.json if present."""
        try:
            mp = os.path.join(os.path.dirname(str(top_path)), "button_map.json")
            if not os.path.exists(mp):
                return
            with open(mp, encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception:
            return
        for name, e in raw.items():
            if name not in self._pins or not isinstance(e, dict):
                continue
            pin = e.get("pin")
            if pin:
                self._pins[name] = (float(pin[0]), float(pin[1]))
            lab = e.get("label")
            if lab:
                lx, ly = float(lab[0]), float(lab[1])
                px, py = self._pins[name]
                far = abs(lx - px) > 0.012 or abs(ly - py) > 0.012
                self._labelpos[name] = (lx, ly) if far else None

    # -- public API (mirrors MouseDiagram) --
    def set_selected(self, name):
        if name != self._selected:
            self._selected = name
            self.update()

    def set_assignments(self, mapping):
        self._assign = dict(mapping)
        self.update()

    # -- layout --
    @staticmethod
    def _fit(pm: QPixmap, x, y, maxw, maxh) -> QRectF:
        if pm.isNull() or pm.height() == 0:
            return QRectF(x, y, maxw, maxh)
        ar = pm.width() / pm.height()
        w, h = maxw, maxw / ar
        if h > maxh:
            h, w = maxh, maxh * ar
        return QRectF(x, y, w, h)

    def _compute(self):
        # top photo (portrait) on the left, side photo (landscape) upper-right —
        # same arrangement as the calibration sandbox, so placements match.
        w, h = self.width(), self.height()
        gap = 0.025 * w
        top_rect = self._fit(self._top, 0.015 * w, 0.03 * h, 0.52 * w, 0.94 * h)
        sx = top_rect.right() + gap
        side_rect = self._fit(self._side, sx, 0.06 * h, 0.985 * w - sx, 0.42 * h)
        self._unit = top_rect.width()
        rects = {"top": top_rect, "side": side_rect}
        hits = {}
        for name in self._pins:
            if name not in self._labels:
                continue
            rect = rects[self._photo[name]]
            px, py = self._pins[name]
            pin = QPointF(rect.x() + px * rect.width(), rect.y() + py * rect.height())
            lab = None
            lp = self._labelpos.get(name)
            if lp is not None:
                lab = QPointF(rect.x() + lp[0] * rect.width(),
                              rect.y() + lp[1] * rect.height())
            hits[name] = (pin, lab)
        return top_rect, side_rect, hits

    def _radius(self):
        return min(max(getattr(self, "_unit", 320.0) * 0.018, 6.0), 10.0)

    def _state(self, name):
        if name == self._selected:
            return "sel"
        if name == self._hover:
            return "hov"
        return "off"

    # -- painting --
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._render(p)
        p.end()

    def _render(self, p: QPainter):
        """Draw photos + pins + leaders + labels. Shared with the sandbox so
        the calibration tool is pixel-for-pixel WYSIWYG with the app."""
        top_rect, side_rect, self._hits = self._compute()
        self._label_boxes = {}
        if not self._top.isNull():
            p.drawPixmap(top_rect, self._top, QRectF(self._top.rect()))
        if not self._side.isNull():
            p.drawPixmap(side_rect, self._side, QRectF(self._side.rect()))
        r = self._radius()
        order = [n for n in self._hits if n not in (self._hover, self._selected)]
        order += [n for n in (self._hover, self._selected) if n and n in self._hits]
        for name in order:                       # leaders + pins
            pin, lab = self._hits[name]
            if lab is not None:
                self._draw_leader(p, name, pin, lab)
            self._draw_pin(p, name, pin, r)
        for name in order:                       # labels / chips on top
            pin, lab = self._hits[name]
            if lab is not None:
                self._draw_label(p, name, lab)
            elif name in (self._hover, self._selected):
                self._draw_chip(p, name, pin, r)

    def _draw_leader(self, p: QPainter, name, pin: QPointF, lab: QPointF):
        st = self._state(name)
        c = (QColor(COL["accent"]) if st == "sel"
             else QColor(COL["accentHi"]) if st == "hov"
             else QColor(255, 255, 255, 150))
        pen = QPen(c, 2.2 if st == "sel" else 1.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawLine(pin, lab)

    def _draw_pin(self, p: QPainter, name, c: QPointF, r):
        sel = name == self._selected
        hov = name == self._hover
        rr = r * (1.4 if sel else 1.18 if hov else 1.0)
        if sel:
            glow = QColor(COL["accent"]); glow.setAlpha(70)
            p.setPen(Qt.NoPen); p.setBrush(glow)
            p.drawEllipse(c, rr * 2.1, rr * 2.1)
        p.setPen(QPen(QColor("#FFFFFF"), 2.0 if (sel or hov) else 1.6))
        fill = QColor(COL["accent"])
        if not (sel or hov):
            fill.setAlpha(190)
        p.setBrush(fill)
        p.drawEllipse(c, rr, rr)
        p.setPen(Qt.NoPen); p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(c, rr * 0.34, rr * 0.34)

    def _chip_rect(self, text, center: QPointF, above_of=None):
        pt = min(max(getattr(self, "_unit", 320.0) * 0.019, 6.5), 9.2)
        f = QFont(self.font()); f.setPointSizeF(pt); f.setBold(True)
        fm = QFontMetricsF(f)
        cw, ch = fm.horizontalAdvance(text) + 16.0, fm.height() + 7.0
        x = center.x() - cw / 2
        if above_of is not None:
            y = center.y() - above_of - 7 - ch
            if y < 2:
                y = center.y() + above_of + 7
        else:
            y = center.y() - ch / 2
        x = max(2.0, min(x, self.width() - cw - 2))
        y = max(2.0, min(y, self.height() - ch - 2))
        return QRectF(x, y, cw, ch), f

    def _paint_chip(self, p: QPainter, name, rect: QRectF, font: QFont):
        st = self._state(name)
        border = (QColor(COL["accent"]) if st == "sel"
                  else QColor(COL["accentHi"]) if st == "hov"
                  else QColor(COL["border2"]))
        bg = QColor("#0E1014"); bg.setAlpha(236)
        p.setBrush(bg)
        p.setPen(QPen(border, 1.4 if st == "sel" else 1.1))
        p.drawRoundedRect(rect, 7, 7)
        p.setFont(font)
        p.setPen(QColor(COL["text"]) if st != "off" else QColor(COL["muted"]))
        p.drawText(rect, int(Qt.AlignCenter), self._labels.get(name, name))

    def _draw_chip(self, p: QPainter, name, c: QPointF, r):
        rect, font = self._chip_rect(self._labels.get(name, name), c, above_of=r)
        self._paint_chip(p, name, rect, font)
        self._label_boxes[name] = rect

    def _draw_label(self, p: QPainter, name, center: QPointF):
        rect, font = self._chip_rect(self._labels.get(name, name), center)
        self._paint_chip(p, name, rect, font)
        self._label_boxes[name] = rect

    # -- interaction --
    def _hit_test(self, pos: QPointF):
        best, best_d = None, 1e18
        for name, (pin, lab) in self._hits.items():
            d = (pos - pin).manhattanLength()
            if d < best_d:
                best, best_d = name, d
        if best is not None and best_d <= self._radius() * 2.4:
            return best
        for name, box in self._label_boxes.items():
            if box.contains(pos):
                return name
        return None

    def mouseMoveEvent(self, e):
        name = self._hit_test(e.position())
        if name != self._hover:
            self._hover = name
            self.setCursor(Qt.PointingHandCursor if name else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, e):
        name = self._hit_test(e.position())
        if name:
            self._selected = name
            self.update()
            self.selected.emit(name)

    def leaveEvent(self, _):
        if self._hover is not None:
            self._hover = None
            self.setCursor(Qt.ArrowCursor)
            self.update()


# ---------------------------------------------------------------------
#   Animated toggle switch
# ---------------------------------------------------------------------

class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)
        self._pos = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(150)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(46, 26)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def getKnob(self):
        return self._pos

    def setKnob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, getKnob, setKnob)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        track = QRectF(1, 3, self.width() - 2, h - 6)
        on_col = QColor(COL["accent"])
        off_col = QColor(COL["card2"])
        col = QColor(
            int(off_col.red() + (on_col.red() - off_col.red()) * self._pos),
            int(off_col.green() + (on_col.green() - off_col.green()) * self._pos),
            int(off_col.blue() + (on_col.blue() - off_col.blue()) * self._pos),
        )
        if not self.isEnabled():
            col = col.darker(160)
        p.setPen(QPen(QColor(COL["border2"]), 1) if self._pos < 0.5 else Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        d = h - 10
        x = track.left() + 2 + (track.width() - d - 4) * self._pos
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#F4F6FA"))
        p.drawEllipse(QRectF(x, track.top() + 2, d, d))


# ---------------------------------------------------------------------
#   Card container
# ---------------------------------------------------------------------

class Card(QFrame):
    def __init__(self, title: str | None = None, parent=None, shadow=True):
        super().__init__(parent)
        self.setObjectName("card")
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(16, 14, 16, 16)
        self._v.setSpacing(12)
        if title:
            t = QLabel(title.upper())
            t.setObjectName("cardTitle")
            self._v.addWidget(t)
        if shadow:
            eff = QGraphicsDropShadowEffect(self)
            eff.setBlurRadius(24)
            eff.setColor(QColor(0, 0, 0, 110))
            eff.setOffset(0, 4)
            self.setGraphicsEffect(eff)

    def addWidget(self, w, *a):
        self._v.addWidget(w, *a)

    def addLayout(self, lay, *a):
        self._v.addLayout(lay, *a)

    def addSpacing(self, n):
        self._v.addSpacing(n)

    def addStretch(self, n=1):
        self._v.addStretch(n)

    def body(self):
        return self._v


# ---------------------------------------------------------------------
#   Nav rail button
# ---------------------------------------------------------------------

class NavButton(QPushButton):
    def __init__(self, icon_name: str, text: str, parent=None):
        # Escape '&' so Qt does not treat it as a mnemonic accelerator.
        super().__init__(text.replace("&", "&&"), parent)
        self.icon_name = icon_name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("nav")
        self.setIconSize(QSize(22, 22))
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggled.connect(self._refresh_icon)
        self._refresh_icon(self.isChecked())

    def _refresh_icon(self, checked):
        color = COL["accent"] if checked else COL["muted"]
        self.setIcon(make_icon(self.icon_name, color, 22))


# ---------------------------------------------------------------------
#   Color wheel  (HSV ring + sat/value square)  — ported, proven
# ---------------------------------------------------------------------

class ColorWheel(QWidget):
    colorChanged = Signal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(248, 248)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._color = QColor(255, 0, 0)
        self._dragging = None

    def color(self) -> QColor:
        return QColor(self._color)

    def setColor(self, c: QColor, emit: bool = True):
        if c == self._color:
            return
        self._color = QColor(c)
        self.update()
        if emit:
            self.colorChanged.emit(self._color)

    def _geom(self):
        r = min(self.width(), self.height()) - 12
        cx = self.width() / 2
        cy = self.height() / 2
        outer = r / 2
        inner = outer * 0.78
        return cx, cy, outer, inner

    def _sv_rect(self):
        cx, cy, _, inner = self._geom()
        side = inner * math.sqrt(2) * 0.85
        return QRectF(cx - side / 2, cy - side / 2, side, side)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, outer, inner = self._geom()

        grad = QConicalGradient(cx, cy, 0)
        for i in range(13):
            grad.setColorAt(i / 12.0, QColor.fromHsv(int(i / 12.0 * 359), 255, 255))
        ring = QPainterPath()
        ring.addEllipse(cx - outer, cy - outer, 2 * outer, 2 * outer)
        inner_path = QPainterPath()
        inner_path.addEllipse(cx - inner, cy - inner, 2 * inner, 2 * inner)
        ring = ring.subtracted(inner_path)
        p.fillPath(ring, QBrush(grad))

        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), outer + 0.5, outer + 0.5)
        p.drawEllipse(QPointF(cx, cy), inner - 0.5, inner - 0.5)

        h = self._color.hue() if self._color.hue() >= 0 else 0
        ang = math.radians(-h)
        mid = (outer + inner) / 2
        hx = cx + math.cos(ang) * mid
        hy = cy + math.sin(ang) * mid
        rh = (outer - inner) / 2 - 2
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 180), 3))
        p.drawEllipse(QPointF(hx, hy), rh, rh)
        p.setPen(QPen(Qt.white, 1.6))
        p.drawEllipse(QPointF(hx, hy), rh, rh)

        rect = self._sv_rect()
        base = QColor.fromHsv(h, 255, 255)
        p.save()
        sv_path = QPainterPath()
        sv_path.addRoundedRect(rect, 6, 6)
        p.setClipPath(sv_path)
        gx = QLinearGradient(rect.left(), 0, rect.right(), 0)
        gx.setColorAt(0, Qt.white)
        gx.setColorAt(1, base)
        p.fillRect(rect, gx)
        gy = QLinearGradient(0, rect.top(), 0, rect.bottom())
        gy.setColorAt(0, QColor(0, 0, 0, 0))
        gy.setColorAt(1, Qt.black)
        p.fillRect(rect, gy)
        p.restore()
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        s = self._color.saturationF()
        v = self._color.valueF()
        sx = rect.left() + s * rect.width()
        sy = rect.top() + (1 - v) * rect.height()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 200), 3))
        p.drawEllipse(QPointF(sx, sy), 7, 7)
        p.setPen(QPen(Qt.white, 1.6))
        p.drawEllipse(QPointF(sx, sy), 7, 7)

    def mousePressEvent(self, ev):
        self._handle_mouse(ev.position(), press=True)

    def mouseMoveEvent(self, ev):
        if self._dragging:
            self._handle_mouse(ev.position(), press=False)

    def mouseReleaseEvent(self, ev):
        self._dragging = None

    def _handle_mouse(self, pos: QPointF, press: bool):
        cx, cy, outer, inner = self._geom()
        dx = pos.x() - cx
        dy = pos.y() - cy
        d = math.hypot(dx, dy)
        rect = self._sv_rect()
        if press:
            if inner <= d <= outer:
                self._dragging = "hue"
            elif rect.contains(pos):
                self._dragging = "sv"
            else:
                self._dragging = None
        if self._dragging == "hue":
            angle = math.degrees(math.atan2(-dy, dx))
            if angle < 0:
                angle += 360
            hh = int(angle) % 360
            self.setColor(QColor.fromHsv(hh, max(self._color.saturation(), 1),
                                         max(self._color.value(), 1)))
        elif self._dragging == "sv":
            sx = max(0.0, min(1.0, (pos.x() - rect.left()) / rect.width()))
            sy = max(0.0, min(1.0, (pos.y() - rect.top()) / rect.height()))
            hh = self._color.hue() if self._color.hue() >= 0 else 0
            self.setColor(QColor.fromHsvF(hh / 360.0, sx, 1 - sy))


class Swatch(QPushButton):
    def __init__(self, color: QColor | None = None, size: int = 30, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self._color = color
        self._refresh()

    def color(self):
        return self._color

    def setColor(self, c):
        self._color = c
        self._refresh()

    def _refresh(self):
        if self._color is None:
            self.setStyleSheet(
                f"QPushButton {{ background:{COL['content']};"
                f" border:1px dashed {COL['border2']}; border-radius:7px; }}")
        else:
            c = self._color.name()
            self.setStyleSheet(
                f"QPushButton {{ background:{c};"
                f" border:1px solid rgba(255,255,255,40); border-radius:7px; }}"
                f"QPushButton:hover {{ border:2px solid white; }}"
                f"QPushButton:pressed {{ border:2px solid {COL['accent']}; }}")


# ---------------------------------------------------------------------
#   Key-name mappings (Qt key / pynput key -> tyon_rgb HID_KEY names)
# ---------------------------------------------------------------------

_QT_SPECIAL = {
    Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "kp_enter",
    Qt.Key_Escape: "escape", Qt.Key_Tab: "tab", Qt.Key_Backspace: "backspace",
    Qt.Key_Delete: "delete", Qt.Key_Insert: "insert", Qt.Key_Home: "home",
    Qt.Key_End: "end", Qt.Key_PageUp: "pageup", Qt.Key_PageDown: "pagedown",
    Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down",
    Qt.Key_Minus: "minus", Qt.Key_Equal: "equal", Qt.Key_BracketLeft: "leftbracket",
    Qt.Key_BracketRight: "rightbracket", Qt.Key_Backslash: "backslash",
    Qt.Key_Semicolon: "semicolon", Qt.Key_Apostrophe: "apostrophe",
    Qt.Key_QuoteLeft: "grave", Qt.Key_Comma: "comma", Qt.Key_Period: "period",
    Qt.Key_Slash: "slash", Qt.Key_CapsLock: "capslock",
}
for _i in range(1, 13):
    _QT_SPECIAL[getattr(Qt, f"Key_F{_i}")] = f"f{_i}"


def qt_key_to_hid(key: int) -> str | None:
    """Map a Qt key code to a tyon_rgb HID_KEY name, or None if unsupported."""
    if key in _QT_SPECIAL:
        return _QT_SPECIAL[key]
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(ord("a") + (key - Qt.Key_A))
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(ord("0") + (key - Qt.Key_0))
    return None


_PYNPUT_NAME = {
    "alt": "l_alt", "alt_l": "l_alt", "alt_r": "r_alt", "alt_gr": "r_alt",
    "ctrl": "l_ctrl", "ctrl_l": "l_ctrl", "ctrl_r": "r_ctrl",
    "shift": "l_shift", "shift_l": "l_shift", "shift_r": "r_shift",
    "cmd": "l_win", "cmd_l": "l_win", "cmd_r": "r_win",
    "backspace": "backspace", "caps_lock": "capslock", "delete": "delete",
    "down": "down", "end": "end", "enter": "enter", "esc": "escape",
    "home": "home", "insert": "insert", "left": "left", "page_down": "pagedown",
    "page_up": "pageup", "print_screen": "printscreen", "right": "right",
    "scroll_lock": "scrolllock", "space": "space", "tab": "tab", "up": "up",
    "num_lock": "numlock", "pause": "pause",
}
for _i in range(1, 13):
    _PYNPUT_NAME[f"f{_i}"] = f"f{_i}"

_PYNPUT_PUNCT = {
    "-": "minus", "=": "equal", "[": "leftbracket", "]": "rightbracket",
    "\\": "backslash", ";": "semicolon", "'": "apostrophe", "`": "grave",
    ",": "comma", ".": "period", "/": "slash", " ": "space",
}


def pynput_str_to_hid(s: str) -> str | None:
    """Map a tyon_input.key_to_str() value to a tyon_rgb HID_KEY name."""
    if s in _PYNPUT_NAME:
        return _PYNPUT_NAME[s]
    if len(s) == 1:
        ch = s.lower()
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            return ch
        if ch in _PYNPUT_PUNCT:
            return _PYNPUT_PUNCT[ch]
    return None


# ---------------------------------------------------------------------
#   Theme
# ---------------------------------------------------------------------

def apply_theme(app):
    from PySide6.QtGui import QPalette
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(COL["bg"]))
    pal.setColor(QPalette.WindowText, QColor(COL["text"]))
    pal.setColor(QPalette.Base, QColor(COL["card"]))
    pal.setColor(QPalette.AlternateBase, QColor(COL["card2"]))
    pal.setColor(QPalette.ToolTipBase, QColor(COL["card2"]))
    pal.setColor(QPalette.ToolTipText, QColor(COL["text"]))
    pal.setColor(QPalette.Text, QColor(COL["text"]))
    pal.setColor(QPalette.Button, QColor(COL["card2"]))
    pal.setColor(QPalette.ButtonText, QColor(COL["text"]))
    pal.setColor(QPalette.Highlight, QColor(COL["accent"]))
    pal.setColor(QPalette.HighlightedText, Qt.white)
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(COL["faint"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(COL["faint"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(COL["faint"]))
    app.setPalette(pal)
    app.setStyleSheet(_QSS.format(**COL))


_QSS = """
* {{ font-family: "Segoe UI Variable", "Segoe UI", sans-serif; }}
QMainWindow, QDialog {{ background: {bg}; }}
QWidget#content {{ background: {content}; }}
QWidget#rail {{ background: {rail}; border-right: 1px solid {border}; }}
QWidget#header {{ background: {rail}; border-bottom: 1px solid {border}; }}

QLabel {{ color: {text}; background: transparent; }}
QLabel#h1 {{ font-size: 17pt; font-weight: 700; color: #F4F6FA; }}
QLabel#h2 {{ font-size: 13pt; font-weight: 700; color: #F4F6FA; }}
QLabel#sub {{ font-size: 9.5pt; color: {muted}; }}
QLabel#cardTitle {{ font-size: 8.5pt; font-weight: 800; letter-spacing: 1.6px;
                    color: {muted}; }}
QLabel#fieldLabel {{ color: {muted}; font-size: 9.5pt; }}
QLabel#value {{ color: #D5D9E0; }}
QLabel#status {{ color: {muted}; }}
QLabel#statusErr {{ color: {danger}; }}
QLabel#statusOk {{ color: {ok}; }}
QLabel#pill {{ color: {muted}; background: {card2}; border: 1px solid {border};
              border-radius: 10px; padding: 2px 10px; font-size: 9pt; }}
QLabel#note {{ color: {muted}; font-size: 9pt; }}
QLabel#warn {{ color: {warn}; font-size: 9pt; }}

QFrame#card {{ background: {card}; border: 1px solid {border}; border-radius: 12px; }}
QFrame#divider {{ background: {border}; }}

QPushButton {{
    background: {card2}; color: {text}; border: 1px solid {border2};
    border-radius: 8px; padding: 8px 14px; min-height: 18px;
}}
QPushButton:hover {{ background: #242935; border-color: #3c4453; }}
QPushButton:pressed {{ background: #15181f; }}
QPushButton:disabled {{ color: {faint}; background: {card}; border-color: {border}; }}

QPushButton#primary {{
    background: {accent}; color: white; border: 1px solid {accent};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {accentHi}; border-color: {accentHi}; }}
QPushButton#primary:pressed {{ background: {accentLo}; }}
QPushButton#primary:disabled {{ background: #2b3344; border-color: #2b3344; color: {faint}; }}

QPushButton#danger {{ background: transparent; color: {danger}; border: 1px solid #5a2a2e; }}
QPushButton#danger:hover {{ background: #2a1517; }}

QPushButton#ghost {{ background: transparent; border: 1px solid {border2}; }}
QPushButton#ghost:hover {{ background: {card2}; }}

QPushButton#nav {{
    background: transparent; border: none; border-radius: 9px;
    text-align: left; padding: 8px 12px; margin: 2px 10px;
    color: {muted}; font-size: 10.5pt; font-weight: 600;
}}
QPushButton#nav:hover {{ background: rgba(255,255,255,0.04); color: {text}; }}
QPushButton#nav:checked {{ background: rgba(90,141,238,0.14); color: #F4F6FA; }}

QComboBox, QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {card2}; color: {text}; border: 1px solid {border2};
    border-radius: 8px; padding: 6px 10px; min-height: 18px;
    selection-background-color: {accent};
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border-color: #44506a; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none; width: 0; height: 0;
    border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 6px solid {muted}; margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {card2}; color: {text}; border: 1px solid {border2};
    border-radius: 8px; outline: none;
    selection-background-color: {accent}; selection-color: white;
    padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QCheckBox {{ color: {text}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {border2}; background: {card2};
}}
QCheckBox::indicator:checked {{
    background: {accent}; border-color: {accent};
    image: none;
}}
QRadioButton {{ color: {text}; spacing: 8px; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 9px;
    border: 1px solid {border2}; background: {card2};
}}
QRadioButton::indicator:checked {{ border: 5px solid {accent}; background: white; }}

QSlider::groove:horizontal {{ height: 4px; background: {card2}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: white; width: 16px; height: 16px; margin: -7px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ background: #E9EDF5; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border2}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #475066; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QListWidget {{
    background: {card2}; border: 1px solid {border2}; border-radius: 8px;
    padding: 4px; outline: none; color: {text};
}}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; }}
QListWidget::item:selected {{ background: rgba(90,141,238,0.18); color: #F4F6FA; }}
QListWidget::item:hover:!selected {{ background: rgba(255,255,255,0.04); }}

QTableWidget {{
    background: {card2}; alternate-background-color: #20252f;
    border: 1px solid {border}; border-radius: 8px; gridline-color: {border};
    color: {text}; selection-background-color: {accent}; selection-color: white;
}}
QHeaderView::section {{
    background: {card}; color: {muted}; border: none;
    border-bottom: 1px solid {border}; padding: 6px 8px; font-weight: 600;
}}
QTableWidget::item {{ padding: 4px 6px; }}

QToolTip {{
    background: {card2}; color: {text}; border: 1px solid {border2};
    border-radius: 6px; padding: 5px 8px;
}}
"""
