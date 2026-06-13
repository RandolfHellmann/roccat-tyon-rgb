# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Randolf Hellmann
"""Roccat Tyon — control center (PySide6).

A clean, dark, device-centric UI: lighting, pointer/DPI, button remapping,
onboard macros, and game profiles (incl. a StarCraft II build-order practice
aid). All settings are written to the mouse's onboard profile flash, so they
survive unplug and reboot.
"""
from __future__ import annotations

import os
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QRadioButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import tyon_input as tinput
import tyon_rgb as tyon
import tyon_store as store
from tyon_widgets import (
    COL, Card, ColorWheel, MouseDiagram, MouseGlyph, MousePhotoMap, NavButton,
    Swatch, ToggleSwitch, apply_theme, pynput_str_to_hid, qt_key_to_hid,
)

# ---------------------------------------------------------------------
#   Constants
# ---------------------------------------------------------------------

STANDARD_COLORS = [
    ("Rot", "#FF0000"), ("Orange", "#FF7F00"), ("Gelb", "#FFD800"),
    ("Grün", "#00C800"), ("Cyan", "#00C8FF"), ("Blau", "#0040FF"),
    ("Lila", "#7F00FF"), ("Magenta", "#FF00FF"), ("Weiß", "#FFFFFF"),
]

EFFECT_LABELS = [
    ("Volltonlicht", "solid"), ("Blinken", "blink"), ("Atmen", "breathe"),
    ("Herzschlag", "heartbeat"), ("Aus", "off"),
]

# (label, hex, effect_key, zone_idx, brightness)
PRESETS = [
    ("MBUX Sport", "#FF2A0A", "solid", 0, 100),
]

PAGES = [
    ("light", "Beleuchtung"),
    ("pointer", "Zeiger & DPI"),
    ("buttons", "Tasten"),
    ("macro", "Makros"),
    ("games", "Spielprofile"),
]


# ---------------------------------------------------------------------
#   Small layout helpers
# ---------------------------------------------------------------------

def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("fieldLabel")
    return lbl


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("divider")
    f.setFixedHeight(1)
    return f


def scroll_wrap(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setWidget(widget)
    return sa


def primary_button(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("primary")
    b.setMinimumHeight(44)
    b.setCursor(Qt.PointingHandCursor)
    return b


def ghost_button(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("ghost")
    b.setCursor(Qt.PointingHandCursor)
    return b


def restyle(w: QWidget) -> None:
    """Re-apply the stylesheet after changing a widget's objectName."""
    w.style().unpolish(w)
    w.style().polish(w)


# ---------------------------------------------------------------------
#   Friendly key labels + combo formatting
# ---------------------------------------------------------------------

KEY_LABELS = {
    "space": "Leertaste", "enter": "Enter", "kp_enter": "Enter (Num)",
    "escape": "Esc", "tab": "Tab", "backspace": "Rücktaste", "delete": "Entf",
    "insert": "Einfg", "home": "Pos1", "end": "Ende", "pageup": "Bild ↑",
    "pagedown": "Bild ↓", "left": "←", "right": "→", "up": "↑", "down": "↓",
    "capslock": "Feststell", "printscreen": "Druck", "scrolllock": "Rollen",
    "pause": "Pause", "numlock": "Num", "minus": "-", "equal": "=",
    "leftbracket": "[", "rightbracket": "]", "backslash": "\\",
    "semicolon": ";", "apostrophe": "'", "grave": "`", "comma": ",",
    "period": ".", "slash": "/",
    "l_ctrl": "Strg", "r_ctrl": "Strg(r)", "l_alt": "Alt", "r_alt": "AltGr",
    "l_shift": "Shift", "r_shift": "Shift(r)", "l_win": "Win", "r_win": "Win(r)",
}

_MOD_ORDER = ("ctrl", "shift", "alt", "win")
_MOD_LABEL = {"ctrl": "Strg", "shift": "Shift", "alt": "Alt", "win": "Win"}


def key_label(name) -> str:
    if name in KEY_LABELS:
        return KEY_LABELS[name]
    if isinstance(name, str) and len(name) == 1:
        return name.upper()
    return str(name).upper()


def combo_label(mods, key_name) -> str:
    parts = [_MOD_LABEL[m] for m in _MOD_ORDER if m in mods]
    parts.append(key_label(key_name))
    return " + ".join(parts)


# ---------------------------------------------------------------------
#   Key-capture button  (press a combo; stores one main key + modifiers)
# ---------------------------------------------------------------------

class KeyCaptureButton(QPushButton):
    captured = Signal()

    _MOD_FLAGS = (
        (Qt.ControlModifier, "ctrl"),
        (Qt.ShiftModifier, "shift"),
        (Qt.AltModifier, "alt"),
        (Qt.MetaModifier, "win"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.key_name: str | None = None
        self.mods: list[str] = []
        self._listening = False
        self.clicked.connect(self._begin)
        self._render()

    def set_combo(self, key_name, mods):
        self.key_name = key_name
        self.mods = list(mods)
        self._listening = False
        self._render()

    def clear_combo(self):
        self.set_combo(None, [])

    def _begin(self):
        self._listening = True
        self.setText("Taste drücken …  (Esc bricht ab)")
        self.setFocus()

    def keyPressEvent(self, ev):
        if not self._listening:
            return super().keyPressEvent(ev)
        key = ev.key()
        if key == Qt.Key_Escape:
            self._listening = False
            self._render()
            return
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta,
                   Qt.Key_AltGr, 0):
            return  # lone modifier — wait for a real key
        name = qt_key_to_hid(key)
        if name is None:
            return  # unsupported key — keep listening
        self.key_name = name
        self.mods = [m for flag, m in self._MOD_FLAGS if ev.modifiers() & flag]
        self._listening = False
        self._render()
        self.captured.emit()

    def focusOutEvent(self, ev):
        if self._listening:
            self._listening = False
            self._render()
        super().focusOutEvent(ev)

    def _render(self):
        if self.key_name is None:
            self.setText("Tastenkürzel erfassen …")
        else:
            self.setText(combo_label(self.mods, self.key_name))


# ---------------------------------------------------------------------
#   Foreground-process detection (Windows) for opt-in auto-switch
# ---------------------------------------------------------------------

def foreground_exe() -> str:
    """Basename of the executable owning the foreground window (lower-case)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(2048)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return ""
            return os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return ""


# ---------------------------------------------------------------------
#   Button / macro vocab (friendly German labels over tyon_rgb constants)
# ---------------------------------------------------------------------

# Physical buttons we expose for remapping (omit the scroll wheel — that is the
# Pointer page's invert toggle).
ASSIGNABLE_BUTTONS = [
    ("left", "Linksklick"),
    ("right", "Rechtsklick"),
    ("middle", "Mausrad-Klick"),
    ("thumb_back", "Daumen zurück"),
    ("thumb_forward", "Daumen vor"),
    ("thumb_pedal", "Daumen-Pedal"),
    ("thumb_paddle_up", "X-Celerator hoch"),
    ("thumb_paddle_down", "X-Celerator runter"),
    ("left_back", "Links hinten"),
    ("left_forward", "Links vorne"),
    ("right_back", "Rechts hinten"),
    ("right_forward", "Rechts vorne"),
    ("fin_right", "Finne rechts"),
    ("fin_left", "Finne links"),
]

# Curated assignable actions: (friendly label, tyon BUTTON_TYPE key)
BUTTON_ACTIONS = [
    ("Linksklick", "click"),
    ("Rechtsklick / Menü", "menu"),
    ("Universal-Scrollen", "universal_scrolling"),
    ("Doppelklick", "double_click"),
    ("Tastenkürzel …", "shortcut"),
    ("Makro (auf Makro-Seite anlegen)", "macro"),
    ("Scrollen hoch", "scroll_up"),
    ("Scrollen runter", "scroll_down"),
    ("Browser vor", "ie_forward"),
    ("Browser zurück", "ie_backward"),
    ("DPI hoch", "cpi_up"),
    ("DPI runter", "cpi_down"),
    ("DPI durchschalten", "cpi_cycle"),
    ("Profil hoch", "profile_up"),
    ("Profil runter", "profile_down"),
    ("Profil durchschalten", "profile_cycle"),
    ("Windows-Taste", "windows_key"),
    ("Wiedergabe / Pause", "play_pause"),
    ("Nächster Titel", "next_track"),
    ("Vorheriger Titel", "prev_track"),
    ("Stopp", "stop"),
    ("Stummschalten", "mute"),
    ("Lauter", "volume_up"),
    ("Leiser", "volume_down"),
    ("Deaktiviert", "disabled"),
]
_ACTION_LABEL = {key: lbl for lbl, key in BUTTON_ACTIONS}

# Macro modifier helper (combo → which HID key to hold)
_MOD_HID = {"ctrl": "l_ctrl", "shift": "l_shift", "alt": "l_alt", "win": "l_win"}


def pretty_assignment(buf: bytearray, idx: int) -> str:
    """Compact, friendly description of a button slot for the list view."""
    type_, mod, key = tyon.get_button(buf, idx)
    if type_ == tyon.BUTTON_TYPE["shortcut"]:
        return combo_label(tyon.modifier_names(mod),
                           tyon.HID_KEY_NAME.get(key, f"0x{key:02x}"))
    if type_ == tyon.BUTTON_TYPE["macro"]:
        return "Makro"
    name = tyon.BUTTON_TYPE_NAME.get(type_)
    return _ACTION_LABEL.get(name, name or f"0x{type_:02x}")


def events_to_keystrokes(events: list[dict]) -> list[tuple]:
    """Convert recorded pynput key events to (key_name, action, period_ms)."""
    keys = [e for e in events if e.get("kind") == "key"]
    out = []
    for i, e in enumerate(keys):
        name = pynput_str_to_hid(e.get("key", ""))
        if name is None:
            continue
        action = (tyon.KEYSTROKE_ACTION_PRESS if e.get("action") == "press"
                  else tyon.KEYSTROKE_ACTION_RELEASE)
        if i + 1 < len(keys):
            period = int(round((keys[i + 1]["t"] - e["t"]) * 1000))
        else:
            period = 0
        out.append((name, action, max(0, min(0xFFFF, period))))
    return out


# ---------------------------------------------------------------------
#   Device hub — serialises all HID access on the GUI thread
# ---------------------------------------------------------------------

class DeviceHub(QObject):
    statusChanged = Signal(str, str)          # message, level ("", "ok", "err")
    profileChanged = Signal(int)
    connectionChanged = Signal(bool, str)     # connected, device name

    def __init__(self):
        super().__init__()
        self.prefs = store.load_prefs()
        self.profile = int(self.prefs.get("last_profile", 0)) % tyon.PROFILE_NUM
        self.connected = False
        self.device_name = "Roccat Tyon"

    # -- status / prefs --
    def set_status(self, msg: str, level: str = "") -> None:
        self.statusChanged.emit(msg, level)

    def save_prefs(self) -> None:
        store.save_prefs(self.prefs)

    # -- profile (edit target == active profile) --
    def set_profile(self, idx: int, make_active: bool = True) -> None:
        idx = int(idx) % tyon.PROFILE_NUM
        self.profile = idx
        self.prefs["last_profile"] = idx
        self.save_prefs()
        if make_active and self.connected:
            self.with_device(
                lambda dev, name: tyon.write_active_profile_index(dev, idx, False),
                announce_errors=False)
        self.profileChanged.emit(idx)

    # -- device access --
    def with_device(self, fn, *, slow: bool = False, announce_errors: bool = True):
        try:
            dev, name = tyon.open_tyon()
        except tyon.TyonNotFoundError:
            if self.connected:
                self.connected = False
                self.connectionChanged.emit(False, "")
            if announce_errors:
                self.set_status("Maus nicht gefunden — Tyon eingesteckt?", "err")
            return None
        except Exception as exc:
            if announce_errors:
                self.set_status(f"Verbindungsfehler: {exc}", "err")
            return None
        if not self.connected or self.device_name != name:
            self.connected = True
            self.device_name = name
            self.connectionChanged.emit(True, name)
        if slow:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return fn(dev, name)
        except Exception as exc:
            if announce_errors:
                self.set_status(f"Fehler: {exc}", "err")
            return None
        finally:
            if slow:
                QApplication.restoreOverrideCursor()
            try:
                dev.close()
            except Exception:
                pass

    def refresh_connection(self) -> None:
        def fn(dev, name):
            return tyon.read_active_profile_index(dev, False)
        active = self.with_device(fn, announce_errors=False)
        if active is not None:
            self.set_status(f"{self.device_name} verbunden.", "ok")


# ---------------------------------------------------------------------
#   Lighting page
# ---------------------------------------------------------------------

class LightingPage(QWidget):
    def __init__(self, hub: DeviceHub):
        super().__init__()
        self.hub = hub
        self._syncing = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)
        root.addWidget(self._build_color_card(), 3)
        root.addLayout(self._build_controls(), 2)

        self._set_color(QColor("#FF00FF"))
        self._refresh_recent()

    # -- color card --
    def _build_color_card(self) -> Card:
        card = Card("Farbe")
        self.wheel = ColorWheel()
        self.wheel.colorChanged.connect(self._on_wheel_changed)
        card.addWidget(self.wheel, 1)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.preview = QLabel()
        self.preview.setFixedSize(42, 42)
        self.preview.setToolTip("Vorschau (Farbe × Helligkeit)")
        row.addWidget(self.preview)
        row.addWidget(field_label("HEX"))
        self.hex_in = QLineEdit()
        self.hex_in.setMaxLength(7)
        self.hex_in.setFixedWidth(96)
        self.hex_in.setValidator(QRegularExpressionValidator(r"^#?[0-9A-Fa-f]{0,6}$"))
        self.hex_in.editingFinished.connect(self._on_hex_changed)
        row.addWidget(self.hex_in)
        for label, key in (("R", "r"), ("G", "g"), ("B", "b")):
            row.addWidget(field_label(label))
            sb = QSpinBox()
            sb.setRange(0, 255)
            sb.setFixedWidth(58)
            sb.setAlignment(Qt.AlignCenter)
            sb.valueChanged.connect(self._on_rgb_changed)
            setattr(self, f"in_{key}", sb)
            row.addWidget(sb)
        row.addStretch(1)
        card.addLayout(row)

        br = QHBoxLayout()
        br.setSpacing(10)
        br.addWidget(field_label("HELLIGKEIT"))
        self.brightness = QSlider(Qt.Horizontal)
        self.brightness.setRange(1, 100)
        self.brightness.setValue(100)
        self.brightness.valueChanged.connect(self._on_brightness_changed)
        br.addWidget(self.brightness, 1)
        self.brightness_value = QLabel("100 %")
        self.brightness_value.setObjectName("value")
        self.brightness_value.setMinimumWidth(46)
        self.brightness_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        br.addWidget(self.brightness_value)
        card.addLayout(br)

        card.addWidget(hline())

        # palette + recent
        pal = QGridLayout()
        pal.setHorizontalSpacing(8)
        pal.setVerticalSpacing(8)
        pal.addWidget(field_label("STANDARD"), 0, 0, 1, 9)
        for i, (name, hex_) in enumerate(STANDARD_COLORS):
            sw = Swatch(QColor(hex_), size=30)
            sw.setToolTip(f"{name} · {hex_}")
            sw.clicked.connect(lambda _=False, h=hex_: self._pick(h))
            pal.addWidget(sw, 1, i)
        pal.addWidget(field_label("ZULETZT"), 2, 0, 1, 9)
        self.recent_swatches = []
        for i in range(store.RECENT_MAX):
            sw = Swatch(None, size=30)
            sw.clicked.connect(self._on_recent_clicked)
            pal.addWidget(sw, 3, i)
            self.recent_swatches.append(sw)
        card.addLayout(pal)
        return card

    # -- controls column --
    def _build_controls(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(16)

        zone_card = Card("Zone")
        self.zone_group = QButtonGroup(self)
        zrow = QHBoxLayout()
        zrow.setSpacing(18)
        for i, label in enumerate(("Beide", "Mausrad", "Boden")):
            rb = QRadioButton(label)
            self.zone_group.addButton(rb, i)
            zrow.addWidget(rb)
        zrow.addStretch(1)
        self.zone_group.button(self.hub.prefs.get("last_zone", 0) or 0).setChecked(True)
        zone_card.addLayout(zrow)
        col.addWidget(zone_card)

        eff_card = Card("Effekt")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)
        grid.addWidget(field_label("Modus"), 0, 0)
        self.effect_combo = QComboBox()
        for label, key in EFFECT_LABELS:
            self.effect_combo.addItem(label, key)
        grid.addWidget(self.effect_combo, 0, 1)
        grid.addWidget(field_label("Tempo"), 1, 0)
        srow = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(1, 3)
        self.speed_slider.setValue(2)
        srow.addWidget(self.speed_slider, 1)
        self.speed_value = QLabel("2")
        self.speed_value.setObjectName("value")
        self.speed_value.setFixedWidth(18)
        self.speed_value.setAlignment(Qt.AlignCenter)
        self.speed_slider.valueChanged.connect(lambda v: self.speed_value.setText(str(v)))
        srow.addWidget(self.speed_value)
        grid.addLayout(srow, 1, 1)
        eff_card.addLayout(grid)
        if PRESETS:
            eff_card.addWidget(hline())
            prow = QHBoxLayout()
            prow.addWidget(field_label("PRESET"))
            for name, hex_, effect, zone, bright in PRESETS:
                from PySide6.QtWidgets import QPushButton
                b = QPushButton(name)
                b.setCursor(Qt.PointingHandCursor)
                c = QColor(hex_)
                b.setStyleSheet(
                    f"QPushButton{{background:{c.name()};color:#fff;border:1px solid #444;"
                    f"border-radius:6px;padding:6px 14px;font-weight:600;}}"
                    f"QPushButton:hover{{border:1px solid #fff;}}")
                b.clicked.connect(lambda _=False, h=hex_, e=effect, z=zone, br=bright:
                                  self._apply_preset(h, e, z, br))
                prow.addWidget(b)
            prow.addStretch(1)
            eff_card.addLayout(prow)
        col.addWidget(eff_card)

        col.addStretch(1)

        from PySide6.QtWidgets import QPushButton
        self.apply_btn = QPushButton("Auf Maus übertragen")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setMinimumHeight(46)
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(self._on_apply)
        col.addWidget(self.apply_btn)

        sec = QHBoxLayout()
        sec.setSpacing(10)
        read_btn = QPushButton("Aus Maus lesen")
        read_btn.setObjectName("ghost")
        read_btn.setCursor(Qt.PointingHandCursor)
        read_btn.clicked.connect(self.load)
        sec.addWidget(read_btn)
        off_btn = QPushButton("Licht aus")
        off_btn.setObjectName("ghost")
        off_btn.setCursor(Qt.PointingHandCursor)
        off_btn.clicked.connect(self._on_off)
        sec.addWidget(off_btn)
        col.addLayout(sec)
        return col

    # -- color sync --
    def _current(self) -> QColor:
        return self.wheel.color()

    def _pick(self, hex_: str):
        self.brightness.setValue(100)
        self._set_color(QColor(hex_))

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
        self.preview.setStyleSheet(
            f"background:{eff.name()}; border:1px solid {COL['border2']}; border-radius:8px;")

    def _on_brightness_changed(self, v):
        self.brightness_value.setText(f"{v} %")
        self._update_preview()

    def _on_wheel_changed(self, c):
        if not self._syncing:
            self._set_color(c)

    def _on_rgb_changed(self, _):
        if not self._syncing:
            self._set_color(QColor(self.in_r.value(), self.in_g.value(), self.in_b.value()))

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
        self.hex_in.setText(self._current().name().upper())

    def _on_recent_clicked(self):
        sw = self.sender()
        if isinstance(sw, Swatch) and sw.color():
            self.brightness.setValue(100)
            self._set_color(sw.color())

    def _refresh_recent(self):
        recent = self.hub.prefs.get("recent_colors", [])
        for i, sw in enumerate(self.recent_swatches):
            if i < len(recent):
                sw.setColor(QColor(recent[i]))
                sw.setToolTip(recent[i])
            else:
                sw.setColor(None)
                sw.setToolTip("")

    def _push_recent(self, c: QColor):
        store.push_recent_color(self.hub.prefs, c.name().upper())
        self.hub.save_prefs()
        self._refresh_recent()

    def _apply_preset(self, hex_, effect_key, zone_idx, brightness):
        self.brightness.setValue(brightness)
        self._set_color(QColor(hex_))
        for idx, (_, key) in enumerate(EFFECT_LABELS):
            if key == effect_key:
                self.effect_combo.setCurrentIndex(idx)
                break
        btn = self.zone_group.button(zone_idx)
        if btn:
            btn.setChecked(True)

    def _effect_label(self, key):
        return next((lbl for lbl, k in EFFECT_LABELS if k == key), key)

    def _zone_args(self, color: QColor):
        idx = self.zone_group.checkedId()
        rgb = (color.red(), color.green(), color.blue())
        if idx == 0:
            return rgb, rgb
        if idx == 1:
            return rgb, None
        return None, rgb

    # -- device ops --
    def _on_apply(self):
        color = self._effective_color()
        wheel_rgb, bottom_rgb = self._zone_args(color)
        effect = self.effect_combo.currentData()
        speed = self.speed_slider.value()
        profile = self.hub.profile
        self.hub.prefs["last_zone"] = self.zone_group.checkedId()
        self.hub.prefs["brightness"] = self.brightness.value()

        def fn(dev, name):
            s = tyon.read_profile_settings(dev, profile, False)
            if wheel_rgb is not None:
                s[18] = 0
                s[19], s[20], s[21] = wheel_rgb
                s[22] = 0
            if bottom_rgb is not None:
                s[23] = 1
                s[24], s[25], s[26] = bottom_rgb
                s[27] = 0
            le = s[14]
            if wheel_rgb is not None:
                le |= tyon.LIGHTS_ENABLED_BIT_WHEEL
            if bottom_rgb is not None:
                le |= tyon.LIGHTS_ENABLED_BIT_BOTTOM
            le |= tyon.LIGHTS_ENABLED_BIT_CUSTOM_COLOR
            s[14] = le & 0xFF
            s[16] = tyon.LIGHT_EFFECT[effect]
            s[17] = max(1, min(3, speed))
            tyon.write_profile_settings(dev, s, False)
            return name

        name = self.hub.with_device(fn, slow=True)
        if name:
            self._push_recent(color)
            self.hub.set_status(
                f"Profil {profile + 1} aktualisiert · {color.name().upper()} · "
                f"{self._effect_label(effect)}", "ok")

    def load(self):
        profile = self.hub.profile

        def fn(dev, name):
            return tyon.read_profile_settings(dev, profile, False)

        s = self.hub.with_device(fn)
        if s is None:
            return
        wheel = QColor(s[19], s[20], s[21])
        effect_byte = s[16]
        effect_key = next((k for k, v in tyon.LIGHT_EFFECT.items() if v == effect_byte), "solid")
        self.brightness.setValue(100)
        self._set_color(wheel)
        self.effect_combo.setCurrentIndex([k for _, k in EFFECT_LABELS].index(effect_key))
        self.speed_slider.setValue(max(1, min(3, s[17])))
        self.hub.set_status(
            f"Profil {profile + 1} gelesen · Rad {wheel.name().upper()} · "
            f"{self._effect_label(effect_key)}", "")

    def _on_off(self):
        profile = self.hub.profile

        def fn(dev, name):
            s = tyon.read_profile_settings(dev, profile, False)
            s[14] &= ~(tyon.LIGHTS_ENABLED_BIT_WHEEL | tyon.LIGHTS_ENABLED_BIT_BOTTOM)
            s[16] = tyon.LIGHT_EFFECT["off"]
            tyon.write_profile_settings(dev, s, False)
            return True

        if self.hub.with_device(fn, slow=True):
            self.hub.set_status(f"Profil {profile + 1} — Licht aus.", "")


# ---------------------------------------------------------------------
#   Pointer & DPI page
# ---------------------------------------------------------------------

class PointerPage(QWidget):
    def __init__(self, hub: DeviceHub):
        super().__init__()
        self.hub = hub
        self._syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(self._build_dpi_card())
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self._build_polling_card(), 1)
        row.addWidget(self._build_wheel_card(), 1)
        root.addLayout(row)
        root.addStretch(1)
        root.addLayout(self._build_actions())

    # -- build --
    def _build_dpi_card(self) -> Card:
        card = Card("DPI-Stufen")
        intro = QLabel("Bis zu fünf Stufen. Aktiviere die, die du brauchst, und "
                       "wähle die Stufe, mit der die Maus startet.")
        intro.setObjectName("note")
        intro.setWordWrap(True)
        card.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(2, 1)
        grid.addWidget(field_label("AN"), 0, 0)
        grid.addWidget(field_label("DPI"), 0, 2)
        grid.addWidget(field_label("AKTIV"), 0, 4)

        self.dpi_toggles, self.dpi_sliders, self.dpi_values = [], [], []
        self.active_group = QButtonGroup(self)
        self.active_group.setExclusive(True)
        for i in range(tyon.CPI_LEVEL_NUM):
            tg = ToggleSwitch()
            tg.toggled.connect(lambda on, idx=i: self._on_toggle(idx, on))
            self.dpi_toggles.append(tg)
            grid.addWidget(tg, i + 1, 0)
            grid.addWidget(QLabel(f"{i + 1}"), i + 1, 1)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(tyon.CPI_MIN, tyon.CPI_MAX)
            sl.setSingleStep(tyon.CPI_STORAGE_UNIT)
            sl.setPageStep(200)
            sl.valueChanged.connect(lambda v, idx=i: self._on_slider(idx, v))
            self.dpi_sliders.append(sl)
            grid.addWidget(sl, i + 1, 2)
            val = QLabel("800 dpi")
            val.setObjectName("value")
            val.setMinimumWidth(72)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.dpi_values.append(val)
            grid.addWidget(val, i + 1, 3)
            rb = QRadioButton()
            self.active_group.addButton(rb, i)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addStretch(1)
            hl.addWidget(rb)
            hl.addStretch(1)
            grid.addWidget(holder, i + 1, 4)
        card.addLayout(grid)
        return card

    def _build_polling_card(self) -> Card:
        card = Card("Abtastrate")
        self.poll_group = QButtonGroup(self)
        row = QHBoxLayout()
        row.setSpacing(16)
        for hz in (125, 250, 500, 1000):
            rb = QRadioButton(f"{hz} Hz")
            self.poll_group.addButton(rb, hz)
            row.addWidget(rb)
        row.addStretch(1)
        self.poll_group.button(1000).setChecked(True)
        card.addLayout(row)
        note = QLabel("Höher = häufigere Positionsmeldungen an den PC.")
        note.setObjectName("note")
        card.addWidget(note)
        return card

    def _build_wheel_card(self) -> Card:
        card = Card("Mausrad")
        row = QHBoxLayout()
        self.wheel_toggle = ToggleSwitch()
        row.addWidget(self.wheel_toggle)
        row.addSpacing(10)
        row.addWidget(QLabel("Scrollrichtung umkehren"))
        row.addStretch(1)
        card.addLayout(row)
        note = QLabel("„Natürliches“ Scrollen: Rad nach unten bewegt den Inhalt nach oben.")
        note.setObjectName("note")
        note.setWordWrap(True)
        card.addWidget(note)
        return card

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        read = ghost_button("Aus Maus lesen")
        read.clicked.connect(self.load)
        self.apply_btn = primary_button("Auf Maus übertragen")
        self.apply_btn.clicked.connect(self._on_apply)
        row.addWidget(read)
        row.addStretch(1)
        row.addWidget(self.apply_btn)
        return row

    # -- interaction --
    def _set_row_enabled(self, idx: int, on: bool):
        self.dpi_sliders[idx].setEnabled(on)
        self.dpi_values[idx].setEnabled(on)
        self.active_group.button(idx).setEnabled(on)

    def _on_toggle(self, idx: int, on: bool):
        if self._syncing:
            return
        if not on and sum(1 for t in self.dpi_toggles if t.isChecked()) == 0:
            self._syncing = True          # never allow zero enabled stages
            self.dpi_toggles[idx].setChecked(True)
            self._syncing = False
            return
        self._set_row_enabled(idx, on)
        rb = self.active_group.button(idx)
        if not on and rb.isChecked():
            for j, t in enumerate(self.dpi_toggles):
                if t.isChecked():
                    self.active_group.button(j).setChecked(True)
                    break

    def _on_slider(self, idx: int, v: int):
        snapped = max(tyon.CPI_MIN, min(tyon.CPI_MAX,
                      int(round(v / tyon.CPI_STORAGE_UNIT)) * tyon.CPI_STORAGE_UNIT))
        if snapped != v and not self._syncing:
            self._syncing = True
            self.dpi_sliders[idx].setValue(snapped)
            self._syncing = False
        self.dpi_values[idx].setText(f"{snapped} dpi")

    # -- device --
    def load(self):
        profile = self.hub.profile

        def fn(dev, name):
            s = tyon.read_profile_settings(dev, profile, False)
            b = tyon.read_profile_buttons(dev, profile, False)
            return s, b

        res = self.hub.with_device(fn)
        if not res:
            return
        s, b = res
        levels = tyon.get_cpi_levels(s)
        mask = tyon.get_cpi_enabled_mask(s)
        active = tyon.get_cpi_active(s)
        self._syncing = True
        for i in range(tyon.CPI_LEVEL_NUM):
            v = max(tyon.CPI_MIN, min(tyon.CPI_MAX, levels[i] or tyon.CPI_MIN))
            self.dpi_sliders[i].setValue(v)
            self.dpi_values[i].setText(f"{v} dpi")
            on = bool(mask & (1 << i))
            self.dpi_toggles[i].setChecked(on)
            self._set_row_enabled(i, on)
        # active stage (fall back to first enabled)
        if 0 <= active < tyon.CPI_LEVEL_NUM and (mask & (1 << active)):
            self.active_group.button(active).setChecked(True)
        else:
            for j in range(tyon.CPI_LEVEL_NUM):
                if mask & (1 << j):
                    self.active_group.button(j).setChecked(True)
                    break
        hz = tyon.get_polling_rate_hz(s) or 1000
        if self.poll_group.button(hz):
            self.poll_group.button(hz).setChecked(True)
        self.wheel_toggle.setChecked(tyon.is_wheel_inverted(b))
        self._syncing = False
        enabled = [levels[i] for i in range(tyon.CPI_LEVEL_NUM) if mask & (1 << i)]
        self.hub.set_status(
            f"Profil {profile + 1} gelesen · DPI {enabled} · {hz} Hz", "")

    def _on_apply(self):
        profile = self.hub.profile
        cpis = [self.dpi_sliders[i].value() for i in range(tyon.CPI_LEVEL_NUM)]
        mask = 0
        for i, t in enumerate(self.dpi_toggles):
            if t.isChecked():
                mask |= (1 << i)
        if not mask:
            mask = 1
        active = self.active_group.checkedId()
        if active < 0 or not (mask & (1 << active)):
            active = next(i for i in range(tyon.CPI_LEVEL_NUM) if mask & (1 << i))
        hz = self.poll_group.checkedId() or 1000
        invert = self.wheel_toggle.isChecked()

        def fn(dev, name):
            s = tyon.read_profile_settings(dev, profile, False)
            tyon.set_cpi_levels(s, cpis)
            tyon.set_cpi_enabled_mask(s, mask)
            tyon.set_cpi_active(s, active)
            tyon.set_polling_rate_hz(s, hz)
            tyon.write_profile_settings(dev, s, False)
            b = tyon.read_profile_buttons(dev, profile, False)
            tyon.set_wheel_inverted(b, invert)
            tyon.write_profile_buttons(dev, b, False)
            return True

        if self.hub.with_device(fn, slow=True):
            self.hub.set_status(
                f"Profil {profile + 1} · {cpis[active]} dpi aktiv · {hz} Hz · "
                f"Rad {'umgekehrt' if invert else 'normal'}", "ok")


# ---------------------------------------------------------------------
#   Buttons page  (master list + assignment detail)
# ---------------------------------------------------------------------

class ButtonsPage(QWidget):
    def __init__(self, hub: DeviceHub):
        super().__init__()
        self.hub = hub
        self.buttons_buf: bytearray | None = None

        self.current_name = ASSIGNABLE_BUTTONS[0][0]

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        diagram_card = Card("Maus")
        _here = os.path.dirname(os.path.abspath(__file__))
        _top = os.path.join(_here, "assets", "tyon_top.png")
        _side = os.path.join(_here, "assets", "tyon_side.png")
        if os.path.exists(_top) and os.path.exists(_side):
            self.diagram = MousePhotoMap(ASSIGNABLE_BUTTONS, _top, _side)
        else:
            self.diagram = MouseDiagram(ASSIGNABLE_BUTTONS)
        self.diagram.set_selected(self.current_name)
        self.diagram.selected.connect(self._on_pick)
        diagram_card.addWidget(self.diagram, 1)
        hint = QLabel("Klick auf eine Taste im Foto, um sie zu belegen.")
        hint.setObjectName("note")
        hint.setWordWrap(True)
        diagram_card.addWidget(hint)
        root.addWidget(diagram_card, 1)

        detail_host = QWidget()
        detail_host.setLayout(self._build_detail())
        detail_host.setMaximumWidth(340)
        root.addWidget(detail_host)

    def _build_detail(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(16)

        self.detail = Card("Zuweisung")
        self.btn_title = QLabel("—")
        self.btn_title.setObjectName("h2")
        self.detail.addWidget(self.btn_title)
        self.current_lbl = QLabel("")
        self.current_lbl.setObjectName("note")
        self.detail.addWidget(self.current_lbl)
        self.detail.addWidget(hline())

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)
        grid.addWidget(field_label("Funktion"), 0, 0)
        self.action_combo = QComboBox()
        for label, key in BUTTON_ACTIONS:
            self.action_combo.addItem(label, key)
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)
        grid.addWidget(self.action_combo, 0, 1)

        self.shortcut_row = QWidget()
        sr = QHBoxLayout(self.shortcut_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(field_label("Kürzel"))
        self.capture = KeyCaptureButton()
        sr.addWidget(self.capture, 1)
        grid.addWidget(self.shortcut_row, 1, 0, 1, 2)
        self.detail.addLayout(grid)

        self.macro_hint = QLabel("Diese Funktion legt das Makro an, das auf der "
                                 "Makro-Seite für diese Taste gespeichert ist.")
        self.macro_hint.setObjectName("note")
        self.macro_hint.setWordWrap(True)
        self.detail.addWidget(self.macro_hint)
        self.detail.addStretch(1)
        col.addWidget(self.detail, 1)

        row = QHBoxLayout()
        read = ghost_button("Aus Maus lesen")
        read.clicked.connect(self.load)
        self.apply_btn = primary_button("Auf Maus übertragen")
        self.apply_btn.clicked.connect(self._on_apply)
        row.addWidget(read)
        row.addStretch(1)
        row.addWidget(self.apply_btn)
        col.addLayout(row)
        return col

    # -- interaction --
    def _on_action_changed(self, _):
        key = self.action_combo.currentData()
        self.shortcut_row.setVisible(key == "shortcut")
        self.macro_hint.setVisible(key == "macro")

    def _on_pick(self, name: str):
        self.current_name = name
        self.diagram.set_selected(name)
        self._show(name)

    def _show(self, name: str):
        label = dict(ASSIGNABLE_BUTTONS).get(name, name)
        self.btn_title.setText(label)
        if self.buttons_buf is None:
            self.current_lbl.setText("Aktuell: —")
            return
        idx = tyon.BUTTON_INDEX[name]
        type_, mod, key = tyon.get_button(self.buttons_buf, idx)
        self.current_lbl.setText("Aktuell: " + pretty_assignment(self.buttons_buf, idx))
        # reflect current type in the combo if it is one we expose
        type_name = tyon.BUTTON_TYPE_NAME.get(type_)
        target = next((j for j, (_l, k) in enumerate(BUTTON_ACTIONS)
                       if k == type_name), None)
        self.action_combo.blockSignals(True)
        self.action_combo.setCurrentIndex(target if target is not None else 0)
        self.action_combo.blockSignals(False)
        if type_ == tyon.BUTTON_TYPE["shortcut"]:
            self.capture.set_combo(tyon.HID_KEY_NAME.get(key), tyon.modifier_names(mod))
        else:
            self.capture.clear_combo()
        self._on_action_changed(None)

    # -- device --
    def load(self):
        profile = self.hub.profile

        def fn(dev, name):
            return tyon.read_profile_buttons(dev, profile, False)

        buf = self.hub.with_device(fn)
        if buf is None:
            return
        self.buttons_buf = buf
        self.diagram.set_assignments(
            {name: pretty_assignment(buf, tyon.BUTTON_INDEX[name])
             for name, _label in ASSIGNABLE_BUTTONS})
        self.diagram.set_selected(self.current_name)
        self._show(self.current_name)
        self.hub.set_status(f"Profil {profile + 1}: Tastenbelegung gelesen.", "")

    def _on_apply(self):
        if self.buttons_buf is None:
            self.load()
            if self.buttons_buf is None:
                return
        name = self.current_name
        idx = tyon.BUTTON_INDEX[name]
        action = self.action_combo.currentData()
        buf = bytearray(self.buttons_buf)
        if action == "shortcut":
            if self.capture.key_name is None:
                self.hub.set_status("Bitte zuerst ein Tastenkürzel erfassen.", "err")
                return
            tyon.set_button_shortcut(buf, idx, self.capture.key_name, self.capture.mods)
        elif action == "macro":
            tyon.set_button(buf, idx, tyon.BUTTON_TYPE["macro"])
        else:
            tyon.set_button(buf, idx, tyon.BUTTON_TYPE[action])
        profile = self.hub.profile

        def fn(dev, _n):
            tyon.write_profile_buttons(dev, buf, False)
            return True

        if self.hub.with_device(fn, slow=True):
            self.buttons_buf = buf
            label = dict(ASSIGNABLE_BUTTONS).get(name, name)
            self.diagram.set_assignments(
                {n: pretty_assignment(buf, tyon.BUTTON_INDEX[n])
                 for n, _l in ASSIGNABLE_BUTTONS})
            self._show(name)
            self.hub.set_status(
                f"{label} → {pretty_assignment(buf, idx)} · Profil {profile + 1}.", "ok")


# ---------------------------------------------------------------------
#   Macros page
# ---------------------------------------------------------------------

class MacrosPage(QWidget):
    recordingDone = Signal(list)

    def __init__(self, hub: DeviceHub):
        super().__init__()
        self.hub = hub
        self._recorder = None
        self._keystrokes: list[tuple] = []
        self.recordingDone.connect(self._on_recording_done)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        head = Card("Makro")
        info = QLabel("Makros laufen direkt auf der Maus (Onboard-Speicher) – kein "
                      "Hintergrundprogramm am PC. Das ist die richtige Wahl für Spiele "
                      "mit Anti-Cheat.")
        info.setObjectName("note")
        info.setWordWrap(True)
        head.addWidget(info)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        form.addWidget(field_label("Taste"), 0, 0)
        self.target_combo = QComboBox()
        for name, label in ASSIGNABLE_BUTTONS:
            if name in ("left", "right"):
                continue  # don't bury the primary clicks under a macro
            self.target_combo.addItem(label, name)
        self.target_combo.setCurrentIndex(
            max(0, self.target_combo.findData("thumb_back")))
        form.addWidget(self.target_combo, 0, 1)
        form.addWidget(field_label("Name"), 0, 2)
        self.name_in = QLineEdit()
        self.name_in.setMaxLength(tyon.MACRO_NAME_LENGTH - 1)
        self.name_in.setPlaceholderText("z. B. Gruß-Spam")
        form.addWidget(self.name_in, 0, 3)
        form.addWidget(field_label("Wiederholungen"), 1, 0)
        self.loop_spin = QSpinBox()
        self.loop_spin.setRange(1, 255)
        self.loop_spin.setValue(1)
        self.loop_spin.setSuffix(" ×")
        form.addWidget(self.loop_spin, 1, 1)
        head.addLayout(form)
        root.addWidget(head)

        body = Card("Tastenfolge")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Taste", "Aktion", "Pause (ms)"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(220)
        body.addWidget(self.table)

        addrow = QHBoxLayout()
        addrow.setSpacing(8)
        self.add_key = KeyCaptureButton()
        addrow.addWidget(self.add_key, 1)
        add_btn = ghost_button("Taste hinzufügen")
        add_btn.clicked.connect(self._add_key)
        addrow.addWidget(add_btn)
        rm_btn = ghost_button("Zeile entfernen")
        rm_btn.clicked.connect(self._remove_row)
        addrow.addWidget(rm_btn)
        clr_btn = ghost_button("Leeren")
        clr_btn.clicked.connect(self._clear)
        addrow.addWidget(clr_btn)
        body.addLayout(addrow)
        root.addWidget(body, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.rec_btn = ghost_button("● Aufnehmen  (F10 stoppt)")
        self.rec_btn.clicked.connect(self._toggle_record)
        actions.addWidget(self.rec_btn)
        read = ghost_button("Aus Maus lesen")
        read.clicked.connect(self._on_read)
        actions.addWidget(read)
        actions.addStretch(1)
        self.flash_btn = primary_button("Auf Taste übertragen")
        self.flash_btn.clicked.connect(self._on_flash)
        actions.addWidget(self.flash_btn)
        root.addLayout(actions)

        if not tinput.available():
            self.rec_btn.setEnabled(False)
            self.rec_btn.setToolTip("pynput nicht verfügbar – Aufnahme deaktiviert.")

    def load(self):
        pass  # macros are button-specific; nothing to auto-load on page enter

    # -- keystroke table --
    def _set_keystrokes(self, ks: list[tuple]):
        self._keystrokes = list(ks)
        self._render_table()

    def _render_table(self):
        self.table.setRowCount(len(self._keystrokes))
        for r, (key, action, period) in enumerate(self._keystrokes):
            kt = QTableWidgetItem(key_label(key if isinstance(key, str)
                                            else tyon.HID_KEY_NAME.get(key, key)))
            at = QTableWidgetItem("Drücken" if action == tyon.KEYSTROKE_ACTION_PRESS
                                  else "Lösen")
            pt = QTableWidgetItem(str(period))
            at.setTextAlignment(Qt.AlignCenter)
            pt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 0, kt)
            self.table.setItem(r, 1, at)
            self.table.setItem(r, 2, pt)

    def _add_key(self):
        if self.add_key.key_name is None:
            self.hub.set_status("Erst eine Taste im Feld erfassen.", "err")
            return
        name, mods = self.add_key.key_name, self.add_key.mods
        seq = [(_MOD_HID[m], tyon.KEYSTROKE_ACTION_PRESS, 12) for m in mods]
        seq.append((name, tyon.KEYSTROKE_ACTION_PRESS, 40))
        seq.append((name, tyon.KEYSTROKE_ACTION_RELEASE, 12))
        seq += [(_MOD_HID[m], tyon.KEYSTROKE_ACTION_RELEASE, 12) for m in reversed(mods)]
        self._keystrokes += seq
        self._render_table()
        self.add_key.clear_combo()

    def _remove_row(self):
        r = self.table.currentRow()
        if 0 <= r < len(self._keystrokes):
            del self._keystrokes[r]
            self._render_table()

    def _clear(self):
        self._keystrokes = []
        self._render_table()

    # -- recording --
    def _toggle_record(self):
        if not tinput.available():
            QMessageBox.warning(self, "pynput fehlt", tinput._import_error_message())
            return
        if self._recorder and self._recorder.is_recording():
            self._recorder.stop()
            return
        self._recorder = tinput.Recorder(record_moves=False, stop_key="f10")
        self.rec_btn.setText("● Aufnahme läuft …  (F10 stoppt)")
        self.rec_btn.setObjectName("danger")
        restyle(self.rec_btn)
        self.hub.set_status("Makro-Aufnahme läuft – tippe deine Tastenfolge, F10 stoppt.", "")
        self._recorder.start(on_stop=lambda evs: self.recordingDone.emit(evs))

    def _on_recording_done(self, events: list):
        self.rec_btn.setText("● Aufnehmen  (F10 stoppt)")
        self.rec_btn.setObjectName("ghost")
        restyle(self.rec_btn)
        ks = events_to_keystrokes(events)
        self._set_keystrokes(ks)
        self.hub.set_status(f"{len(ks)} Tastenanschläge aufgenommen.", "ok")

    # -- device --
    def _on_flash(self):
        if not self._keystrokes:
            self.hub.set_status("Keine Tastenfolge vorhanden.", "err")
            return
        profile = self.hub.profile
        name = self.name_in.text().strip() or "Makro"
        loop = self.loop_spin.value()
        btn_name = self.target_combo.currentData()
        bidx = tyon.BUTTON_INDEX[btn_name]
        ks = list(self._keystrokes)

        def fn(dev, _n):
            buf = tyon.build_tyon_macro(profile, bidx, name, ks, loop=loop)
            tyon.write_macro(dev, profile, bidx, buf, False)
            b = tyon.read_profile_buttons(dev, profile, False)
            tyon.set_button(b, bidx, tyon.BUTTON_TYPE["macro"])
            tyon.write_profile_buttons(dev, b, False)
            return True

        if self.hub.with_device(fn, slow=True):
            self.hub.set_status(
                f"Makro „{name}“ ({len(ks)} Anschläge, {loop}×) auf "
                f"{self.target_combo.currentText()} – Profil {profile + 1}.", "ok")

    def _on_read(self):
        profile = self.hub.profile
        bidx = tyon.BUTTON_INDEX[self.target_combo.currentData()]

        def fn(dev, _n):
            return tyon.read_macro(dev, profile, bidx, False)

        buf = self.hub.with_device(fn, slow=True)
        if buf is None:
            return
        info = tyon.parse_macro(buf)
        ks = [(tyon.HID_KEY_NAME.get(k, k), a, p) for (k, a, p) in info["keystrokes"]]
        self.name_in.setText(info["name"])
        self.loop_spin.setValue(max(1, info["loop"]))
        self._set_keystrokes(ks)
        if info["count"]:
            self.hub.set_status(
                f"Makro „{info['name']}“ gelesen · {info['count']} Anschläge.", "")
        else:
            self.hub.set_status("Auf dieser Taste ist kein Makro gespeichert.", "")


# ---------------------------------------------------------------------
#   Game profiles + StarCraft II build-order practice aid
# ---------------------------------------------------------------------

class GamesPage(QWidget):
    playbackDone = Signal(bool)
    recordingDone = Signal(list)

    def __init__(self, hub: DeviceHub):
        super().__init__()
        self.hub = hub
        self.profiles = store.load_game_profiles()
        self._recorder = None
        self._player = None
        self._record_screen = (0, 0)
        self.playbackDone.connect(self._on_playback_done)
        self.recordingDone.connect(self._finish_bo_record)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(self._build_profiles_card())
        root.addWidget(self._build_buildorder_card(), 1)

        # foreground watcher (opt-in)
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(2000)
        self.watch_timer.timeout.connect(self._tick_watch)
        if self.hub.prefs.get("auto_switch_enabled"):
            self.watch_toggle.setChecked(True)

    # -- game-profile table --
    def _build_profiles_card(self) -> Card:
        card = Card("Spielprofile")
        intro = QLabel("Ordne jedem Spiel ein Maus-Profil zu. Auto-Switch wechselt nur "
                       "das aktive Onboard-Profil der Maus, wenn das Spiel im "
                       "Vordergrund ist – es greift NIE in das Spiel ein.")
        intro.setObjectName("note")
        intro.setWordWrap(True)
        card.addWidget(intro)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Spiel", "Prozess (.exe)", "Maus-Profil", "Auto"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(170)
        self._rebuild_table()
        card.addWidget(self.table)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.watch_toggle = ToggleSwitch()
        self.watch_toggle.toggled.connect(self._on_watch_toggled)
        row.addWidget(self.watch_toggle)
        row.addSpacing(6)
        self.watch_lbl = QLabel("Auto-Switch aktiv")
        row.addWidget(self.watch_lbl)
        row.addStretch(1)
        add = ghost_button("Zeile hinzufügen")
        add.clicked.connect(self._add_profile)
        row.addWidget(add)
        rm = ghost_button("Zeile entfernen")
        rm.clicked.connect(self._remove_profile)
        row.addWidget(rm)
        save = primary_button("Speichern")
        save.setMinimumHeight(0)
        save.clicked.connect(self._save_profiles)
        row.addWidget(save)
        card.addLayout(row)
        return card

    def _center(self, w: QWidget) -> QWidget:
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        lay.addWidget(w)
        lay.addStretch(1)
        return holder

    def _rebuild_table(self):
        self.table.setRowCount(len(self.profiles))
        for r, p in enumerate(self.profiles):
            self.table.setItem(r, 0, QTableWidgetItem(p.get("name", "")))
            self.table.setItem(r, 1, QTableWidgetItem(p.get("exe", "")))
            combo = QComboBox()
            for i in range(tyon.PROFILE_NUM):
                combo.addItem(f"Profil {i + 1}", i)
            combo.setMinimumWidth(104)
            combo.setCurrentIndex(int(p.get("mouse_profile", 0)) % tyon.PROFILE_NUM)
            self.table.setCellWidget(r, 2, combo)
            tg = ToggleSwitch()
            tg.setChecked(bool(p.get("auto_switch")))
            self.table.setCellWidget(r, 3, self._center(tg))

    def _collect_table(self):
        out = []
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            exe_item = self.table.item(r, 1)
            combo = self.table.cellWidget(r, 2)
            holder = self.table.cellWidget(r, 3)
            tg = holder.findChild(ToggleSwitch) if holder else None
            out.append({
                "name": name_item.text() if name_item else "",
                "exe": (exe_item.text() if exe_item else "").strip(),
                "mouse_profile": combo.currentData() if combo else 0,
                "auto_switch": tg.isChecked() if tg else False,
            })
        return out

    def _add_profile(self):
        self.profiles = self._collect_table()
        self.profiles.append({"name": "Neues Spiel", "exe": "", "mouse_profile": 0,
                              "auto_switch": False})
        self._rebuild_table()

    def _remove_profile(self):
        r = self.table.currentRow()
        self.profiles = self._collect_table()
        if 0 <= r < len(self.profiles):
            del self.profiles[r]
            self._rebuild_table()

    def _save_profiles(self):
        self.profiles = self._collect_table()
        store.save_game_profiles(self.profiles)
        self.hub.set_status(f"{len(self.profiles)} Spielprofile gespeichert.", "ok")

    # -- auto-switch watcher --
    def _on_watch_toggled(self, on: bool):
        self.hub.prefs["auto_switch_enabled"] = bool(on)
        self.hub.save_prefs()
        if on:
            self.profiles = self._collect_table()
            self.watch_timer.start()
            self.hub.set_status("Auto-Switch aktiv – wechselt das Maus-Profil je "
                                "nach Vordergrund-Spiel.", "")
        else:
            self.watch_timer.stop()
            self.hub.set_status("Auto-Switch aus.", "")

    def _tick_watch(self):
        if not self.watch_toggle.isChecked():
            return
        exe = foreground_exe()
        target = None
        default = None
        for p in self.profiles:
            pe = (p.get("exe") or "").strip().lower()
            if pe == "":
                default = p.get("mouse_profile")
            elif p.get("auto_switch") and pe == exe:
                target = p.get("mouse_profile")
        chosen = target if target is not None else default
        if chosen is None:
            return
        chosen = int(chosen) % tyon.PROFILE_NUM
        if chosen != self.hub.profile:
            self.hub.set_profile(chosen, make_active=True)
            where = exe if target is not None else "Desktop"
            self.hub.set_status(f"Auto-Switch → Profil {chosen + 1} ({where}).", "")

    # -- SC2 build orders --
    def _build_buildorder_card(self) -> Card:
        card = Card("StarCraft II – Build-Order (Übungshilfe)")
        disc = QLabel(
            "Übungshilfe, kein Spielvorteil: Sie nimmt eine selbst gespielte "
            "Eröffnung auf und spielt exakt dieselben Klicks/Tasten wieder ab "
            "(Kamera-Anker + Auflösungs-Skalierung). Kein Aim-Assist, kein "
            "Rückstoß-Ausgleich, nichts Kampf-Relevantes. Automatisierte Eingaben "
            "sind bei Blizzard eine ToS-Grauzone – nutze das nur fürs Training und "
            "auf eigenes Risiko. Abbruch jederzeit mit F12.")
        disc.setObjectName("warn")
        disc.setWordWrap(True)
        card.addWidget(disc)

        opts = QGridLayout()
        opts.setHorizontalSpacing(12)
        opts.setVerticalSpacing(10)
        opts.setColumnStretch(1, 1)
        opts.setColumnStretch(3, 1)
        opts.addWidget(field_label("Startverzögerung"), 0, 0)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 15)
        self.delay_spin.setValue(3)
        self.delay_spin.setSuffix(" s")
        opts.addWidget(self.delay_spin, 0, 1)
        opts.addWidget(field_label("Kamera-Anker"), 0, 2)
        self.anchor_combo = QComboBox()
        self.anchor_combo.addItem("Basis zentrieren (Rücktaste)", "backspace")
        self.anchor_combo.addItem("Kein Anker", "")
        opts.addWidget(self.anchor_combo, 0, 3)
        card.addLayout(opts)

        mid = QHBoxLayout()
        mid.setSpacing(16)
        self.bo_list = QListWidget()
        self.bo_list.setMinimumHeight(140)
        mid.addWidget(self.bo_list, 1)
        card.addLayout(mid)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.bo_rec_btn = ghost_button("● Aufnehmen  (F10 stoppt)")
        self.bo_rec_btn.clicked.connect(self._toggle_bo_record)
        row.addWidget(self.bo_rec_btn)
        refresh = ghost_button("Aktualisieren")
        refresh.clicked.connect(self._refresh_orders)
        row.addWidget(refresh)
        delete = QPushButton("Löschen")
        delete.setObjectName("danger")
        delete.setCursor(Qt.PointingHandCursor)
        delete.clicked.connect(self._delete_order)
        row.addWidget(delete)
        row.addStretch(1)
        self.bo_stop_btn = ghost_button("Stopp")
        self.bo_stop_btn.clicked.connect(self._stop_play)
        self.bo_stop_btn.setEnabled(False)
        row.addWidget(self.bo_stop_btn)
        self.bo_play_btn = primary_button("Abspielen")
        self.bo_play_btn.clicked.connect(self._play_order)
        row.addWidget(self.bo_play_btn)
        card.addLayout(row)

        if not tinput.available():
            for w in (self.bo_rec_btn, self.bo_play_btn):
                w.setEnabled(False)
                w.setToolTip("pynput nicht verfügbar.")
        return card

    def _refresh_orders(self):
        self.bo_list.clear()
        for path in store.list_build_orders():
            try:
                bo = tinput.BuildOrder.load(str(path))
                label = f"{bo.name}   ·   {bo.duration:.0f}s   ·   {len(bo.events)} Aktionen"
            except Exception:
                label = path.stem
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, str(path))
            self.bo_list.addItem(it)

    def _toggle_bo_record(self):
        if not tinput.available():
            QMessageBox.warning(self, "pynput fehlt", tinput._import_error_message())
            return
        if self._recorder and self._recorder.is_recording():
            self._recorder.stop()
            return
        self._recorder = tinput.Recorder(record_moves=False, stop_key="f10")
        self._record_screen = tinput.screen_size()
        self.bo_rec_btn.setText("● Aufnahme läuft …  (F10 stoppt)")
        self.bo_rec_btn.setObjectName("danger")
        restyle(self.bo_rec_btn)
        self.hub.set_status("Build-Order-Aufnahme läuft – spiele deine Eröffnung, "
                            "F10 stoppt.", "")
        # on_stop fires on the listener thread; the queued signal hops to the GUI thread
        self._recorder.start(on_stop=lambda evs: self.recordingDone.emit(evs))

    def _finish_bo_record(self, events: list):
        self.bo_rec_btn.setText("● Aufnehmen  (F10 stoppt)")
        self.bo_rec_btn.setObjectName("ghost")
        restyle(self.bo_rec_btn)
        if not events:
            self.hub.set_status("Nichts aufgenommen.", "err")
            return
        name, ok = QInputDialog.getText(self, "Build-Order speichern",
                                        "Name der Build-Order:")
        if not ok or not name.strip():
            self.hub.set_status("Aufnahme verworfen (kein Name).", "")
            return
        anchor = self.anchor_combo.currentData()
        bo = tinput.BuildOrder(name.strip(), events, self._record_screen,
                               game="StarCraft II", camera_anchor=anchor or "backspace")
        bo.save(str(store.build_order_path(name)))
        self._refresh_orders()
        self.hub.set_status(f"Build-Order „{name.strip()}“ gespeichert "
                            f"({len(events)} Aktionen).", "ok")

    def _delete_order(self):
        item = self.bo_list.currentItem()
        if not item:
            return
        path = item.data(Qt.UserRole)
        if QMessageBox.question(self, "Löschen",
                                f"Build-Order „{item.text()}“ löschen?") \
                == QMessageBox.Yes:
            store.delete_build_order(path)
            self._refresh_orders()
            self.hub.set_status("Build-Order gelöscht.", "")

    def _play_order(self):
        if not tinput.available():
            return
        item = self.bo_list.currentItem()
        if not item:
            self.hub.set_status("Erst eine Build-Order auswählen.", "err")
            return
        try:
            bo = tinput.BuildOrder.load(item.data(Qt.UserRole))
        except Exception as exc:
            self.hub.set_status(f"Laden fehlgeschlagen: {exc}", "err")
            return
        delay = self.delay_spin.value()
        anchor = self.anchor_combo.currentData() or None
        self._player = tinput.Player()
        self.bo_play_btn.setEnabled(False)
        self.bo_stop_btn.setEnabled(True)
        self.hub.set_status(
            f"„{bo.name}“ startet in {delay}s … wechsle ins Spiel. F12 bricht ab.", "")

        def run():
            ok = self._player.play(
                bo.events, src_screen=tuple(bo.screen), camera_anchor=anchor,
                start_delay=delay, abort_key="f12")
            self.playbackDone.emit(ok)

        threading.Thread(target=run, daemon=True).start()

    def _stop_play(self):
        if self._player:
            self._player.abort()

    def _on_playback_done(self, ok: bool):
        self.bo_play_btn.setEnabled(True)
        self.bo_stop_btn.setEnabled(False)
        self.hub.set_status("Build-Order abgespielt." if ok
                            else "Build-Order abgebrochen.", "ok" if ok else "")

    def load(self):
        self.profiles = store.load_game_profiles()
        self._rebuild_table()
        self._refresh_orders()


# ---------------------------------------------------------------------
#   Main window
# ---------------------------------------------------------------------

class TyonWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Roccat Tyon — Control Center")
        self.setMinimumSize(1200, 780)
        self.resize(1720, 1000)

        self.hub = DeviceHub()
        self.hub.statusChanged.connect(self._on_status)
        self.hub.connectionChanged.connect(self._on_connection)

        central = QWidget()
        central.setObjectName("content")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_rail())

        content_wrap = QWidget()
        content_wrap.setObjectName("content")
        cv = QVBoxLayout(content_wrap)
        cv.setContentsMargins(24, 22, 24, 14)
        cv.setSpacing(14)
        self.stack = QStackedWidget()
        cv.addWidget(self.stack, 1)
        cv.addWidget(self._build_statusbar())
        body.addWidget(content_wrap, 1)
        outer.addLayout(body, 1)

        # pages
        self.pages = {}
        self.pages["light"] = LightingPage(self.hub)
        self.pages["pointer"] = PointerPage(self.hub)
        self.pages["buttons"] = ButtonsPage(self.hub)
        self.pages["macro"] = MacrosPage(self.hub)
        self.pages["games"] = GamesPage(self.hub)
        for key, _ in PAGES:
            self.stack.addWidget(scroll_wrap(self.pages[key]))

        self.hub.profileChanged.connect(lambda _: self._load_current())
        self.nav_buttons[0].setChecked(True)
        self._switch(0)

        # initial connection probe
        self.hub.refresh_connection()
        self._sync_profile_combo()

    # -- header --
    def _build_header(self) -> QWidget:
        h = QWidget()
        h.setObjectName("header")
        h.setFixedHeight(74)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(20, 0, 22, 0)
        lay.setSpacing(14)
        lay.addWidget(MouseGlyph())
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        self.device_label = QLabel("Roccat Tyon")
        self.device_label.setObjectName("h2")
        sub = QLabel("Onboard-Konfiguration")
        sub.setObjectName("sub")
        tcol.addWidget(self.device_label)
        tcol.addWidget(sub)
        lay.addLayout(tcol)
        lay.addStretch(1)

        self.conn_dot = QLabel()
        self.conn_dot.setFixedSize(10, 10)
        self._set_dot(False)
        lay.addWidget(self.conn_dot)
        self.conn_label = QLabel("Getrennt")
        self.conn_label.setObjectName("sub")
        lay.addWidget(self.conn_label)

        lay.addSpacing(10)
        plabel = QLabel("PROFIL")
        plabel.setObjectName("cardTitle")
        lay.addWidget(plabel)
        self.profile_combo = QComboBox()
        for i in range(tyon.PROFILE_NUM):
            self.profile_combo.addItem(f"{i + 1}", i)
        self.profile_combo.setFixedWidth(64)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_combo)
        lay.addWidget(self.profile_combo)
        return h

    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("rail")
        rail.setFixedWidth(212)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(0, 14, 0, 14)
        lay.setSpacing(2)

        brand = QLabel("  TYON")
        brand.setStyleSheet(f"color:{COL['text']}; font-size:12pt; font-weight:800;"
                            f"letter-spacing:3px; padding:8px 18px 14px 18px;")
        lay.addWidget(brand)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        for i, (icon, label) in enumerate(PAGES):
            btn = NavButton(icon, label)
            self.nav_group.addButton(btn, i)
            lay.addWidget(btn)
            self.nav_buttons.append(btn)
        self.nav_group.idClicked.connect(self._switch)
        lay.addStretch(1)

        hint = QLabel("  Einstellungen landen im\n  Onboard-Speicher der Maus.")
        hint.setObjectName("note")
        hint.setStyleSheet(f"color:{COL['faint']}; padding:8px 18px 2px; font-size:8.5pt;")
        lay.addWidget(hint)

        credit = QLabel("  © 2026 Randolf Hellmann")
        credit.setObjectName("note")
        credit.setStyleSheet(f"color:{COL['faint']}; padding:0 18px 12px; font-size:8pt;")
        lay.addWidget(credit)
        return rail

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(2, 0, 2, 0)
        self.status_label = QLabel("Bereit.")
        self.status_label.setObjectName("status")
        lay.addWidget(self.status_label)
        lay.addStretch(1)
        return bar

    # -- navigation --
    def _switch(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self._load_current()

    def _load_current(self):
        w = self.stack.currentWidget()
        page = w.widget() if isinstance(w, QScrollArea) else w
        if hasattr(page, "load"):
            page.load()

    # -- profile --
    def _on_profile_combo(self, _):
        idx = self.profile_combo.currentData()
        if idx is None:
            return
        self.hub.set_profile(idx, make_active=True)

    def _sync_profile_combo(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(self.hub.profile)
        self.profile_combo.blockSignals(False)

    # -- status / connection --
    def _on_status(self, msg, level):
        self.status_label.setText(msg)
        self.status_label.setObjectName(
            {"ok": "statusOk", "err": "statusErr"}.get(level, "status"))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _set_dot(self, connected):
        c = COL["ok"] if connected else COL["faint"]
        self.conn_dot.setStyleSheet(f"background:{c}; border-radius:5px;")

    def _on_connection(self, connected, name):
        self._set_dot(connected)
        self.conn_label.setText("Verbunden" if connected else "Getrennt")
        if connected and name:
            self.device_label.setText(name)


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    win = TyonWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
