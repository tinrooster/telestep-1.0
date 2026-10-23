"""telestep_settings.py - remembered settings, presets and toolbar position (one small JSON file)."""
import json
import os
from pathlib import Path

DEFAULT_HOTKEYS = {"pause": "f9", "stop": "f10", "note": "ctrl+shift+f7", "shot": "ctrl+shift+f8",
                   "undo": "ctrl+shift+f6"}

DEFAULTS = {
    "base_dir": str(Path.home() / "Documents" / "Telestep"),
    # capture
    "capture_mode": "screen", "monitor": 1, "region": None, "exclude_taskbar": False,
    "after_mode": "off", "after_delay_ms": 700, "max_width": 1600,
    "dbl": True, "drag": True, "scroll": False, "shortcuts": True, "watch_dialogs": True,
    # privacy
    "masks": [], "mask_style": "solid", "key_mode": "count",
    "ocr": {"ip": False, "mac": False, "key": False, "email": False}, "ocr_style": "solid",
    # report
    "formats": {"md": True, "docx": True, "html": False, "pdf": False, "txt": False},
    "review_after_stop": True, "wording": "friendly",
    "template": {"header": "", "footer": "", "logo": "", "author": "", "environment": True},
    # app
    "hotkeys": dict(DEFAULT_HOTKEYS), "flash": True, "sound": False, "tray": False, "hide_in_tray": False, "close_to_tray": True,
    "hide_from_capture": True, "overlays": True, "toolbar_pos": None, "presets": {},
}
NESTED = ("ocr", "formats", "template", "hotkeys")
# what a preset stores (everything except per-machine bits and the preset list itself)
PRESET_KEYS = [k for k in DEFAULTS if k not in ("base_dir", "toolbar_pos", "presets")]


def settings_path():
    root = os.environ.get("APPDATA")
    base = Path(root) / "Telestep" if root else Path.home() / ".telestep_recorder"
    return base / "settings.json"


def merge(base, over):
    out = json.loads(json.dumps(base))
    for k, v in (over or {}).items():
        if k not in out:
            continue
        if k in NESTED and isinstance(v, dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def load(path=None):
    p = Path(path) if path else settings_path()
    try:
        return merge(DEFAULTS, json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return merge(DEFAULTS, {})


def save(data, path=None):
    p = Path(path) if path else settings_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, p)
        return True
    except OSError:
        return False


def preset_of(settings):
    return json.loads(json.dumps({k: settings[k] for k in PRESET_KEYS}))
