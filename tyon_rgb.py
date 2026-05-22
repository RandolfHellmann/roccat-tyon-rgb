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


def select_profile(dev, profile_index: int, request: int, verbose: bool) -> None:
    """Send the CONTROL select packet, then verify."""
    write_feature(
        dev,
        bytes([REPORT_ID_CONTROL, profile_index & 0x1F, request]),
        f"SELECT profile={profile_index} req=0x{request:02x}",
        verbose,
    )
    check_write(dev, verbose)


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
