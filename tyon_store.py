# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Randolf Hellmann
"""Persistent user state: GUI preferences, game profiles, and build orders.

Everything lives under ``%APPDATA%\\RoccatTyonRGB`` on Windows (``~/.config`` as
a fallback) so the repository stays clean and settings survive a reinstall or a
``git pull``.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

APP_NAME = "RoccatTyonRGB"
RECENT_MAX = 5


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        d = Path(base) / APP_NAME
    else:
        d = Path.home() / ".config" / "roccat-tyon-rgb"
    d.mkdir(parents=True, exist_ok=True)
    return d


PREFS_PATH = config_dir() / "prefs.json"
GAME_PROFILES_PATH = config_dir() / "game_profiles.json"
BUILD_ORDERS_DIR = config_dir() / "build_orders"


# ---------- low-level json helpers ----------

def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic on Windows when same volume


# ---------- preferences (recent colors, last UI state) ----------

DEFAULT_PREFS = {
    "recent_colors": [],
    "last_profile": 0,
    "last_zone": 0,          # 0=both, 1=wheel, 2=bottom
    "brightness": 100,
}


def load_prefs() -> dict:
    prefs = dict(DEFAULT_PREFS)
    prefs.update(_read_json(PREFS_PATH, {}))
    _migrate_legacy_recent(prefs)
    return prefs


def save_prefs(prefs: dict) -> None:
    _write_json(PREFS_PATH, prefs)


def _migrate_legacy_recent(prefs: dict) -> None:
    """Import recent colors from the old repo-local recent.json (one time)."""
    if prefs.get("recent_colors"):
        return
    legacy = Path(__file__).resolve().parent / "recent.json"
    data = _read_json(legacy, None)
    if isinstance(data, dict):
        colors = [c for c in data.get("recent", []) if isinstance(c, str)]
        if colors:
            prefs["recent_colors"] = colors[:RECENT_MAX]


def push_recent_color(prefs: dict, hex_color: str) -> None:
    hex_color = hex_color.upper()
    recent = [c for c in prefs.get("recent_colors", []) if c.upper() != hex_color]
    recent.insert(0, hex_color)
    prefs["recent_colors"] = recent[:RECENT_MAX]


# ---------- game profiles ----------
#
# A game profile maps a game to an onboard mouse profile and (optionally) a
# process name for the opt-in auto-switch watcher. Auto-switch only changes
# which onboard profile is *active* on the mouse; it never injects input into a
# running game, so it is safe even for kernel-anti-cheat titles.

def default_game_profiles() -> list[dict]:
    return [
        {
            "name": "Call of Duty: Warzone",
            "exe": "cod.exe",
            "mouse_profile": 1,
            "auto_switch": False,
            "note": "Onboard macros only — no host input (Ricochet-safe).",
        },
        {
            "name": "StarCraft II",
            "exe": "SC2_x64.exe",
            "mouse_profile": 2,
            "auto_switch": False,
            "note": "Build-order replay available (host-side, practice aid).",
        },
        {
            "name": "Desktop",
            "exe": "",
            "mouse_profile": 0,
            "auto_switch": False,
            "note": "Default profile when no game is running.",
        },
    ]


def load_game_profiles() -> list[dict]:
    data = _read_json(GAME_PROFILES_PATH, None)
    if not isinstance(data, list) or not data:
        data = default_game_profiles()
        _write_json(GAME_PROFILES_PATH, data)
    return data


def save_game_profiles(profiles: list[dict]) -> None:
    _write_json(GAME_PROFILES_PATH, profiles)


# ---------- build orders ----------

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_").lower()
    return slug or "build_order"


def build_order_path(name: str) -> Path:
    BUILD_ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    return BUILD_ORDERS_DIR / f"{_slugify(name)}.json"


def list_build_orders() -> list[Path]:
    if not BUILD_ORDERS_DIR.exists():
        return []
    return sorted(BUILD_ORDERS_DIR.glob("*.json"))


def delete_build_order(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    print("config dir:", config_dir())
    p = load_prefs()
    print("prefs:", p)
    print("game profiles:", len(load_game_profiles()))
    print("build orders:", [b.name for b in list_build_orders()])
