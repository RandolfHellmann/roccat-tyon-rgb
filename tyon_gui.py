"""Roccat Tyon RGB GUI (PySide6, dark theme).

Color picker = custom HSV wheel + saturation/value square + RGB/Hex inputs
+ standard color palette + 5-slot recent colors persisted to JSON.
Tyon-specific controls: profile selector, zones, effect, speed, Apply.
"""

import json
import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QLinearGradient, QPainter, QPainterPath,
    QPalette, QPen, QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QRadioButton, QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

import tyon_rgb as tyon

APP_DIR = Path(__file__).resolve().parent
RECENT_PATH = APP_DIR / "recent.json"
RECENT_MAX = 5

STANDARD_COLORS = [
    ("Rot",     "#FF0000"),
    ("Orange",  "#FF7F00"),
    ("Gelb",    "#FFD800"),
    ("Grün",    "#00C800"),
    ("Cyan",    "#00C8FF"),
    ("Blau",    "#0040FF"),
    ("Lila",    "#7F00FF"),
    ("Magenta", "#FF00FF"),
    ("Weiß",    "#FFFFFF"),
]

EFFECT_LABELS = [
    ("Volltonlicht",       "solid"),
    ("Blinken",            "blink"),
    ("Atmen",              "breathe"),
    ("Herzschlag",         "heartbeat"),
    ("Aus",                "off"),
]

# Presets: (label, hex, effect_key, zone_idx, brightness)
#   zone_idx: 0=Beide, 1=Mausrad, 2=Boden
PRESETS = [
    ("MBUX Sport", "#FF2A0A", "solid", 0, 100),
]


# ---------------------------------------------------------------------
#   Color wheel widget
# ---------------------------------------------------------------------

class ColorWheel(QWidget):
    """HSV color wheel: outer ring picks hue, inner square picks sat+value."""

    colorChanged = Signal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._color = QColor(255, 0, 0)
        self._dragging = None  # "hue" or "sv"

    def color(self) -> QColor:
        return QColor(self._color)

    def setColor(self, c: QColor, emit: bool = True):
        if c == self._color:
            return
        self._color = QColor(c)
        if self._color.saturation() == 0 and self._color.value() > 0:
            # pure grey — keep current hue to avoid jumping the picker
            pass
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

        # Hue ring (conical gradient)
        grad = QConicalGradient(cx, cy, 0)
        for i in range(13):
            grad.setColorAt(i / 12.0, QColor.fromHsv(int(i / 12.0 * 359), 255, 255))
        ring = QPainterPath()
        ring.addEllipse(cx - outer, cy - outer, 2 * outer, 2 * outer)
        inner_path = QPainterPath()
        inner_path.addEllipse(cx - inner, cy - inner, 2 * inner, 2 * inner)
        ring = ring.subtracted(inner_path)
        p.fillPath(ring, QBrush(grad))

        # Subtle inner + outer rim
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), outer + 0.5, outer + 0.5)
        p.drawEllipse(QPointF(cx, cy), inner - 0.5, inner - 0.5)

        # Hue selector — crisp double-stroked ring at mid-ring position
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

        # SV square — rounded corners feel a bit more refined
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

        # SV selector — crisp double-stroked ring
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
            h = int(angle) % 360
            new = QColor.fromHsv(h, max(self._color.saturation(), 1),
                                 max(self._color.value(), 1))
            self.setColor(new)
        elif self._dragging == "sv":
            sx = max(0.0, min(1.0, (pos.x() - rect.left()) / rect.width()))
            sy = max(0.0, min(1.0, (pos.y() - rect.top()) / rect.height()))
            h = self._color.hue() if self._color.hue() >= 0 else 0
            new = QColor.fromHsvF(h / 360.0, sx, 1 - sy)
            self.setColor(new)


# ---------------------------------------------------------------------
#   Swatch button
# ---------------------------------------------------------------------

class Swatch(QPushButton):
    def __init__(self, color: QColor | None = None, size: int = 28, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self._color = color
        self._refresh()

    def color(self) -> QColor | None:
        return self._color

    def setColor(self, c: QColor | None):
        self._color = c
        self._refresh()

    def _refresh(self):
        if self._color is None:
            self.setStyleSheet(
                "QPushButton {"
                "  background: #14171d;"
                "  border: 1px dashed #2a2f3a;"
                "  border-radius: 7px;"
                "}"
            )
        else:
            c = self._color.name()
            self.setStyleSheet(
                f"QPushButton {{"
                f"  background: {c};"
                f"  border: 1px solid rgba(255,255,255,40);"
                f"  border-radius: 7px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  border: 2px solid white;"
                f"}}"
                f"QPushButton:pressed {{"
                f"  border: 2px solid #3b82f6;"
                f"}}"
            )


# ---------------------------------------------------------------------
#   Main window
# ---------------------------------------------------------------------

class TyonWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Roccat Tyon RGB")
        self.setFixedSize(1020, 700)
        self._recent: list[str] = self._load_recent()
        self._syncing = False  # guard for two-way binding

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(20)

        root.addLayout(self._build_left(), 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color:#1f242d; background:#1f242d;")
        sep.setFixedWidth(1)
        root.addWidget(sep)

        root.addLayout(self._build_right(), 0)

        self._set_color(QColor("#FF00FF"))
        self._refresh_recent_swatches()

    # ---- left side: color picker --------------------------------------

    def _build_left(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(14)

        # Wheel
        self.wheel = ColorWheel()
        self.wheel.colorChanged.connect(self._on_wheel_changed)
        col.addWidget(self.wheel, 1)

        # Hex + RGB row
        inputs = QHBoxLayout()
        inputs.setSpacing(10)

        self.preview = QLabel()
        self.preview.setFixedSize(44, 44)
        self.preview.setToolTip("Vorschau (Farbe × Helligkeit)")
        inputs.addWidget(self.preview)

        hex_lbl = QLabel("HEX")
        hex_lbl.setStyleSheet("color:#9ca3af; font-size:9pt; font-weight:600;")
        inputs.addWidget(hex_lbl)
        self.hex_in = QLineEdit()
        self.hex_in.setMaxLength(7)
        self.hex_in.setFixedWidth(100)
        rx = QRegularExpressionValidator(r"^#?[0-9A-Fa-f]{0,6}$")
        self.hex_in.setValidator(rx)
        self.hex_in.editingFinished.connect(self._on_hex_changed)
        inputs.addWidget(self.hex_in)

        for label, key in (("R", "r"), ("G", "g"), ("B", "b")):
            chan_lbl = QLabel(label)
            chan_lbl.setStyleSheet("color:#9ca3af; font-size:9pt; font-weight:600;")
            inputs.addWidget(chan_lbl)
            sb = QSpinBox()
            sb.setRange(0, 255)
            sb.setFixedWidth(64)
            sb.setButtonSymbols(QSpinBox.NoButtons)
            sb.setAlignment(Qt.AlignCenter)
            sb.valueChanged.connect(self._on_rgb_changed)
            setattr(self, f"in_{key}", sb)
            inputs.addWidget(sb)

        inputs.addStretch(1)
        col.addLayout(inputs)

        # Brightness row
        br_row = QHBoxLayout()
        br_row.setSpacing(10)
        br_label = QLabel("HELLIGKEIT")
        br_label.setStyleSheet(
            "color:#9ca3af; font-size:9pt; font-weight:700; letter-spacing:1.2px;"
        )
        br_label.setMinimumWidth(84)
        br_row.addWidget(br_label)
        self.brightness = QSlider(Qt.Horizontal)
        self.brightness.setObjectName("brightness")
        self.brightness.setRange(1, 100)
        self.brightness.setValue(100)
        self.brightness.setTickPosition(QSlider.NoTicks)
        self.brightness.valueChanged.connect(self._on_brightness_changed)
        br_row.addWidget(self.brightness, 1)
        self.brightness_value = QLabel("100 %")
        self.brightness_value.setMinimumWidth(50)
        self.brightness_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.brightness_value.setStyleSheet("color:#d1d5db; font-variant-numeric: tabular-nums;")
        br_row.addWidget(self.brightness_value)
        col.addLayout(br_row)

        # Standard palette
        std_box = QGroupBox("STANDARDFARBEN")
        std_layout = QHBoxLayout(std_box)
        std_layout.setContentsMargins(2, 2, 2, 2)
        std_layout.setSpacing(8)
        for name, hex_ in STANDARD_COLORS:
            sw = Swatch(QColor(hex_), size=34)
            sw.clicked.connect(lambda _=False, h=hex_: self._set_color(QColor(h)))
            sw.setToolTip(f"{name} · {hex_}")
            std_layout.addWidget(sw)
        std_layout.addStretch(1)
        col.addWidget(std_box)

        # Presets (color + effect + zone in one click)
        preset_box = QGroupBox("PRESETS")
        preset_layout = QHBoxLayout(preset_box)
        preset_layout.setContentsMargins(2, 2, 2, 2)
        preset_layout.setSpacing(8)
        for name, hex_, effect, zone, bright in PRESETS:
            btn = QPushButton(name)
            btn.setFixedHeight(32)
            btn.setCursor(Qt.PointingHandCursor)
            # Tinted button matching the preset color
            c = QColor(hex_)
            # darker tone for hover/pressed to keep contrast
            btn.setStyleSheet(
                f"QPushButton {{ background:{c.name()}; color:#fff; "
                f"border:1px solid #444; border-radius:6px; "
                f"padding:0 14px; font-weight:600; }}"
                f"QPushButton:hover {{ border:1px solid #fff; }}"
                f"QPushButton:pressed {{ background:{c.darker(120).name()}; }}"
            )
            eff_label = next((lbl for lbl, k in EFFECT_LABELS if k == effect), effect)
            btn.setToolTip(
                f"{hex_} · {eff_label} · {('Beide', 'Mausrad', 'Boden')[zone]}"
            )
            btn.clicked.connect(
                lambda _=False, h=hex_, e=effect, z=zone, b=bright:
                self._apply_preset(h, e, z, b)
            )
            preset_layout.addWidget(btn)
        preset_layout.addStretch(1)
        col.addWidget(preset_box)

        # Recent
        rec_box = QGroupBox("ZULETZT VERWENDET")
        rec_layout = QHBoxLayout(rec_box)
        rec_layout.setContentsMargins(2, 2, 2, 2)
        rec_layout.setSpacing(8)
        self.recent_swatches: list[Swatch] = []
        for _ in range(RECENT_MAX):
            sw = Swatch(None, size=34)
            sw.clicked.connect(self._on_recent_clicked)
            rec_layout.addWidget(sw)
            self.recent_swatches.append(sw)
        rec_layout.addStretch(1)
        col.addWidget(rec_box)

        return col

    # ---- right side: tyon controls ------------------------------------

    def _build_right(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(14)
        col.setContentsMargins(4, 0, 0, 0)

        title = QLabel("Roccat Tyon")
        title.setObjectName("title")
        col.addWidget(title)

        subtitle = QLabel("Onboard-Profil schreiben — bleibt auch nach Aus- und Einstecken erhalten.")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        col.addWidget(subtitle)

        col.addSpacing(4)

        # Profile
        prof_box = QGroupBox("PROFIL")
        prof_layout = QVBoxLayout(prof_box)
        prof_layout.setContentsMargins(2, 2, 2, 2)
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Aktives Profil (auto)", None)
        for i in range(tyon.PROFILE_NUM):
            self.profile_combo.addItem(f"Profil {i + 1}", i)
        prof_layout.addWidget(self.profile_combo)
        col.addWidget(prof_box)

        # Zone
        zone_box = QGroupBox("ZONE")
        zone_layout = QHBoxLayout(zone_box)
        zone_layout.setContentsMargins(2, 2, 2, 2)
        zone_layout.setSpacing(16)
        self.zone_group = QButtonGroup(self)
        for i, label in enumerate(("Beide", "Mausrad", "Boden")):
            rb = QRadioButton(label)
            self.zone_group.addButton(rb, i)
            zone_layout.addWidget(rb)
        zone_layout.addStretch(1)
        self.zone_group.button(0).setChecked(True)
        col.addWidget(zone_box)

        # Effect
        eff_box = QGroupBox("EFFEKT")
        eff_layout = QGridLayout(eff_box)
        eff_layout.setContentsMargins(2, 2, 2, 2)
        eff_layout.setHorizontalSpacing(12)
        eff_layout.setVerticalSpacing(10)
        eff_layout.setColumnStretch(1, 1)

        mode_lbl = QLabel("Modus")
        mode_lbl.setStyleSheet("color:#9ca3af;")
        eff_layout.addWidget(mode_lbl, 0, 0)
        self.effect_combo = QComboBox()
        for label, key in EFFECT_LABELS:
            self.effect_combo.addItem(label, key)
        eff_layout.addWidget(self.effect_combo, 0, 1)

        speed_lbl = QLabel("Tempo")
        speed_lbl.setStyleSheet("color:#9ca3af;")
        eff_layout.addWidget(speed_lbl, 1, 0)
        speed_row = QHBoxLayout()
        speed_row.setSpacing(10)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(1, 3)
        self.speed_slider.setValue(2)
        self.speed_slider.setTickPosition(QSlider.NoTicks)
        speed_row.addWidget(self.speed_slider, 1)
        self.speed_value = QLabel("2")
        self.speed_value.setMinimumWidth(20)
        self.speed_value.setAlignment(Qt.AlignCenter)
        self.speed_value.setStyleSheet("color:#d1d5db; font-variant-numeric: tabular-nums;")
        speed_row.addWidget(self.speed_value)
        self.speed_slider.valueChanged.connect(
            lambda v: self.speed_value.setText(str(v))
        )
        eff_layout.addLayout(speed_row, 1, 1)
        col.addWidget(eff_box)

        col.addStretch(1)

        # Apply button
        self.apply_btn = QPushButton("Auf Maus übertragen")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setMinimumHeight(46)
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(self._on_apply)
        col.addWidget(self.apply_btn)

        # Secondary buttons
        sec = QHBoxLayout()
        sec.setSpacing(8)
        read_btn = QPushButton("Aus Maus lesen")
        read_btn.setCursor(Qt.PointingHandCursor)
        read_btn.clicked.connect(self._on_read)
        sec.addWidget(read_btn)

        off_btn = QPushButton("Licht aus")
        off_btn.setCursor(Qt.PointingHandCursor)
        off_btn.clicked.connect(self._on_off)
        sec.addWidget(off_btn)
        col.addLayout(sec)

        # Status
        self.status = QLabel("Bereit.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        col.addWidget(self.status)

        return col

    # ---- color synchronization ---------------------------------------

    def _current(self) -> QColor:
        return self.wheel.color()

    def _set_color(self, c: QColor):
        if not c.isValid():
            return
        self._syncing = True
        self.wheel.setColor(c, emit=False)
        self.in_r.setValue(c.red())
        self.in_g.setValue(c.green())
        self.in_b.setValue(c.blue())
        self.hex_in.setText(c.name().upper())
        self._update_preview()
        self._syncing = False

    def _effective_color(self) -> QColor:
        c = self._current()
        f = self.brightness.value() / 100.0
        return QColor(round(c.red() * f), round(c.green() * f), round(c.blue() * f))

    def _update_preview(self):
        eff = self._effective_color()
        # Preview tile shows what the mouse will actually display
        self.preview.setStyleSheet(
            f"background:{eff.name()}; border:1px solid #2a2f3a; border-radius:8px;"
        )

    def _on_brightness_changed(self, v: int):
        self.brightness_value.setText(f"{v} %")
        self._update_preview()

    def _on_wheel_changed(self, c: QColor):
        if self._syncing:
            return
        self._set_color(c)

    def _on_rgb_changed(self, _):
        if self._syncing:
            return
        c = QColor(self.in_r.value(), self.in_g.value(), self.in_b.value())
        self._set_color(c)

    def _on_hex_changed(self):
        if self._syncing:
            return
        text = self.hex_in.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        if len(text) == 7:
            c = QColor(text)
            if c.isValid():
                self._set_color(c)
                return
        # invalid -> revert to current
        self.hex_in.setText(self._current().name().upper())

    # ---- recent colors -----------------------------------------------

    def _load_recent(self) -> list[str]:
        if not RECENT_PATH.exists():
            return []
        try:
            data = json.loads(RECENT_PATH.read_text(encoding="utf-8"))
            return [c for c in data.get("recent", []) if isinstance(c, str)][:RECENT_MAX]
        except Exception:
            return []

    def _save_recent(self):
        try:
            RECENT_PATH.write_text(
                json.dumps({"recent": self._recent}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _push_recent(self, c: QColor):
        hex_ = c.name().upper()
        if hex_ in self._recent:
            self._recent.remove(hex_)
        self._recent.insert(0, hex_)
        self._recent = self._recent[:RECENT_MAX]
        self._save_recent()
        self._refresh_recent_swatches()

    def _refresh_recent_swatches(self):
        for i, sw in enumerate(self.recent_swatches):
            if i < len(self._recent):
                sw.setColor(QColor(self._recent[i]))
                sw.setToolTip(self._recent[i])
            else:
                sw.setColor(None)
                sw.setToolTip("")

    def _on_recent_clicked(self):
        sw = self.sender()
        c = sw.color() if isinstance(sw, Swatch) else None
        if c:
            # A recent entry is the final color we wrote — reset brightness
            # so what the user sees matches what the mouse will display.
            self.brightness.setValue(100)
            self._set_color(c)

    # ---- presets -----------------------------------------------------

    def _apply_preset(self, hex_color: str, effect_key: str,
                      zone_idx: int, brightness: int):
        """Load a preset into the UI (does NOT write to the mouse — user
        still has to press 'Auf Maus übertragen' for that)."""
        self.brightness.setValue(brightness)
        self._set_color(QColor(hex_color))
        # Effect dropdown
        for idx, (_, key) in enumerate(EFFECT_LABELS):
            if key == effect_key:
                self.effect_combo.setCurrentIndex(idx)
                break
        # Zone radio group
        btn = self.zone_group.button(zone_idx)
        if btn is not None:
            btn.setChecked(True)

    # ---- tyon actions ------------------------------------------------

    def _status(self, msg: str, error: bool = False):
        self.status.setText(msg)
        self.status.setObjectName("statusError" if error else "status")
        # Re-polish so the new objectName's QSS rules take effect
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _zone_args(self, color: QColor) -> tuple:
        idx = self.zone_group.checkedId()
        rgb = (color.red(), color.green(), color.blue())
        # (wheel, bottom)
        if idx == 0:
            return rgb, rgb
        if idx == 1:
            return rgb, None
        return None, rgb

    def _on_apply(self):
        color = self._effective_color()
        wheel_rgb, bottom_rgb = self._zone_args(color)
        profile = self.profile_combo.currentData()
        effect = self.effect_combo.currentData()
        speed = self.speed_slider.value()
        try:
            dev, name = tyon.open_tyon()
        except tyon.TyonNotFoundError as e:
            QMessageBox.warning(self, "Tyon nicht gefunden", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"{e}")
            return
        try:
            if profile is None:
                profile = tyon.read_active_profile_index(dev, verbose=False)
            settings = tyon.read_profile_settings(dev, profile, verbose=False)

            if wheel_rgb is not None:
                settings[18] = 0
                settings[19], settings[20], settings[21] = wheel_rgb
                settings[22] = 0
            if bottom_rgb is not None:
                settings[23] = 1
                settings[24], settings[25], settings[26] = bottom_rgb
                settings[27] = 0

            lights_enabled = settings[14]
            if wheel_rgb is not None:
                lights_enabled |= tyon.LIGHTS_ENABLED_BIT_WHEEL
            if bottom_rgb is not None:
                lights_enabled |= tyon.LIGHTS_ENABLED_BIT_BOTTOM
            lights_enabled |= tyon.LIGHTS_ENABLED_BIT_CUSTOM_COLOR
            settings[14] = lights_enabled & 0xFF

            settings[16] = tyon.LIGHT_EFFECT[effect]
            settings[17] = max(1, min(3, speed))

            tyon.write_profile_settings(dev, settings, verbose=False)
            self._push_recent(color)
            self._status(
                f"{name}: Profil {profile + 1} aktualisiert "
                f"({color.name().upper()}, {self._effect_label(effect)})"
            )
        except Exception as e:
            QMessageBox.critical(self, "Schreibfehler", str(e))
        finally:
            dev.close()

    def _effect_label(self, key: str) -> str:
        for label, k in EFFECT_LABELS:
            if k == key:
                return label
        return key

    def _on_read(self):
        profile = self.profile_combo.currentData()
        try:
            dev, name = tyon.open_tyon()
        except tyon.TyonNotFoundError as e:
            QMessageBox.warning(self, "Tyon nicht gefunden", str(e))
            return
        try:
            if profile is None:
                profile = tyon.read_active_profile_index(dev, verbose=False)
            s = tyon.read_profile_settings(dev, profile, verbose=False)
            wheel  = QColor(s[19], s[20], s[21])
            bottom = QColor(s[24], s[25], s[26])
            effect_byte = s[16]
            effect_key = next((k for k, v in tyon.LIGHT_EFFECT.items()
                               if v == effect_byte), "solid")
            speed = s[17]

            self.profile_combo.setCurrentIndex(profile + 1)
            self.brightness.setValue(100)
            self._set_color(wheel)
            self.effect_combo.setCurrentIndex(
                [k for _, k in EFFECT_LABELS].index(effect_key)
            )
            self.speed_slider.setValue(max(1, min(3, speed)))
            self._status(
                f"{name}: Profil {profile + 1} gelesen — "
                f"Rad {wheel.name().upper()}, Boden {bottom.name().upper()}, "
                f"Effekt {self._effect_label(effect_key)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Lesefehler", str(e))
        finally:
            dev.close()

    def _on_off(self):
        profile = self.profile_combo.currentData()
        try:
            dev, name = tyon.open_tyon()
        except tyon.TyonNotFoundError as e:
            QMessageBox.warning(self, "Tyon nicht gefunden", str(e))
            return
        try:
            if profile is None:
                profile = tyon.read_active_profile_index(dev, verbose=False)
            s = tyon.read_profile_settings(dev, profile, verbose=False)
            s[14] &= ~(tyon.LIGHTS_ENABLED_BIT_WHEEL | tyon.LIGHTS_ENABLED_BIT_BOTTOM)
            s[16] = tyon.LIGHT_EFFECT["off"]
            tyon.write_profile_settings(dev, s, verbose=False)
            self._status(f"{name}: Profil {profile + 1} — Licht aus")
        except Exception as e:
            QMessageBox.critical(self, "Schreibfehler", str(e))
        finally:
            dev.close()


# ---------------------------------------------------------------------
#   Dark theme + entry point
# ---------------------------------------------------------------------

def apply_dark_theme(app: QApplication):
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#0f1115"))
    pal.setColor(QPalette.WindowText, QColor("#e5e7eb"))
    pal.setColor(QPalette.Base, QColor("#181b22"))
    pal.setColor(QPalette.AlternateBase, QColor("#1e2229"))
    pal.setColor(QPalette.ToolTipBase, QColor("#181b22"))
    pal.setColor(QPalette.ToolTipText, QColor("#e5e7eb"))
    pal.setColor(QPalette.Text, QColor("#e5e7eb"))
    pal.setColor(QPalette.Button, QColor("#1e2229"))
    pal.setColor(QPalette.ButtonText, QColor("#e5e7eb"))
    pal.setColor(QPalette.BrightText, Qt.red)
    pal.setColor(QPalette.Highlight, QColor("#3b82f6"))
    pal.setColor(QPalette.HighlightedText, Qt.white)
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#6b7280"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#6b7280"))
    app.setPalette(pal)
    app.setStyleSheet("""
        QWidget { font-family: "Segoe UI Variable", "Segoe UI", sans-serif; }

        QMainWindow { background: #0f1115; }

        QGroupBox {
            background: #14171d;
            border: 1px solid #1f242d;
            border-radius: 10px;
            margin-top: 20px;
            padding: 14px 14px 12px 14px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.4px;
            color: #9ca3af;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            top: 2px;
            padding: 0 6px;
            background: #0f1115;
        }

        QLabel { color: #e5e7eb; }
        QLabel#title    { font-size: 18pt; font-weight: 700; color: #f3f4f6; }
        QLabel#subtitle { font-size: 9pt; color: #9ca3af; }
        QLabel#status   { color: #9ca3af; padding: 6px 10px;
                          background: #14171d; border: 1px solid #1f242d;
                          border-radius: 8px; }
        QLabel#statusError { color: #fca5a5; padding: 6px 10px;
                          background: #2a1416; border: 1px solid #5a1f24;
                          border-radius: 8px; }

        QPushButton {
            background: #1e2229;
            color: #e5e7eb;
            border: 1px solid #2a2f3a;
            border-radius: 8px;
            padding: 8px 14px;
            min-height: 18px;
        }
        QPushButton:hover { background: #262b35; border-color: #3a3f4a; }
        QPushButton:pressed { background: #15181f; }

        QPushButton#primary {
            background: #3b82f6;
            color: white;
            border: 1px solid #3b82f6;
            font-weight: 700;
            padding: 12px 18px;
            min-height: 22px;
        }
        QPushButton#primary:hover { background: #60a5fa; border-color: #60a5fa; }
        QPushButton#primary:pressed { background: #2563eb; border-color: #2563eb; }

        QComboBox, QSpinBox, QLineEdit {
            background: #14171d;
            color: #f3f4f6;
            border: 1px solid #2a2f3a;
            border-radius: 6px;
            padding: 6px 8px;
            min-height: 22px;
            selection-background-color: #3b82f6;
        }
        QComboBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: #3a3f4a; }
        QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border-color: #3b82f6; }
        QComboBox::drop-down { border: none; width: 22px; }
        QComboBox QAbstractItemView {
            background: #14171d; color: #e5e7eb;
            border: 1px solid #2a2f3a; border-radius: 6px;
            selection-background-color: #3b82f6;
            padding: 4px;
        }

        QRadioButton { color: #e5e7eb; spacing: 6px; padding: 2px; }
        QRadioButton::indicator { width: 16px; height: 16px; }
        QRadioButton::indicator:unchecked {
            border: 1.5px solid #4b5563; border-radius: 8px; background: #14171d;
        }
        QRadioButton::indicator:checked {
            border: 1.5px solid #3b82f6; border-radius: 8px;
            background: qradialgradient(cx:0.5 cy:0.5 radius:0.5,
                stop:0 #3b82f6, stop:0.4 #3b82f6,
                stop:0.5 #14171d, stop:1 #14171d);
        }

        QSlider::groove:horizontal {
            height: 6px; background: #2a2f3a; border-radius: 3px;
        }
        QSlider::sub-page:horizontal {
            background: #3b82f6; border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: white; border: 2px solid #3b82f6;
            width: 14px; height: 14px; margin: -6px 0; border-radius: 9px;
        }
        QSlider::handle:horizontal:hover { border-color: #60a5fa; }

        QSlider#brightness::groove:horizontal {
            height: 10px;
            border-radius: 5px;
            background: qlineargradient(
                x1:0 y1:0 x2:1 y2:0,
                stop:0 #0a0a0a, stop:1 #e5e7eb
            );
            border: 1px solid #2a2f3a;
        }
        QSlider#brightness::sub-page:horizontal { background: transparent; }
        QSlider#brightness::add-page:horizontal { background: transparent; }
        QSlider#brightness::handle:horizontal {
            background: white; border: 2px solid #1f242d;
            width: 16px; height: 16px; margin: -5px 0; border-radius: 9px;
        }
        QSlider#brightness::handle:horizontal:hover { border-color: #3b82f6; }

        QMessageBox { background: #14171d; }
        QMessageBox QLabel { color: #e5e7eb; }
    """)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Roccat Tyon RGB")
    apply_dark_theme(app)
    win = TyonWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
