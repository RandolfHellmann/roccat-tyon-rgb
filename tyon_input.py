# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Randolf Hellmann
"""Host-side input recording & playback for StarCraft II build orders.

WHAT THIS IS
------------
A practice / comfort aid. You record one of your own opening build orders once,
from a fixed camera anchor, and the tool can replay that exact input sequence so
the same on-screen clicks land on the same build locations every game. The
determinism comes from three honest tricks, not from reading or modifying the
game:

* **Camera anchor** — before replay we tap a camera key (default Backspace,
  which centres SC2 on your main town hall) so the world-to-screen mapping is
  the same as when you recorded.
* **Resolution scaling** — recorded clicks are stored with the screen size they
  were captured at and rescaled to the current screen.
* **Faithful replay** — we reproduce your recorded keys and clicks verbatim
  (including any Shift-queueing you did yourself), at the recorded timing.

WHAT THIS IS NOT
----------------
This does not give an in-combat advantage. There is no aim assistance, no
recoil compensation, no rapid fire, no reaction-time automation. It only
replays a build order you performed yourself. StarCraft II has no kernel-level
anti-cheat, but automated input is a Blizzard ToS grey area — use it for
practice / ladder warm-up and at your own discretion.

This module is intentionally separate from the onboard macro path
(``tyon_rgb.write_macro``), which runs on the mouse firmware with no host
process and is the right choice for anti-cheat-protected games.
"""
from __future__ import annotations

import ctypes
import json
import threading
import time

try:
    from pynput import keyboard, mouse
    _IMPORT_ERROR: Exception | None = None
except Exception as exc:                      # pragma: no cover - import guard
    keyboard = mouse = None                   # type: ignore
    _IMPORT_ERROR = exc

FILE_FORMAT_VERSION = 1


# ---------- screen helpers ----------

def screen_size() -> tuple[int, int]:
    """Primary-monitor size in physical pixels (Windows). (0, 0) on failure."""
    try:
        user32 = ctypes.windll.user32          # type: ignore[attr-defined]
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return (0, 0)


# ---------- key (de)serialisation ----------

def key_to_str(key) -> str:
    """Serialise a pynput key/keycode to a stable string."""
    char = getattr(key, "char", None)
    if char is not None:
        return char
    name = getattr(key, "name", None)
    if name is not None:
        return name
    vk = getattr(key, "vk", None)
    if vk is not None:
        return f"vk:{vk}"
    return str(key)


def str_to_key(s: str):
    """Inverse of key_to_str; returns a pynput Key or KeyCode."""
    if keyboard is None:
        raise RuntimeError(_import_error_message())
    if s.startswith("vk:"):
        return keyboard.KeyCode.from_vk(int(s[3:]))
    if len(s) == 1:
        return keyboard.KeyCode.from_char(s)
    try:
        return getattr(keyboard.Key, s)
    except AttributeError:
        return keyboard.KeyCode.from_char(s)


def _import_error_message() -> str:
    return (f"pynput is required for host-side recording/playback but could "
            f"not be imported: {_IMPORT_ERROR}")


def available() -> bool:
    """True if pynput imported successfully and host input is usable."""
    return _IMPORT_ERROR is None


# ---------- recording ----------

class Recorder:
    """Records keyboard + mouse-click + scroll events with relative timing.

    Continuous mouse moves are not recorded by default: build-order playback
    teleports the cursor to each click position, which is faster and more
    deterministic than replaying a motion path.
    """

    def __init__(self, record_moves: bool = False, stop_key: str | None = "f10"):
        if _IMPORT_ERROR is not None:
            raise RuntimeError(_import_error_message())
        self.record_moves = record_moves
        self.stop_key = stop_key
        self.events: list[dict] = []
        self.screen = screen_size()
        self._t0: float | None = None
        self._kb = None
        self._ms = None
        self._lock = threading.Lock()
        self._on_stop = None

    # -- lifecycle --
    def start(self, on_stop=None) -> None:
        self.events = []
        self.screen = screen_size()
        self._t0 = time.perf_counter()
        self._on_stop = on_stop
        self._kb = keyboard.Listener(on_press=self._on_press,
                                     on_release=self._on_release)
        self._ms = mouse.Listener(on_click=self._on_click,
                                  on_scroll=self._on_scroll,
                                  on_move=self._on_move if self.record_moves else None)
        self._kb.start()
        self._ms.start()

    def stop(self) -> list[dict]:
        if self._kb:
            self._kb.stop()
            self._kb = None
        if self._ms:
            self._ms.stop()
            self._ms = None
        cb, self._on_stop = self._on_stop, None
        if cb:
            try:
                cb(self.events)
            except Exception:
                pass
        return self.events

    def is_recording(self) -> bool:
        return self._kb is not None

    # -- internals --
    def _now(self) -> float:
        return time.perf_counter() - (self._t0 or time.perf_counter())

    def _add(self, ev: dict) -> None:
        with self._lock:
            self.events.append(ev)

    def _on_press(self, key):
        if self.stop_key is not None and key_to_str(key) == self.stop_key:
            self.stop()
            return False
        self._add({"t": self._now(), "kind": "key",
                   "action": "press", "key": key_to_str(key)})

    def _on_release(self, key):
        self._add({"t": self._now(), "kind": "key",
                   "action": "release", "key": key_to_str(key)})

    def _on_click(self, x, y, button, pressed):
        self._add({"t": self._now(), "kind": "click",
                   "action": "press" if pressed else "release",
                   "button": button.name, "x": int(x), "y": int(y)})

    def _on_scroll(self, x, y, dx, dy):
        self._add({"t": self._now(), "kind": "scroll",
                   "x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)})

    def _on_move(self, x, y):
        self._add({"t": self._now(), "kind": "move", "x": int(x), "y": int(y)})


# ---------- playback ----------

class Player:
    """Replays a recorded event list with optional camera anchor + scaling."""

    def __init__(self):
        if _IMPORT_ERROR is not None:
            raise RuntimeError(_import_error_message())
        self._kb = keyboard.Controller()
        self._ms = mouse.Controller()
        self._abort = threading.Event()
        self._abort_listener = None

    def abort(self) -> None:
        self._abort.set()

    def play(self, events: list[dict], *, speed: float = 1.0,
             src_screen: tuple[int, int] | None = None,
             dst_screen: tuple[int, int] | None = None,
             camera_anchor: str | None = None,
             start_delay: float = 0.0,
             abort_key: str | None = "f12",
             on_progress=None) -> bool:
        """Replay events. Returns True if it finished, False if aborted.

        speed         playback-speed multiplier (1.0 == recorded timing)
        src_screen    screen size the events were recorded at (for scaling)
        dst_screen    current screen size (defaults to the live primary screen)
        camera_anchor key tapped once before replay (e.g. "backspace" for SC2)
        start_delay   seconds to wait before the first event (alt-tab grace)
        abort_key     key that stops playback immediately (default F12)
        """
        self._abort.clear()
        dst_screen = dst_screen or screen_size()
        sx = sy = 1.0
        if src_screen and dst_screen and src_screen[0] and src_screen[1]:
            sx = dst_screen[0] / src_screen[0]
            sy = dst_screen[1] / src_screen[1]

        def scale(x, y):
            return int(round(x * sx)), int(round(y * sy))

        self._start_abort_listener(abort_key)
        try:
            if start_delay > 0:
                if not self._sleep_abortable(start_delay):
                    return False
            if camera_anchor:
                self._tap(camera_anchor)
                if not self._sleep_abortable(0.15):
                    return False

            t_prev = 0.0
            total = len(events)
            for i, ev in enumerate(events):
                if self._abort.is_set():
                    return False
                dt = (ev.get("t", 0.0) - t_prev) / max(0.05, speed)
                if dt > 0 and not self._sleep_abortable(dt):
                    return False
                t_prev = ev.get("t", t_prev)
                self._dispatch(ev, scale)
                if on_progress:
                    try:
                        on_progress(i + 1, total)
                    except Exception:
                        pass
            return not self._abort.is_set()
        finally:
            self._stop_abort_listener()
            self._release_all()

    # -- internals --
    def _dispatch(self, ev: dict, scale) -> None:
        kind = ev.get("kind")
        if kind == "key":
            key = str_to_key(ev["key"])
            (self._kb.press if ev["action"] == "press" else self._kb.release)(key)
        elif kind == "click":
            self._ms.position = scale(ev["x"], ev["y"])
            btn = getattr(mouse.Button, ev.get("button", "left"), mouse.Button.left)
            (self._ms.press if ev["action"] == "press" else self._ms.release)(btn)
        elif kind == "scroll":
            self._ms.position = scale(ev["x"], ev["y"])
            self._ms.scroll(ev.get("dx", 0), ev.get("dy", 0))
        elif kind == "move":
            self._ms.position = scale(ev["x"], ev["y"])

    def _tap(self, key_name: str) -> None:
        key = str_to_key(key_name)
        self._kb.press(key)
        time.sleep(0.03)
        self._kb.release(key)

    def _sleep_abortable(self, dt: float) -> bool:
        """Sleep up to dt seconds; return False if aborted during the wait."""
        end = time.perf_counter() + dt
        while True:
            remaining = end - time.perf_counter()
            if self._abort.is_set():
                return False
            if remaining <= 0:
                return True
            time.sleep(min(0.02, remaining))

    def _start_abort_listener(self, abort_key: str | None) -> None:
        if not abort_key:
            return

        def on_press(key):
            if key_to_str(key) == abort_key:
                self._abort.set()
                return False

        self._abort_listener = keyboard.Listener(on_press=on_press)
        self._abort_listener.start()

    def _stop_abort_listener(self) -> None:
        if self._abort_listener:
            self._abort_listener.stop()
            self._abort_listener = None

    def _release_all(self) -> None:
        """Best-effort release of modifiers so a mid-abort can't stick a key."""
        for k in ("shift", "ctrl", "alt", "cmd"):
            try:
                self._kb.release(getattr(keyboard.Key, k))
            except Exception:
                pass


# ---------- build-order container + (de)serialisation ----------

class BuildOrder:
    """A named, replayable build order: events + the context to reproduce them."""

    def __init__(self, name: str, events: list[dict], screen: tuple[int, int],
                 game: str = "StarCraft II", camera_anchor: str = "backspace",
                 notes: str = ""):
        self.name = name
        self.events = events
        self.screen = tuple(screen)
        self.game = game
        self.camera_anchor = camera_anchor
        self.notes = notes

    @property
    def duration(self) -> float:
        return self.events[-1]["t"] if self.events else 0.0

    def to_dict(self) -> dict:
        return {
            "format": FILE_FORMAT_VERSION,
            "name": self.name,
            "game": self.game,
            "camera_anchor": self.camera_anchor,
            "screen": list(self.screen),
            "notes": self.notes,
            "events": self.events,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BuildOrder":
        return cls(
            name=d.get("name", "Unnamed"),
            events=d.get("events", []),
            screen=tuple(d.get("screen", (0, 0))),
            game=d.get("game", "StarCraft II"),
            camera_anchor=d.get("camera_anchor", "backspace"),
            notes=d.get("notes", ""),
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "BuildOrder":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


if __name__ == "__main__":
    # Tiny self-test: serialise/deserialise round-trip without touching input.
    print("pynput available:", available())
    print("screen size:", screen_size())
    bo = BuildOrder("test", [{"t": 0.0, "kind": "key", "action": "press", "key": "b"}],
                    screen=(2560, 1440))
    d = bo.to_dict()
    bo2 = BuildOrder.from_dict(d)
    assert bo2.events == bo.events and bo2.screen == bo.screen
    print("round-trip OK; duration:", bo2.duration)
