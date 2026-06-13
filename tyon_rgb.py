# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Randolf Hellmann
"""Roccat Tyon RGB controller.

Two paths:

* Persistent (default): writes into the onboard profile flash. Survives
  unplug, reboot, switch to another PC. Per-zone colors supported.
* Live (--live):  sends a TalkFX feature report. RAM-only, lost on unplug,
  but instant and doesn't touch the profile.

Protocol reverse-engineered from Linux roccat-tools (tyon/libroccattyon).
"""

import argparse
import sys
import time
from typing import Iterable

import hid

VID = 0x1E7D
PIDS = {0x2E4A: "Tyon Black", 0x2E4B: "Tyon White"}

# --- Report IDs (from tyon_device.h) ---
REPORT_ID_CONTROL          = 0x04
REPORT_ID_PROFILE          = 0x05
REPORT_ID_PROFILE_SETTINGS = 0x06
REPORT_ID_TALK             = 0x10

# --- Sizes ---
PROFILE_SIZE          = 3      # report_id + size + profile_index
PROFILE_SETTINGS_SIZE = 30
TALK_SIZE             = 16
CONTROL_SIZE          = 3

# --- Profile count ---
PROFILE_NUM = 5

# --- CONTROL request types (from tyon_device.h, TyonControlRequest) ---
CONTROL_REQUEST_CHECK            = 0x00
CONTROL_REQUEST_PROFILE_SETTINGS = 0x80
CONTROL_REQUEST_PROFILE_BUTTONS  = 0x90

# --- CONTROL status (from roccat_control.c) ---
CONTROL_STATUS_OK       = 0x01
CONTROL_STATUS_INVALID  = 0x02
CONTROL_STATUS_BUSY     = 0x03
CONTROL_STATUS_CRITICAL = 0x04

# --- Profile-settings lighting field bits/values ---
LIGHTS_ENABLED_BIT_WHEEL        = 1 << 0
LIGHTS_ENABLED_BIT_BOTTOM       = 1 << 1
LIGHTS_ENABLED_BIT_CUSTOM_COLOR = 1 << 4

COLOR_FLOW_OFF             = 0
COLOR_FLOW_SIMULTANEOUSLY  = 1
COLOR_FLOW_UP              = 2
COLOR_FLOW_DOWN            = 3

LIGHT_EFFECT = {
    "off":       0,  # ALL_OFF
    "solid":     1,  # FULLY_LIGHTED
    "blink":     2,  # BLINKING
    "breathe":   3,  # BREATHING
    "heartbeat": 4,  # HEARTBEAT
}

# --- TalkFX (live) ---
TALK_EASYSHIFT_UNUSED = 0xFF
TALK_EASYAIM_UNUSED   = 0xFF
TALK_FX_ON  = 0x01
TALK_FX_OFF = 0x00
TALK_ZONE_AMBIENT = 3
TALK_ZONE_EVENT   = 4

# --- Buttons / Macros (report ids, from tyon_device.h) ---
REPORT_ID_PROFILE_BUTTONS = 0x07
REPORT_ID_MACRO           = 0x08

PROFILE_BUTTONS_SIZE = 99   # 3 header + 32 buttons * 3 bytes, no checksum
PROFILE_BUTTON_NUM   = 32
BUTTON_STRIDE        = 3    # each button: {type, modifier, key}

# --- DPI / CPI (from tyon.h) ---
CPI_MIN  = 200
CPI_MAX  = 8200
CPI_STEP = 200            # UI step: snap DPI selections to multiples of 200
CPI_STORAGE_UNIT = 50     # on-device byte = cpi / 50  (verified on hardware)
CPI_LEVEL_NUM = 5
CPI_BYTE_MAX = CPI_MAX // CPI_STORAGE_UNIT   # 164

# --- Polling rate: low nibble of profile-settings byte 13 ---
POLLING_RATE     = {0x00: 125, 0x01: 250, 0x02: 500, 0x03: 1000}
POLLING_RATE_INV = {v: k for k, v in POLLING_RATE.items()}

# --- Physical button positions (TyonButtonIndex). +16 = Easy-Shift variant. ---
BUTTON_INDEX = {
    "left": 0, "right": 1, "middle": 2,
    "thumb_back": 3, "thumb_forward": 4, "thumb_pedal": 5,
    "thumb_paddle_up": 6, "thumb_paddle_down": 7,
    "left_back": 8, "left_forward": 9,
    "right_back": 10, "right_forward": 11,
    "fin_right": 12, "fin_left": 13,
    "wheel_up": 14, "wheel_down": 15,
}
SHIFT_OFFSET = 16  # add to a base index for its Easy-Shift slot

# --- Button action types (TyonButtonType) ---
BUTTON_TYPE = {
    "unused": 0x00, "click": 0x01, "menu": 0x02, "universal_scrolling": 0x03,
    "double_click": 0x04, "shortcut": 0x05, "disabled": 0x06,
    "ie_forward": 0x07, "ie_backward": 0x08, "tilt_left": 0x09, "tilt_right": 0x0a,
    "scroll_up": 0x0d, "scroll_down": 0x0e, "quicklaunch": 0x0f,
    "profile_cycle": 0x10, "profile_up": 0x11, "profile_down": 0x12,
    "cpi_cycle": 0x14, "cpi_up": 0x15, "cpi_down": 0x16,
    "sensitivity_cycle": 0x17, "sensitivity_up": 0x18, "sensitivity_down": 0x19,
    "windows_key": 0x1a, "open_driver": 0x1b, "open_player": 0x20,
    "prev_track": 0x21, "next_track": 0x22, "play_pause": 0x23, "stop": 0x24,
    "mute": 0x25, "volume_up": 0x26, "volume_down": 0x27,
    "macro": 0x30, "timer": 0x31, "timer_stop": 0x32,
    "easyaim_1": 0x33, "easyaim_2": 0x34, "easyaim_3": 0x35,
    "easyaim_4": 0x36, "easyaim_5": 0x37,
    "easyshift_self": 0x41,
    "home": 0x86, "end": 0x87, "page_up": 0x88, "page_down": 0x89,
    "l_ctrl": 0x8a, "l_alt": 0x8b,
}
BUTTON_TYPE_NAME = {v: k for k, v in BUTTON_TYPE.items()}
# Extra names for read-back display only (gamepad-axis / DirectInput mappings,
# e.g. the X-Celerator paddle shows up as a DInput axis). Not in the curated
# assignable set above.
BUTTON_TYPE_NAME.update({0x60 + i: f"xinput_{i + 1}" for i in range(10)})
BUTTON_TYPE_NAME.update({0x74 + i: f"dinput_{i + 1}" for i in range(12)})
BUTTON_TYPE_NAME.update({
    0x6a: "xinput_rx_up", 0x6b: "xinput_rx_down",
    0x6c: "xinput_ry_up", 0x6d: "xinput_ry_down",
    0x6e: "xinput_x_up",  0x6f: "xinput_x_down",
    0x70: "xinput_y_up",  0x71: "xinput_y_down",
    0x72: "xinput_z_up",  0x73: "xinput_z_down",
    0x80: "dinput_x_up",  0x81: "dinput_x_down",
    0x82: "dinput_y_up",  0x83: "dinput_y_down",
    0x84: "dinput_z_up",  0x85: "dinput_z_down",
})

# --- SHORTCUT modifier bits (TyonButtonModifierBit). byte = OR of (1 << bit). ---
BUTTON_MODIFIER_BIT = {"shift": 1, "ctrl": 2, "alt": 3, "win": 4}

# --- Macro protocol constants (tyon_macro.h / tyon_device.h) ---
CONTROL_DATA_INDEX_NONE    = 0x00
CONTROL_DATA_INDEX_MACRO_1 = 0x10
CONTROL_DATA_INDEX_MACRO_2 = 0x20

MACRO_TOTAL_SIZE     = 1997   # full TyonMacro struct (split across 2 reports)
MACRO_1_DATA_SIZE    = 1024
MACRO_2_DATA_SIZE    = 973
MACRO_2_UNUSED_SIZE  = 51
MACRO_REPORT_SIZE    = 1026   # report_id + selector + data, for each of the 2 reports
MACRO_KEYSTROKES_NUM = 480
MACRO_NAME_LENGTH    = 24
KEYSTROKE_ACTION_PRESS   = 1
KEYSTROKE_ACTION_RELEASE = 2

# Byte offsets inside the 1997-byte TyonMacro struct
_MACRO_OFF_PROFILE    = 0
_MACRO_OFF_BUTTON     = 1
_MACRO_OFF_LOOP       = 2
_MACRO_OFF_MACROSET   = 27
_MACRO_OFF_NAME       = 51
_MACRO_OFF_COUNT      = 75
_MACRO_OFF_KEYSTROKES = 77

# --- USB HID keyboard/keypad usage IDs (page 0x07) ---
# Used both for SHORTCUT button assignment and for macro keystrokes.
HID_KEY = {
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0a, "h": 0x0b, "i": 0x0c, "j": 0x0d, "k": 0x0e, "l": 0x0f,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1a, "x": 0x1b,
    "y": 0x1c, "z": 0x1d,
    "1": 0x1e, "2": 0x1f, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "enter": 0x28, "escape": 0x29, "backspace": 0x2a, "tab": 0x2b,
    "space": 0x2c, "minus": 0x2d, "equal": 0x2e, "leftbracket": 0x2f,
    "rightbracket": 0x30, "backslash": 0x31, "semicolon": 0x33,
    "apostrophe": 0x34, "grave": 0x35, "comma": 0x36, "period": 0x37,
    "slash": 0x38, "capslock": 0x39,
    "f1": 0x3a, "f2": 0x3b, "f3": 0x3c, "f4": 0x3d, "f5": 0x3e, "f6": 0x3f,
    "f7": 0x40, "f8": 0x41, "f9": 0x42, "f10": 0x43, "f11": 0x44, "f12": 0x45,
    "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48, "insert": 0x49,
    "home": 0x4a, "pageup": 0x4b, "delete": 0x4c, "end": 0x4d, "pagedown": 0x4e,
    "right": 0x4f, "left": 0x50, "down": 0x51, "up": 0x52,
    "numlock": 0x53, "kp_slash": 0x54, "kp_asterisk": 0x55, "kp_minus": 0x56,
    "kp_plus": 0x57, "kp_enter": 0x58,
    "kp_1": 0x59, "kp_2": 0x5a, "kp_3": 0x5b, "kp_4": 0x5c, "kp_5": 0x5d,
    "kp_6": 0x5e, "kp_7": 0x5f, "kp_8": 0x60, "kp_9": 0x61, "kp_0": 0x62,
    "kp_period": 0x63,
    "f13": 0x68, "f14": 0x69, "f15": 0x6a, "f16": 0x6b, "f17": 0x6c,
    "f18": 0x6d, "f19": 0x6e, "f20": 0x6f, "f21": 0x70, "f22": 0x71,
    "f23": 0x72, "f24": 0x73,
    "l_ctrl": 0xe0, "l_shift": 0xe1, "l_alt": 0xe2, "l_win": 0xe3,
    "r_ctrl": 0xe4, "r_shift": 0xe5, "r_alt": 0xe6, "r_win": 0xe7,
}
HID_KEY_NAME = {v: k for k, v in HID_KEY.items()}


# ---------- helpers ----------

def parse_color(s: str) -> tuple[int, int, int]:
    s = s.strip().lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError(
            f"color must be 6 hex digits (RRGGBB), got {s!r}"
        )
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"bad color {s!r}: {e}")


def enumerate_tyon() -> list[dict]:
    out = []
    for pid in PIDS:
        out.extend(hid.enumerate(VID, pid))
    return out


def find_vendor_interface(infos: list[dict]) -> dict | None:
    # Roccat hides vendor feature reports under the Telephony (0x000b) TLC of
    # the mouse interface (MI_00). Empirically verified on Tyon White.
    for info in infos:
        if info.get("usage_page") == 0x000B:
            return info
    return None


class TyonNotFoundError(RuntimeError):
    pass


def open_tyon():
    infos = enumerate_tyon()
    if not infos:
        raise TyonNotFoundError(
            "No Tyon found (VID 0x1E7D, PID 0x2E4A/0x2E4B). "
            "Is the mouse plugged in?"
        )
    chosen = find_vendor_interface(infos)
    if chosen is None:
        raise TyonNotFoundError(
            "Tyon detected but the vendor HID interface (Telephony "
            "collection, usage_page 0x000b) wasn't found."
        )
    name = PIDS.get(chosen["product_id"], "Tyon")
    path = chosen["path"]
    if isinstance(path, str):
        path = path.encode()
    dev = hid.device()
    dev.open_path(path)
    return dev, name


def calc_checksum(buf: bytes | bytearray) -> int:
    # ROCCAT_BYTESUM_PARTIALLY: sum of all bytes EXCEPT the trailing 2 checksum
    # bytes, taken modulo 2**16, stored little-endian.
    return sum(buf[:-2]) & 0xFFFF


def write_feature(dev, data: bytes, label: str, verbose: bool) -> None:
    n = dev.send_feature_report(data)
    if verbose:
        print(f"  > {label} ({len(data)} B): {data.hex(' ')} -> ret={n}")
    if n < 0:
        raise IOError(f"send_feature_report({label}) failed (returned {n})")


def read_feature(dev, report_id: int, size: int, label: str, verbose: bool) -> bytes:
    raw = dev.get_feature_report(report_id, size)
    if verbose:
        print(f"  < {label}: {bytes(raw).hex(' ') if raw else '<empty>'}")
    return bytes(raw)


def check_write(dev, verbose: bool, init_wait_ms: int = 200,
                busy_wait_ms: int = 500, max_loops: int = 6) -> None:
    """Poll CONTROL (0x04) after a write until OK, mirroring roccat_check_write."""
    time.sleep(init_wait_ms / 1000.0)
    increasing_wait = busy_wait_ms
    for i in range(max_loops):
        resp = read_feature(dev, REPORT_ID_CONTROL, CONTROL_SIZE,
                            f"check#{i}", verbose)
        if len(resp) < 2:
            raise IOError(f"CONTROL read returned {len(resp)} bytes")
        status = resp[1]
        if status == CONTROL_STATUS_OK:
            return
        if status == CONTROL_STATUS_BUSY:
            time.sleep(increasing_wait / 1000.0)
            increasing_wait += busy_wait_ms
            continue
        names = {
            CONTROL_STATUS_INVALID: "INVALID",
            CONTROL_STATUS_CRITICAL: "CRITICAL",
            0x00: "CRITICAL(0)",
        }
        raise IOError(f"CONTROL status {status:#04x} "
                      f"({names.get(status, 'UNKNOWN')})")
    raise IOError(f"CONTROL still busy after {max_loops} polls")


def tyon_select(dev, profile_index: int, data_index: int, request: int,
                verbose: bool) -> None:
    """Send a CONTROL select packet, then verify.

    Mirrors roccat_select: byte1 = data_index | profile_index, byte2 = request.
    For macro reads the data_index selects MACRO_1/MACRO_2 and the request byte
    carries the button index. Profiles occupy the low 3 bits, so they never
    collide with the data-index bits (0x10 / 0x20).
    """
    byte1 = (data_index | (profile_index & 0x07)) & 0xFF
    write_feature(
        dev,
        bytes([REPORT_ID_CONTROL, byte1, request & 0xFF]),
        f"SELECT profile={profile_index} data=0x{data_index:02x} req=0x{request:02x}",
        verbose,
    )
    check_write(dev, verbose)


def select_profile(dev, profile_index: int, request: int, verbose: bool) -> None:
    """Select a profile for a plain (non-macro) data transfer."""
    tyon_select(dev, profile_index, CONTROL_DATA_INDEX_NONE, request, verbose)


def read_active_profile_index(dev, verbose: bool) -> int:
    raw = read_feature(dev, REPORT_ID_PROFILE, PROFILE_SIZE, "PROFILE", verbose)
    if len(raw) < 3:
        raise IOError("PROFILE read too short")
    return raw[2]


def write_active_profile_index(dev, profile_index: int, verbose: bool) -> None:
    pkt = bytes([REPORT_ID_PROFILE, PROFILE_SIZE, profile_index & 0x07])
    write_feature(dev, pkt, f"SET active profile = {profile_index}", verbose)
    check_write(dev, verbose)


def read_profile_settings(dev, profile_index: int, verbose: bool) -> bytearray:
    select_profile(dev, profile_index, CONTROL_REQUEST_PROFILE_SETTINGS, verbose)
    raw = read_feature(dev, REPORT_ID_PROFILE_SETTINGS,
                       PROFILE_SETTINGS_SIZE, "PROFILE_SETTINGS", verbose)
    if len(raw) != PROFILE_SETTINGS_SIZE:
        raise IOError(f"PROFILE_SETTINGS read returned {len(raw)} bytes, "
                      f"expected {PROFILE_SETTINGS_SIZE}")
    return bytearray(raw)


def write_profile_settings(dev, settings: bytearray, verbose: bool) -> None:
    # Always overwrite the header bytes and checksum before sending
    settings[0] = REPORT_ID_PROFILE_SETTINGS
    settings[1] = PROFILE_SETTINGS_SIZE
    chk = calc_checksum(settings)
    settings[28] = chk & 0xFF
    settings[29] = (chk >> 8) & 0xFF
    write_feature(dev, bytes(settings), "PROFILE_SETTINGS", verbose)
    check_write(dev, verbose)


# ---------- DPI / polling helpers (operate on a ProfileSettings buffer) ----------

def cpi_byte_to_value(b: int) -> int:
    return b * CPI_STORAGE_UNIT


def cpi_value_to_byte(cpi: int) -> int:
    cpi = max(CPI_MIN, min(CPI_MAX, cpi))
    return max(1, min(CPI_BYTE_MAX, round(cpi / CPI_STORAGE_UNIT)))


def get_cpi_levels(s: bytearray) -> list[int]:
    return [cpi_byte_to_value(s[7 + i]) for i in range(CPI_LEVEL_NUM)]


def set_cpi_levels(s: bytearray, cpis: list[int]) -> None:
    """Set the 5 DPI stages (in cpi). 0/None leaves a slot unchanged."""
    for i in range(CPI_LEVEL_NUM):
        if i < len(cpis) and cpis[i]:
            s[7 + i] = cpi_value_to_byte(cpis[i])


def get_cpi_enabled_mask(s: bytearray) -> int:
    return s[6]


def set_cpi_enabled_mask(s: bytearray, mask: int) -> None:
    s[6] = mask & 0x1F


def get_cpi_active(s: bytearray) -> int:
    return s[12]


def set_cpi_active(s: bytearray, idx: int) -> None:
    s[12] = idx & 0x07


def get_polling_rate_hz(s: bytearray) -> int | None:
    return POLLING_RATE.get(s[13] & 0x0F)


def set_polling_rate_hz(s: bytearray, hz: int) -> None:
    if hz not in POLLING_RATE_INV:
        raise ValueError(f"polling rate must be one of {list(POLLING_RATE_INV)}")
    s[13] = (s[13] & 0xF0) | (POLLING_RATE_INV[hz] & 0x0F)


# ---------- Buttons (report 0x07) ----------

def read_profile_buttons(dev, profile_index: int, verbose: bool) -> bytearray:
    select_profile(dev, profile_index, CONTROL_REQUEST_PROFILE_BUTTONS, verbose)
    raw = read_feature(dev, REPORT_ID_PROFILE_BUTTONS,
                       PROFILE_BUTTONS_SIZE, "PROFILE_BUTTONS", verbose)
    if len(raw) != PROFILE_BUTTONS_SIZE:
        raise IOError(f"PROFILE_BUTTONS read returned {len(raw)} bytes, "
                      f"expected {PROFILE_BUTTONS_SIZE}")
    return bytearray(raw)


def write_profile_buttons(dev, buttons: bytearray, verbose: bool) -> None:
    # 99-byte report has no checksum (3 header + 96 button bytes).
    buttons[0] = REPORT_ID_PROFILE_BUTTONS
    buttons[1] = PROFILE_BUTTONS_SIZE
    # buttons[2] = profile_index is preserved from the read
    write_feature(dev, bytes(buttons), "PROFILE_BUTTONS", verbose)
    check_write(dev, verbose)


def get_button(buttons: bytearray, index: int) -> tuple[int, int, int]:
    base = 3 + index * BUTTON_STRIDE
    return buttons[base], buttons[base + 1], buttons[base + 2]


def set_button(buttons: bytearray, index: int, type_: int,
               modifier: int = 0, key: int = 0) -> None:
    base = 3 + index * BUTTON_STRIDE
    buttons[base] = type_ & 0xFF
    buttons[base + 1] = modifier & 0xFF
    buttons[base + 2] = key & 0xFF


def set_wheel_inverted(buttons: bytearray, inverted: bool) -> None:
    """Invert the scroll wheel by swapping the wheel-up/down action types."""
    up   = BUTTON_TYPE["scroll_down"] if inverted else BUTTON_TYPE["scroll_up"]
    down = BUTTON_TYPE["scroll_up"]   if inverted else BUTTON_TYPE["scroll_down"]
    set_button(buttons, BUTTON_INDEX["wheel_up"], up)
    set_button(buttons, BUTTON_INDEX["wheel_down"], down)


def is_wheel_inverted(buttons: bytearray) -> bool:
    up_type, _, _ = get_button(buttons, BUTTON_INDEX["wheel_up"])
    return up_type == BUTTON_TYPE["scroll_down"]


# ---------- shortcuts (key assignment) ----------

def modifier_byte(mods: Iterable[str]) -> int:
    """Combine modifier names (shift/ctrl/alt/win) into the SHORTCUT modifier byte."""
    b = 0
    for m in mods:
        key = str(m).strip().lower()
        if key not in BUTTON_MODIFIER_BIT:
            raise ValueError(f"unknown modifier {m!r} "
                             f"(expected one of {list(BUTTON_MODIFIER_BIT)})")
        b |= 1 << BUTTON_MODIFIER_BIT[key]
    return b


def modifier_names(byte: int) -> list[str]:
    """Inverse of modifier_byte: list active modifier names for display."""
    return [name for name, bit in BUTTON_MODIFIER_BIT.items() if byte & (1 << bit)]


def resolve_hid_key(key) -> int:
    """Accept a HID usage id (int) or a friendly key name; return the usage id."""
    if isinstance(key, int):
        return key & 0xFF
    name = str(key).strip().lower()
    if name in HID_KEY:
        return HID_KEY[name]
    raise ValueError(f"unknown key {key!r} (see HID_KEY for valid names)")


def set_button_shortcut(buttons: bytearray, index: int, key,
                        mods: Iterable[str] = ()) -> None:
    """Assign a keyboard shortcut (SHORTCUT type) to a button slot."""
    set_button(buttons, index, BUTTON_TYPE["shortcut"],
               modifier_byte(mods), resolve_hid_key(key))


def describe_button(buttons: bytearray, index: int) -> str:
    """Human-readable description of a button slot, for read-back/audit."""
    type_, mod, key = get_button(buttons, index)
    name = BUTTON_TYPE_NAME.get(type_, f"0x{type_:02x}")
    if type_ == BUTTON_TYPE["shortcut"]:
        parts = modifier_names(mod) + [HID_KEY_NAME.get(key, f"0x{key:02x}")]
        return "shortcut " + "+".join(parts)
    if type_ == BUTTON_TYPE["macro"]:
        return "macro"
    if mod or key:
        return f"{name} (mod=0x{mod:02x} key=0x{key:02x})"
    return name


# ---------- onboard macros (report 0x08) ----------

def _put_macro_name(buf: bytearray, offset: int, name: str,
                    length: int = MACRO_NAME_LENGTH) -> None:
    data = str(name).encode("ascii", "replace")[: length - 1]
    buf[offset : offset + len(data)] = data
    # remaining bytes stay zero (buffer is zero-initialised)


def build_tyon_macro(profile_index: int, button_index: int, name: str,
                     keystrokes, loop: int = 1, macroset: str = "custom") -> bytearray:
    """Build the 1997-byte TyonMacro struct.

    keystrokes: iterable of (key, action, period_ms) where ``key`` is a HID
    usage id or friendly name, ``action`` is KEYSTROKE_ACTION_PRESS / _RELEASE,
    and ``period_ms`` is the delay until the next event in milliseconds.
    """
    buf = bytearray(MACRO_TOTAL_SIZE)
    buf[_MACRO_OFF_PROFILE] = profile_index & 0xFF
    buf[_MACRO_OFF_BUTTON]  = button_index & 0xFF
    buf[_MACRO_OFF_LOOP]    = max(1, int(loop)) & 0xFF
    _put_macro_name(buf, _MACRO_OFF_MACROSET, macroset)
    _put_macro_name(buf, _MACRO_OFF_NAME, name)
    ks = list(keystrokes)[:MACRO_KEYSTROKES_NUM]
    buf[_MACRO_OFF_COUNT]     = len(ks) & 0xFF
    buf[_MACRO_OFF_COUNT + 1] = (len(ks) >> 8) & 0xFF
    off = _MACRO_OFF_KEYSTROKES
    for key, action, period in ks:
        period = max(0, min(0xFFFF, int(period)))
        buf[off]     = resolve_hid_key(key)
        buf[off + 1] = int(action) & 0xFF
        buf[off + 2] = period & 0xFF
        buf[off + 3] = (period >> 8) & 0xFF
        off += 4
    return buf


def write_macro(dev, profile_index: int, button_index: int,
                macro_buf: bytearray, verbose: bool) -> None:
    """Flash a macro to a button slot via the two-report split protocol."""
    macro_buf = bytearray(macro_buf)
    if len(macro_buf) != MACRO_TOTAL_SIZE:
        raise ValueError(f"macro must be {MACRO_TOTAL_SIZE} bytes, "
                         f"got {len(macro_buf)}")
    macro_buf[_MACRO_OFF_PROFILE] = profile_index & 0xFF
    macro_buf[_MACRO_OFF_BUTTON]  = button_index & 0xFF
    report1 = bytes([REPORT_ID_MACRO, 1]) + bytes(macro_buf[:MACRO_1_DATA_SIZE])
    report2 = (bytes([REPORT_ID_MACRO, 2])
               + bytes(macro_buf[MACRO_1_DATA_SIZE:MACRO_TOTAL_SIZE])
               + bytes(MACRO_2_UNUSED_SIZE))
    write_feature(dev, report1, "MACRO_1", verbose)
    check_write(dev, verbose)
    write_feature(dev, report2, "MACRO_2", verbose)
    check_write(dev, verbose)


def read_macro(dev, profile_index: int, button_index: int,
               verbose: bool) -> bytearray:
    """Read back a macro from a button slot; returns the 1997-byte struct."""
    tyon_select(dev, profile_index, CONTROL_DATA_INDEX_MACRO_1, button_index, verbose)
    raw1 = read_feature(dev, REPORT_ID_MACRO, MACRO_REPORT_SIZE, "MACRO_1", verbose)
    tyon_select(dev, profile_index, CONTROL_DATA_INDEX_MACRO_2, button_index, verbose)
    raw2 = read_feature(dev, REPORT_ID_MACRO, MACRO_REPORT_SIZE, "MACRO_2", verbose)
    data = (bytes(raw1[2:2 + MACRO_1_DATA_SIZE])
            + bytes(raw2[2:2 + MACRO_2_DATA_SIZE]))
    return bytearray(data)


def parse_macro(macro_buf: bytearray) -> dict:
    """Decode a 1997-byte TyonMacro buffer into a dict (for display/audit)."""
    def _name(off):
        raw = bytes(macro_buf[off:off + MACRO_NAME_LENGTH])
        return raw.split(b"\x00", 1)[0].decode("ascii", "replace")

    count = macro_buf[_MACRO_OFF_COUNT] | (macro_buf[_MACRO_OFF_COUNT + 1] << 8)
    count = min(count, MACRO_KEYSTROKES_NUM)
    keystrokes = []
    off = _MACRO_OFF_KEYSTROKES
    for _ in range(count):
        key = macro_buf[off]
        action = macro_buf[off + 1]
        period = macro_buf[off + 2] | (macro_buf[off + 3] << 8)
        keystrokes.append((key, action, period))
        off += 4
    return {
        "profile_index": macro_buf[_MACRO_OFF_PROFILE],
        "button_index": macro_buf[_MACRO_OFF_BUTTON],
        "loop": macro_buf[_MACRO_OFF_LOOP],
        "macroset": _name(_MACRO_OFF_MACROSET),
        "name": _name(_MACRO_OFF_NAME),
        "count": count,
        "keystrokes": keystrokes,
    }


# ---------- TalkFX (live) ----------

def talkfx_send(dev, ambient: tuple[int, int, int], event: tuple[int, int, int],
                effect: int, speed: int, verbose: bool, off: bool = False) -> None:
    if off:
        report = bytes([
            REPORT_ID_TALK, TALK_SIZE,
            TALK_EASYSHIFT_UNUSED, TALK_EASYSHIFT_UNUSED, TALK_EASYAIM_UNUSED,
            TALK_FX_OFF,
            0, 0, 0, 0,
            0, 0, 0, 0, 0, 0,
        ])
    else:
        report = bytes([
            REPORT_ID_TALK, TALK_SIZE,
            TALK_EASYSHIFT_UNUSED, TALK_EASYSHIFT_UNUSED, TALK_EASYAIM_UNUSED,
            TALK_FX_ON,
            TALK_ZONE_AMBIENT, 0,
            effect, speed,
            ambient[0], ambient[1], ambient[2],
            event[0], event[1], event[2],
        ])
    write_feature(dev, report, "TALK", verbose)


# ---------- subcommands ----------

def cmd_probe() -> None:
    print("Scanning for Roccat Tyon HID interfaces...\n")
    infos = enumerate_tyon()
    if not infos:
        print("  Nothing found. Mouse not plugged in?")
        return
    for info in infos:
        pid = info["product_id"]
        name = PIDS.get(pid, f"PID 0x{pid:04x}")
        iface = info.get("interface_number")
        up = info.get("usage_page", 0)
        usage = info.get("usage", 0)
        path = info["path"]
        path_str = path.decode(errors="replace") if isinstance(path, bytes) else path
        marker = "  <-- vendor (use this)" if up == 0x000B else ""
        print(f"  {name}: iface={iface}  usage_page=0x{up:04x}  "
              f"usage=0x{usage:04x}{marker}")
        print(f"    {path_str}")
    print()


def fmt_color(rgb: Iterable[int]) -> str:
    r, g, b = rgb
    return f"#{r:02X}{g:02X}{b:02X}"


def cmd_read(profile_index: int | None, verbose: bool) -> None:
    dev, name = open_tyon()
    try:
        active = read_active_profile_index(dev, verbose)
        targets = [profile_index] if profile_index is not None else list(range(PROFILE_NUM))
        print(f"{name}: active profile = {active}\n")
        for i in targets:
            s = read_profile_settings(dev, i, verbose)
            lights_enabled = s[14]
            color_flow     = s[15]
            light_effect   = s[16]
            effect_speed   = s[17]
            wheel  = (s[19], s[20], s[21])
            bottom = (s[24], s[25], s[26])
            effect_name = next((k for k, v in LIGHT_EFFECT.items()
                                if v == light_effect), str(light_effect))
            tag = " (active)" if i == active else ""
            print(f"Profile {i}{tag}:")
            print(f"  wheel  = {fmt_color(wheel)}  enabled={bool(lights_enabled & LIGHTS_ENABLED_BIT_WHEEL)}")
            print(f"  bottom = {fmt_color(bottom)}  enabled={bool(lights_enabled & LIGHTS_ENABLED_BIT_BOTTOM)}")
            print(f"  custom_color = {bool(lights_enabled & LIGHTS_ENABLED_BIT_CUSTOM_COLOR)}")
            print(f"  color_flow = {color_flow}  effect = {effect_name}  speed = {effect_speed}")
            print(f"  dpi stages = {get_cpi_levels(s)} cpi  "
                  f"enabled_mask=0x{s[6]:02x}  active_idx={get_cpi_active(s)}")
            print(f"  dpi stages (raw bytes) = {list(s[7:12])}")
            print(f"  polling = {get_polling_rate_hz(s)} Hz")
            try:
                b = read_profile_buttons(dev, i, verbose)
                print(f"  wheel = {'INVERTED' if is_wheel_inverted(b) else 'normal'}")
                mapped = []
                for bname, bidx in BUTTON_INDEX.items():
                    t, _mod, _key = get_button(b, bidx)
                    mapped.append(f"{bname}={BUTTON_TYPE_NAME.get(t, hex(t))}")
                print("  buttons: " + ", ".join(mapped))
            except Exception as e:  # noqa: BLE001 - diagnostic, keep --read robust
                print(f"  buttons: <read failed: {e}>")
            print()
    finally:
        dev.close()


def cmd_persist(profile_index: int | None, wheel: tuple[int, int, int] | None,
                bottom: tuple[int, int, int] | None, effect: str, speed: int,
                wheel_off: bool, bottom_off: bool, verbose: bool) -> None:
    dev, name = open_tyon()
    try:
        if profile_index is None:
            profile_index = read_active_profile_index(dev, verbose)
        s = read_profile_settings(dev, profile_index, verbose)

        if wheel is not None:
            s[18] = 0                # index
            s[19], s[20], s[21] = wheel
            s[22] = 0                # unused
        if bottom is not None:
            s[23] = 1                # index
            s[24], s[25], s[26] = bottom
            s[27] = 0                # unused

        lights_enabled = s[14]
        if wheel_off:
            lights_enabled &= ~LIGHTS_ENABLED_BIT_WHEEL
        elif wheel is not None:
            lights_enabled |= LIGHTS_ENABLED_BIT_WHEEL
        if bottom_off:
            lights_enabled &= ~LIGHTS_ENABLED_BIT_BOTTOM
        elif bottom is not None:
            lights_enabled |= LIGHTS_ENABLED_BIT_BOTTOM
        if wheel is not None or bottom is not None:
            lights_enabled |= LIGHTS_ENABLED_BIT_CUSTOM_COLOR  # use our RGB, not palette
        s[14] = lights_enabled & 0xFF

        s[16] = LIGHT_EFFECT[effect]
        s[17] = max(1, min(3, speed))

        # We are deliberately not touching color_flow; leave whatever was there.
        # If the user wants 'solid', the effect field already enforces it.

        write_profile_settings(dev, s, verbose)
        print(f"{name}: profile {profile_index} updated. "
              f"wheel={fmt_color((s[19], s[20], s[21]))} "
              f"bottom={fmt_color((s[24], s[25], s[26]))} "
              f"effect={effect} speed={s[17]} "
              f"enabled_bits=0x{s[14]:02x}")
    finally:
        dev.close()


def cmd_off_persist(profile_index: int | None, verbose: bool) -> None:
    dev, name = open_tyon()
    try:
        if profile_index is None:
            profile_index = read_active_profile_index(dev, verbose)
        s = read_profile_settings(dev, profile_index, verbose)
        s[14] &= ~(LIGHTS_ENABLED_BIT_WHEEL | LIGHTS_ENABLED_BIT_BOTTOM)
        s[16] = LIGHT_EFFECT["off"]
        write_profile_settings(dev, s, verbose)
        print(f"{name}: profile {profile_index} lighting disabled")
    finally:
        dev.close()


def cmd_invert_wheel(profile_index: int | None, inverted: bool,
                     verbose: bool) -> None:
    dev, name = open_tyon()
    try:
        if profile_index is None:
            profile_index = read_active_profile_index(dev, verbose)
        b = read_profile_buttons(dev, profile_index, verbose)
        set_wheel_inverted(b, inverted)
        write_profile_buttons(dev, b, verbose)
        print(f"{name}: profile {profile_index} wheel = "
              f"{'inverted' if inverted else 'normal'}")
    finally:
        dev.close()


def cmd_set_polling(profile_index: int | None, hz: int, verbose: bool) -> None:
    dev, name = open_tyon()
    try:
        if profile_index is None:
            profile_index = read_active_profile_index(dev, verbose)
        s = read_profile_settings(dev, profile_index, verbose)
        set_polling_rate_hz(s, hz)
        write_profile_settings(dev, s, verbose)
        print(f"{name}: profile {profile_index} polling = {hz} Hz")
    finally:
        dev.close()


def cmd_set_dpi(profile_index: int | None, cpis: list[int],
                active_idx: int | None, verbose: bool) -> None:
    dev, name = open_tyon()
    try:
        if profile_index is None:
            profile_index = read_active_profile_index(dev, verbose)
        s = read_profile_settings(dev, profile_index, verbose)
        before = get_cpi_levels(s)
        set_cpi_levels(s, cpis)
        # enable exactly the stages we were given
        mask = 0
        for i in range(min(CPI_LEVEL_NUM, len(cpis))):
            if cpis[i]:
                mask |= (1 << i)
        if mask:
            set_cpi_enabled_mask(s, mask)
        if active_idx is not None:
            set_cpi_active(s, active_idx)
        write_profile_settings(dev, s, verbose)
        print(f"{name}: profile {profile_index} dpi {before} -> "
              f"{get_cpi_levels(s)} cpi  active_idx={get_cpi_active(s)}")
    finally:
        dev.close()


def cmd_demo_live() -> None:
    seq = [
        ("red",   (0xFF, 0x00, 0x00)),
        ("green", (0x00, 0xFF, 0x00)),
        ("blue",  (0x00, 0x00, 0xFF)),
        ("white", (0xFF, 0xFF, 0xFF)),
    ]
    dev, name = open_tyon()
    try:
        for label, rgb in seq:
            talkfx_send(dev, rgb, rgb, LIGHT_EFFECT["solid"], 2, False)
            print(f"[{name}] {label}")
            time.sleep(1.0)
    finally:
        dev.close()


def cmd_live(ambient: tuple[int, int, int], event: tuple[int, int, int],
             effect: str, speed: int, off: bool, verbose: bool) -> None:
    dev, name = open_tyon()
    try:
        talkfx_send(dev, ambient, event, LIGHT_EFFECT[effect], speed, verbose, off)
        if off:
            print(f"{name}: TalkFX off")
        else:
            print(f"{name}: live ambient={fmt_color(ambient)} "
                  f"event={fmt_color(event)} effect={effect} speed={speed}")
    finally:
        dev.close()


# ---------- entry point ----------

def main() -> None:
    p = argparse.ArgumentParser(description="Roccat Tyon RGB control")

    p.add_argument("--probe", action="store_true",
                   help="List Tyon HID interfaces")
    p.add_argument("--read", action="store_true",
                   help="Read and print current lighting settings")
    p.add_argument("--off", action="store_true",
                   help="Turn lighting off")
    p.add_argument("--demo-live", action="store_true",
                   help="Cycle R->G->B->W via TalkFX (volatile)")
    p.add_argument("--live", action="store_true",
                   help="Use TalkFX (RAM-only, instant, not persistent)")

    p.add_argument("--profile", type=int, choices=range(PROFILE_NUM),
                   metavar="0..4",
                   help="Profile index 0-4 (default: currently active)")
    p.add_argument("--color", type=parse_color, metavar="RRGGBB",
                   help="Both wheel + bottom to this color")
    p.add_argument("--wheel", type=parse_color, metavar="RRGGBB",
                   help="Wheel color (persistent path only)")
    p.add_argument("--bottom", type=parse_color, metavar="RRGGBB",
                   help="Bottom color (persistent path only)")
    p.add_argument("--ambient", type=parse_color, metavar="RRGGBB",
                   help="TalkFX ambient color (--live only)")
    p.add_argument("--event", type=parse_color, metavar="RRGGBB",
                   help="TalkFX event color (--live only)")
    p.add_argument("--wheel-off", action="store_true",
                   help="Disable wheel light bit (persistent)")
    p.add_argument("--bottom-off", action="store_true",
                   help="Disable bottom light bit (persistent)")
    p.add_argument("--effect", default="solid", choices=list(LIGHT_EFFECT),
                   help="Lighting effect (default: solid)")
    p.add_argument("--speed", type=int, default=2, choices=[1, 2, 3],
                   help="Effect speed 1..3 (default 2)")
    p.add_argument("--invert-wheel", choices=["on", "off"],
                   help="Invert scroll wheel direction (onboard, persistent)")
    p.add_argument("--polling", type=int, choices=[125, 250, 500, 1000],
                   metavar="HZ", help="Set polling rate (persistent)")
    p.add_argument("--dpi", type=str, metavar="LIST",
                   help="Set DPI stages, comma-separated cpi "
                        "(e.g. 400,800,1600,3200,8200)")
    p.add_argument("--dpi-active", type=int, choices=range(5), metavar="0..4",
                   help="Active DPI stage index (use with --dpi)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Print raw HID traffic")

    args = p.parse_args()

    if args.probe:
        cmd_probe()
        return

    if args.demo_live:
        cmd_demo_live()
        return

    if args.read:
        cmd_read(args.profile, args.verbose)
        return

    if args.invert_wheel is not None:
        cmd_invert_wheel(args.profile, args.invert_wheel == "on", args.verbose)
        return

    if args.polling is not None:
        cmd_set_polling(args.profile, args.polling, args.verbose)
        return

    if args.dpi is not None:
        try:
            cpis = [int(x) for x in args.dpi.split(",") if x.strip()]
        except ValueError:
            p.error("--dpi must be comma-separated integers, e.g. 400,800,1600")
        if not cpis:
            p.error("--dpi needs at least one value")
        cmd_set_dpi(args.profile, cpis, args.dpi_active, args.verbose)
        return

    # --- LIVE / TalkFX path ---
    if args.live:
        ambient = args.ambient or args.color
        event = args.event or args.color or ambient
        if args.off:
            cmd_live((0, 0, 0), (0, 0, 0), "off", 1, True, args.verbose)
            return
        if ambient is None:
            p.error("--live needs --color or --ambient/--event")
        cmd_live(ambient, event or ambient, args.effect, args.speed,
                 False, args.verbose)
        return

    # --- PERSISTENT path (default) ---
    if args.off:
        cmd_off_persist(args.profile, args.verbose)
        return

    wheel = args.wheel or args.color
    bottom = args.bottom or args.color
    if wheel is None and bottom is None and not args.wheel_off and not args.bottom_off:
        p.error("nothing to do; try --color RRGGBB, --read, --off, --probe, "
                "or --demo-live")

    cmd_persist(args.profile, wheel, bottom, args.effect, args.speed,
                args.wheel_off, args.bottom_off, args.verbose)


if __name__ == "__main__":
    try:
        main()
    except TyonNotFoundError as e:
        sys.exit(f"ERROR: {e}")
