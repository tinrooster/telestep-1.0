"""Pieces shared by every backend (pure Python, no OS calls)."""
import re

EMPTY_INFO = {"hwnd": 0, "title": "", "cls": "", "pid": 0}
SKIP_TITLES = set()  # our own click-through overlay windows: never report them as "the window under the cursor"


def box(l, t, r, b):
    return {"left": l, "top": t, "width": r - l, "height": b - t}


# Hotkey specs ('ctrl+shift+f8') are stored and checked the same way everywhere; the codes below are Windows
# virtual-key codes, which other backends translate as they need.
_MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
_VK_NAMED = {"esc": 0x1B, "space": 0x20, "enter": 0x0D, "tab": 0x09, "delete": 0x2E, "insert": 0x2D,
             "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "pause": 0x13, "printscreen": 0x2C}


def parse_hotkey(spec):
    """'ctrl+shift+f8' -> (mod_flags, vk).  Raises ValueError for anything it can't map."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    mods, key = 0, parts[-1]
    for p in parts[:-1]:
        if p not in _MODS:
            raise ValueError(f"unknown modifier {p!r}")
        mods |= _MODS[p]
    m = re.fullmatch(r"f(\d{1,2})", key)
    if m and 1 <= int(m.group(1)) <= 24:
        return mods, 0x70 + int(m.group(1)) - 1
    if len(key) == 1 and key.isalnum():
        return mods, ord(key.upper())
    if key in _VK_NAMED:
        return mods, _VK_NAMED[key]
    raise ValueError(f"unknown key {key!r}")
