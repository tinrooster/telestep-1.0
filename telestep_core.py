"""
telestep_core.py - shared low-level helpers for Telestep (no GUI, no recorder logic).

  * DPI awareness (set on import, before any coordinates are read)
  * text/name cleaning, geometry
  * Windows helpers via ctypes (window/process info, hotkeys, monitors).  Every one of them
    degrades to "nothing" on other systems so the logic can be unit-tested anywhere.
  * mask styles + window-following masks + optional OCR redaction
  * marker annotation (click circle, double-click, drag arrow, scroll arrow, step badge)
"""
import ctypes
import datetime as dt
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path

# Must happen before any coordinates are read, or clicks land offset on scaled displays.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat  # noqa: E402

VERSION = "1.0"


def _no_console_windows():
    """Telestep is a window-only program, but the helper programs it starts (Tesseract for OCR, ipconfig in Support
    mode) are console programs: each one can flash a black window, and OCR starts several per click.  Ask Windows not
    to create a console for any child process we start."""
    import subprocess
    import sys
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if sys.platform != "win32" or not flag or getattr(subprocess.Popen, "_telestep_quiet", False):
        return
    real = subprocess.Popen

    class QuietPopen(real):
        _telestep_quiet = True

        def __init__(self, *a, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | flag
            super().__init__(*a, **kw)

    subprocess.Popen = QuietPopen


_no_console_windows()


# ---------------------------------------------------------------------------
# text / name helpers
# ---------------------------------------------------------------------------
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_text(s):
    """Strip what Word/XML cannot store (control characters, ANSI colour codes, lone surrogates)
    so one odd character in a note or window title can't break the whole export."""
    s = _ANSI.sub("", s or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return _XML_BAD.sub("", s)


def session_dir_name(title="", now=None):
    """'20261022_182830' or '20261022_182830_Fix_Teams_audio' - always a valid Windows folder name."""
    stamp = (now or dt.datetime.now()).strftime("%Y%m%d_%H%M%S")
    slug = _BAD_NAME.sub("", title or "")
    slug = re.sub(r"\s+", "_", slug.strip()).strip("._")[:60]
    return f"{stamp}_{slug}" if slug else stamp


# ---------------------------------------------------------------------------
# geometry (screen pixels; box = {"left","top","width","height"}, rect = (l, t, r, b))
# ---------------------------------------------------------------------------
def _box(l, t, r, b):
    return {"left": l, "top": t, "width": r - l, "height": b - t}


def _contains(b, x, y):
    return b["left"] <= x < b["left"] + b["width"] and b["top"] <= y < b["top"] + b["height"]


def _intersect(a, b):
    l = max(a["left"], b["left"])
    t = max(a["top"], b["top"])
    r = min(a["left"] + a["width"], b["left"] + b["width"])
    bt = min(a["top"] + a["height"], b["top"] + b["height"])
    if r - l < 1 or bt - t < 1:
        return None
    return _box(l, t, r, bt)


def in_rects(x, y, rects):
    return any(l <= x < r and t <= y < b for (l, t, r, b) in rects)


# ---------------------------------------------------------------------------
# Windows helpers (private DLL handles so we never touch argtypes other libraries rely on)
# ---------------------------------------------------------------------------
_dlls = {}


def _dll(name):
    d = _dlls.get(name)
    if d is None:
        d = _dlls[name] = ctypes.WinDLL(name, use_last_error=True)  # AttributeError off Windows
    return d


def _sig(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


def _info_of(hwnd):
    from ctypes import wintypes
    u = _dll("user32")
    buf = ctypes.create_unicode_buffer(512)
    _sig(u.GetWindowTextW, ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)(hwnd, buf, 512)
    title = buf.value
    cbuf = ctypes.create_unicode_buffer(256)
    _sig(u.GetClassNameW, ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)(hwnd, cbuf, 256)
    pid = wintypes.DWORD()
    _sig(u.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))(
        hwnd, ctypes.byref(pid))
    return {"hwnd": hwnd or 0, "title": title, "cls": cbuf.value, "pid": pid.value}


_EMPTY_INFO = {"hwnd": 0, "title": "", "cls": "", "pid": 0}
SKIP_TITLES = set()  # our own click-through overlay windows: never report them as "the window under the cursor"


def _hit(x, y):
    """hwnd under the point.  If that is one of our own overlays, look through it (z-order walk)."""
    from ctypes import wintypes
    u = _dll("user32")
    hwnd = _sig(u.WindowFromPoint, wintypes.HWND, wintypes.POINT)(wintypes.POINT(int(x), int(y)))
    if SKIP_TITLES and hwnd:
        root = _sig(u.GetAncestor, wintypes.HWND, wintypes.HWND, wintypes.UINT)(hwnd, 2) or hwnd
        if _info_of(root)["title"] in SKIP_TITLES:
            for win in list_windows():  # EnumWindows order = top of the z-order first
                l, t, r, b = win["rect"]
                if win["title"] not in SKIP_TITLES and l <= x < r and t <= y < b:
                    return win["hwnd"]
    return hwnd


def window_info(x, y):
    """{'hwnd','title','cls','pid'} of the top-level window under the point (Windows)."""
    try:
        from ctypes import wintypes
        hwnd = _hit(x, y)
        root = _sig(_dll("user32").GetAncestor, wintypes.HWND, wintypes.HWND, wintypes.UINT)(hwnd, 2) or hwnd
        return _info_of(root)
    except Exception:
        return dict(_EMPTY_INFO)


def window_at(x, y):
    return window_info(x, y)["title"]


def foreground_info():
    try:
        from ctypes import wintypes
        hwnd = _sig(_dll("user32").GetForegroundWindow, wintypes.HWND)()
        return _info_of(hwnd) if hwnd else dict(_EMPTY_INFO)
    except Exception:
        return dict(_EMPTY_INFO)


def own_process_active():
    """True/False: is the foreground window one of this program's (toolbar, dialogs, drop-downs)?  None if unknown.
    More reliable than Tk's focus, which reads 'none' right after a dialog or drop-down closes."""
    try:
        import os
        from ctypes import wintypes
        u = _dll("user32")
        hwnd = _sig(u.GetForegroundWindow, wintypes.HWND)()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        _sig(u.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))(
            hwnd, ctypes.byref(pid))
        return pid.value == os.getpid()
    except Exception:
        return None


def foreground_title():
    return foreground_info()["title"]


def _frame_rect(hwnd):
    from ctypes import wintypes
    rc = wintypes.RECT()
    ok = _dll("dwmapi").DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(rc), ctypes.sizeof(rc)) == 0
    if not ok:  # 9 = DWMWA_EXTENDED_FRAME_BOUNDS (skips the invisible resize shadow)
        _dll("user32").GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
    return rc.left, rc.top, rc.right, rc.bottom


def window_rect(x, y):
    """Box of the top-level window under the point, unioned with its owner (so popup menus
    still show the app window they belong to)."""
    try:
        from ctypes import wintypes
        u = _dll("user32")
        hwnd0 = _hit(x, y)
        ga = _sig(u.GetAncestor, wintypes.HWND, wintypes.HWND, wintypes.UINT)
        rects = [_frame_rect(ga(hwnd0, flag)) for flag in (2, 3)]  # GA_ROOT, GA_ROOTOWNER
        l = min(r[0] for r in rects)
        t = min(r[1] for r in rects)
        r_ = max(r[2] for r in rects)
        b = max(r[3] for r in rects)
        return _box(l, t, r_, b) if r_ > l and b > t else None
    except Exception:
        return None


def list_windows():
    """Visible, non-minimised, titled top-level windows: [{'hwnd','title','cls','pid','rect'}]."""
    out = []
    try:
        from ctypes import wintypes
        u = _dll("user32")
        visible = _sig(u.IsWindowVisible, wintypes.BOOL, wintypes.HWND)
        iconic = _sig(u.IsIconic, wintypes.BOOL, wintypes.HWND)
        proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _lp):
            try:
                if not visible(hwnd) or iconic(hwnd):
                    return True
                info = _info_of(hwnd)
                if not info["title"]:
                    return True
                cloaked = wintypes.DWORD()
                _dll("dwmapi").DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), 4)
                if cloaked.value:  # hidden UWP / other-desktop windows
                    return True
                l, t, r, b = _frame_rect(hwnd)
                if r - l < 2 or b - t < 2:
                    return True
                info["rect"] = (l, t, r, b)
                out.append(info)
            except Exception:
                pass
            return True

        _sig(u.EnumWindows, wintypes.BOOL, proc, wintypes.LPARAM)(proc(cb), 0)
    except Exception:
        pass
    return out


def find_windows(substr):
    """Screen rects of visible windows whose title contains `substr` (case-insensitive)."""
    s = (substr or "").strip().casefold()
    if not s:
        return []
    return [w["rect"] for w in list_windows() if s in w["title"].casefold()]


def work_area_at(x, y):
    """((work L,T,R,B), (monitor L,T,R,B)) for the monitor containing the point, or None.
    The work area is the monitor minus the taskbar (and other docked app bars)."""
    try:
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        u = _dll("user32")
        hmon = _sig(u.MonitorFromPoint, wintypes.HANDLE, wintypes.POINT, wintypes.DWORD)(
            wintypes.POINT(int(x), int(y)), 2)  # MONITOR_DEFAULTTONEAREST
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not _sig(u.GetMonitorInfoW, wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(MONITORINFO))(
                hmon, ctypes.byref(mi)):
            return None
        w, m = mi.rcWork, mi.rcMonitor
        return (w.left, w.top, w.right, w.bottom), (m.left, m.top, m.right, m.bottom)
    except Exception:
        return None


def taskbar_strips(monitors):
    """Taskbar/app-bar strips of every monitor in an mss-style list (index 0 = whole desktop)."""
    strips = []
    for m in monitors[1:]:
        info = work_area_at(m["left"] + m["width"] // 2, m["top"] + m["height"] // 2)
        if not info:
            continue
        (wl, wt, wr, wb), (ml, mt, mr, mb) = info
        if wl > ml:
            strips.append((ml, mt, wl, mb))
        if wr < mr:
            strips.append((wr, mt, mr, mb))
        if wt > mt:
            strips.append((ml, mt, mr, wt))
        if wb < mb:
            strips.append((ml, wb, mr, mb))
    return strips


def cursor_pos():
    try:
        from ctypes import wintypes
        pt = wintypes.POINT()
        _dll("user32").GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return None


def double_click_time():
    try:
        return _dll("user32").GetDoubleClickTime() / 1000.0
    except Exception:
        return 0.5


def is_admin():
    try:
        return bool(_dll("shell32").IsUserAnAdmin())
    except Exception:
        return False


def process_path(pid):
    try:
        from ctypes import wintypes
        k = _dll("kernel32")
        h = _sig(k.OpenProcess, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)(0x1000, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            ok = _sig(k.QueryFullProcessImageNameW, wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD,
                      wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))(h, 0, buf, ctypes.byref(size))
            return buf.value if ok else ""
        finally:
            _sig(k.CloseHandle, wintypes.BOOL, wintypes.HANDLE)(h)
    except Exception:
        return ""


def process_elevated(pid):
    """True / False, or None if unknown.  Access-denied on the token means "more privileged than us"."""
    try:
        from ctypes import wintypes
        k, a = _dll("kernel32"), _dll("advapi32")
        close = _sig(k.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
        h = _sig(k.OpenProcess, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)(0x1000, False, pid)
        if not h:
            return True if ctypes.get_last_error() == 5 else None
        try:
            tok = wintypes.HANDLE()
            if not _sig(a.OpenProcessToken, wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD,
                        ctypes.POINTER(wintypes.HANDLE))(h, 0x8, ctypes.byref(tok)):
                return True if ctypes.get_last_error() == 5 else None
            try:
                elev, ret = wintypes.DWORD(), wintypes.DWORD()
                ok = _sig(a.GetTokenInformation, wintypes.BOOL, wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))(
                    tok, 20, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(ret))  # TokenElevation
                return bool(elev.value) if ok else None
            finally:
                close(tok)
        finally:
            close(h)
    except Exception:
        return None


def file_version_info(path):
    """{'ProductName','FileDescription','ProductVersion','FileVersion'} from an exe's version resource."""
    try:
        import struct
        from ctypes import wintypes
        v = _dll("version")
        size = _sig(v.GetFileVersionInfoSizeW, wintypes.DWORD, wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))(
            path, None)
        if not size:
            return {}
        buf = ctypes.create_string_buffer(size)
        if not _sig(v.GetFileVersionInfoW, wintypes.BOOL, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                    ctypes.c_void_p)(path, 0, size, buf):
            return {}
        query = _sig(v.VerQueryValueW, wintypes.BOOL, ctypes.c_void_p, wintypes.LPCWSTR,
                     ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT))
        lp, ln = ctypes.c_void_p(), wintypes.UINT()
        if not query(buf, "\\VarFileInfo\\Translation", ctypes.byref(lp), ctypes.byref(ln)) or ln.value < 4:
            return {}
        lang, cp = struct.unpack("<HH", ctypes.string_at(lp.value, 4))
        out = {}
        for key in ("ProductName", "FileDescription", "ProductVersion", "FileVersion"):
            if query(buf, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{key}", ctypes.byref(lp), ctypes.byref(ln)) and ln.value:
                out[key] = ctypes.wstring_at(lp.value, ln.value).rstrip("\x00").strip()
        return out
    except Exception:
        return {}


_app_cache = {}


def app_info(pid):
    """{'app': 'chrome.exe', 'name': 'Google Chrome', 'version': '124.0.1', 'elevated': bool|None} (cached)."""
    if not pid:
        return {"app": "", "name": "", "version": "", "elevated": None}
    if pid in _app_cache:
        return _app_cache[pid]
    path = process_path(pid)
    ver = file_version_info(path) if path else {}
    info = {
        "app": Path(path).name if path else "",
        "name": ver.get("ProductName") or ver.get("FileDescription") or "",
        "version": ver.get("ProductVersion") or ver.get("FileVersion") or "",
        "elevated": process_elevated(pid),
    }
    _app_cache[pid] = info
    return info


# ---------------------------------------------------------------------------
# capture geometry
# ---------------------------------------------------------------------------
def capture_box(opts, mons, x, y):
    """Screen rectangle captured for a click at (x, y) under `opts`; None if the click is out of
    scope. `mons` is the mss monitor list (index 0 = whole desktop). Shared with the toolbar overlays."""
    o = opts
    cur = next((m for m in mons[1:] if _contains(m, x, y)), mons[1])
    if o.mode == "all":
        box = dict(mons[0])
    elif o.mode == "monitor":
        box = dict(mons[o.monitor if 1 <= o.monitor < len(mons) else 1])
        if not _contains(box, x, y):
            return None
    elif o.mode == "region" and o.region:
        box = _box(*o.region)
        if not _contains(box, x, y):
            return None
    elif o.mode == "window":
        box = _intersect(window_rect(x, y) or cur, mons[0]) or dict(cur)
    else:
        box = dict(cur)
    if o.exclude_taskbar and o.mode != "all":
        info = work_area_at(x, y)
        if info:
            cropped = _intersect(box, _box(*info[0]))
            # A click on the taskbar itself keeps the full frame so the marker stays visible.
            if cropped and _contains(cropped, x, y):
                box = cropped
    return box


# ---------------------------------------------------------------------------
# global hotkeys without a keyboard hook (RegisterHotKey on its own message-loop thread)
# ---------------------------------------------------------------------------
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


class HotkeyListener:
    """Registers system-wide hotkeys with RegisterHotKey.  `bindings` = {'ctrl+shift+f8': callable}.
    `failed` lists specs that could not be registered (already taken, or not on Windows)."""

    def __init__(self, bindings):
        self.bindings = dict(bindings)
        self.failed = list(self.bindings)
        self.registered = []
        self._ids = {}
        self._tid = 0
        self._ready = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        return not self.failed

    def _run(self):
        try:
            from ctypes import wintypes
            u, k = _dll("user32"), _dll("kernel32")
            self._tid = k.GetCurrentThreadId()
            failed = []
            reg = _sig(u.RegisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
            for i, (spec, fn) in enumerate(self.bindings.items(), 1):
                try:
                    mods, vk = parse_hotkey(spec)
                    if reg(None, i, mods | 0x4000, vk):  # MOD_NOREPEAT
                        self._ids[i] = fn
                        self.registered.append(spec)
                        continue
                except ValueError:
                    pass
                failed.append(spec)
            self.failed = failed
            self._ready.set()
            if not self._ids:
                return
            msg = wintypes.MSG()
            get = _sig(u.GetMessageW, ctypes.c_int, ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                       wintypes.UINT)
            while get(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    fn = self._ids.get(msg.wParam)
                    if fn:
                        try:
                            fn()
                        except Exception:
                            pass
            for i in self._ids:
                u.UnregisterHotKey(None, i)
        except Exception:
            pass
        finally:
            self._ready.set()

    def stop(self):
        try:
            if self._tid:
                _dll("user32").PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass


# ---------------------------------------------------------------------------
# fonts
# ---------------------------------------------------------------------------
_fonts = {}


FONT_FILES = {  # name shown to the user -> (regular candidates, bold candidates); the first one that exists is used
    "Sans": (("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"), ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")),
    "Serif": (("times.ttf", "georgia.ttf", "DejaVuSerif.ttf"), ("timesbd.ttf", "georgiab.ttf", "DejaVuSerif-Bold.ttf")),
    "Console": (("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"), ("consolab.ttf", "courbd.ttf", "DejaVuSansMono-Bold.ttf")),
    "Handwriting": (("segoepr.ttf", "comic.ttf", "DejaVuSans.ttf"), ("segoeprb.ttf", "comicbd.ttf", "DejaVuSans-Bold.ttf")),
}
FONT_ALIASES = {"Segoe UI": "Sans", "Arial": "Sans", "Calibri": "Sans", "Verdana": "Sans",
                "Times New Roman": "Serif", "Consolas": "Console"}  # names used by the first version of the mark-up tools
TK_FONTS = {"Sans": "Segoe UI", "Serif": "Times New Roman", "Console": "Consolas", "Handwriting": "Segoe Print"}


def font_family(name):
    name = FONT_ALIASES.get(name, name)
    return name if name in FONT_FILES else "Sans"


def get_font(size, bold=False, family=None):
    size = int(max(8, size))
    family = font_family(family) if family else None
    key = (size, bold, family)
    if key in _fonts:
        return _fonts[key]
    names = list(FONT_FILES[family][1 if bold else 0]) if family else []
    names += ["arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"]
    font = None
    for n in names:
        try:
            font = ImageFont.truetype(n, size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size)
        except TypeError:
            font = ImageFont.load_default()
    _fonts[key] = font
    return font


# ---------------------------------------------------------------------------
# masks
# ---------------------------------------------------------------------------
MASK_STYLES = {
    "solid": "Solid black",
    "soft": "Soft gray + label",
    "match": "Match background",
    "pixelate": "Pixelated",
    "pixelate_fine": "Pixelated (fine)",
    "blur": "Blurred",
    "blur_heavy": "Blurred (heavy)",
    "dim": "Faded (de-emphasize only - still readable!)",
}
HIDING_STYLES = [k for k in MASK_STYLES if k != "dim"]
LEGACY_STYLES = {"hatch": "soft", "frosted": "blur"}  # removed styles: old settings and sessions still open


def canon_style(key):
    """Current style key for any (possibly retired) one; unknown values fail closed to solid."""
    key = LEGACY_STYLES.get(key, key)
    return key if key in MASK_STYLES else "solid"


@dataclass
class Mask:
    """One thing to hide in every screenshot: a fixed screen rectangle, or any window whose title
    contains `title` (the mask then follows the window as it moves)."""
    rect: tuple = None  # (l, t, r, b) screen pixels
    title: str = ""
    style: str = "solid"
    label: str = ""
    frac: tuple = None  # with `title`: only this part of the window, as fractions (l, t, r, b) of its size

    def to_dict(self):
        return {"rect": list(self.rect) if self.rect else None, "title": self.title,
                "style": self.style, "label": self.label, "frac": list(self.frac) if self.frac else None}

    @classmethod
    def from_dict(cls, d):
        r, f = d.get("rect"), d.get("frac")
        return cls(tuple(r) if r else None, d.get("title", ""), canon_style(d.get("style", "solid")), d.get("label", ""),
                   tuple(f) if f and len(f) == 4 else None)

    def describe(self):
        st = MASK_STYLES.get(self.style, self.style).split(" (")[0]
        if self.frac and self.title:
            l, t, r, b = self.frac
            return f"Part of window \"{self.title}\" ({round(l * 100)}-{round(r * 100)}% across, {round(t * 100)}-{round(b * 100)}% down)  -  {st}"
        if self.rect:
            l, t, r, b = self.rect
            return f"Area {r - l}x{b - t} at {l},{t}  -  {st}"
        return f"Window titled \"{self.title}\"  -  {st}"


def norm_masks(items):
    """Accept Mask objects, dicts, or bare (l, t, r, b) tuples (old API)."""
    out = []
    for m in items or []:
        if isinstance(m, Mask):
            out.append(m)
        elif isinstance(m, dict):
            out.append(Mask.from_dict(m))
        else:
            out.append(Mask(rect=tuple(m)))
    return out


def apply_mask(img, rect, style="solid", label=""):
    """Paint `style` over rect=(l,t,r,b) in image pixels (in place)."""
    l, t = max(0, int(rect[0])), max(0, int(rect[1]))
    r, b = min(img.width, int(rect[2])), min(img.height, int(rect[3]))
    w, h = r - l, b - t
    if w < 1 or h < 1:
        return
    d = ImageDraw.Draw(img)
    style = canon_style(style)
    if style == "soft":
        base = (226, 229, 234)
        img.paste(Image.new("RGB", (w, h), base), (l, t))
        d.rectangle([l, t, r - 1, b - 1], outline=(165, 171, 182))
        if label and w >= 48 and h >= 16:
            font = get_font(min(h * 0.45, 22), bold=True)
            tw = d.textlength(label, font=font)
            if tw < w - 6:
                d.text((l + w / 2, t + h / 2), label, fill=(95, 102, 115), font=font, anchor="mm")
    elif style in ("pixelate", "pixelate_fine"):
        region = img.crop((l, t, r, b))
        block = max(10, int(min(w, h) / 4)) if style == "pixelate" else max(7, int(min(w, h) / 6))
        small = region.resize((max(1, w // block), max(1, h // block)), Image.BILINEAR)
        img.paste(small.resize((w, h), Image.NEAREST), (l, t))
    elif style in ("blur", "blur_heavy"):
        short = min(w, h)
        sigma = min(60, max(9, short * 0.35)) if style == "blur" else min(60, max(16, short * 0.7))
        pad = int(sigma * 3)  # blur with the surroundings too, so the edges look natural (they are not secret)
        L, T = max(0, l - pad), max(0, t - pad)
        R, B = min(img.width, r + pad), min(img.height, b + pad)
        blurred = img.crop((L, T, R, B)).filter(ImageFilter.GaussianBlur(sigma))
        patch = blurred.crop((l - L, t - T, l - L + w, t - T + h))
        img.paste(Image.blend(patch, Image.new("RGB", (w, h), (128, 128, 128)), 0.08), (l, t))
    elif style == "match":
        meds = []
        m = 3
        for box in ((l, max(0, t - m), r, t), (l, b, r, min(img.height, b + m)),
                    (max(0, l - m), t, l, b), (r, t, min(img.width, r + m), b)):
            if box[2] - box[0] >= 1 and box[3] - box[1] >= 1:
                meds.append(ImageStat.Stat(img.crop(box)).median[:3])
        if meds:
            col = tuple(int(sorted(c[i] for c in meds)[len(meds) // 2]) for i in range(3))
        else:
            col = (226, 229, 234)
        d.rectangle([l, t, r - 1, b - 1], fill=col)
    elif style == "dim":
        region = img.crop((l, t, r, b))
        img.paste(Image.blend(region, Image.new("RGB", (w, h), (255, 255, 255)), 0.80), (l, t))
        if label and w >= 48 and h >= 16:
            font = get_font(min(h * 0.4, 18), bold=True)
            d.text((l + w / 2, t + h / 2), label, fill=(120, 126, 138), font=font, anchor="mm")
    else:  # "solid" and anything unknown: always fails closed
        d.rectangle([l, t, r - 1, b - 1], fill=(0, 0, 0))


def apply_masks(img, box, masks, window_finder=find_windows):
    """Paint every mask that overlaps the captured `box` (screen pixels) onto `img`.
    Window masks are looked up at call time so they follow the window."""
    for m in masks:
        rects = [m.rect] if m.rect else window_finder(m.title)
        if m.frac and not m.rect:  # a part of the window, measured as fractions so it survives resizing
            fl, ft, fr, fb = m.frac
            rects = [(w[0] + (w[2] - w[0]) * fl, w[1] + (w[3] - w[1]) * ft, w[0] + (w[2] - w[0]) * fr,
                      w[1] + (w[3] - w[1]) * fb) for w in rects]
        for r in rects:
            c = _intersect(_box(*[int(round(v)) for v in r]), box)
            if c:
                l, t = c["left"] - box["left"], c["top"] - box["top"]
                label = m.label or ("Hidden" if canon_style(m.style) == "soft" else "")
                apply_mask(img, (l, t, l + c["width"], t + c["height"]), m.style, label)


# ---------------------------------------------------------------------------
# optional OCR redaction (IP / MAC / keys / e-mail) - needs pytesseract + the Tesseract program
# ---------------------------------------------------------------------------
OCR_PATTERNS = {
    "ip": re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?::\d{1,5})?$"),
    "mac": re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"),
    "key": re.compile(r"^(?:[A-Za-z0-9+/=_-]{28,}|[0-9A-Fa-f]{24,}|(?:[A-Z0-9]{4,6}-){3,}[A-Z0-9]{4,6})$"),
    "email": re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$"),
    "card": re.compile(r"^(?:\d{4}[- ]?){3}\d{1,4}$|^\d{13,19}$"),
    "ssn": re.compile(r"^\d{3}-\d{2}-\d{4}$"),
}
OCR_LABELS = {"ip": "IP addresses", "mac": "MAC addresses", "key": "Keys / long tokens", "email": "E-mail addresses",
              "card": "Card-like numbers", "ssn": "ID numbers (123-45-6789)"}
COMMON_SECRETS = ("ip", "mac", "key", "email", "card", "ssn")  # the "Hide common secrets" preset


class OcrUnavailable(RuntimeError):
    pass


_OCR_OK = None  # cached: asking Tesseract for its version starts a program and can take seconds on some PCs


def ocr_status():
    """True / False once ocr_available() has run, None before (never blocks)."""
    return _OCR_OK


def ocr_available(refresh=False):
    global _OCR_OK
    if _OCR_OK is not None and not refresh:
        return _OCR_OK
    try:
        import pytesseract
        _tesseract_path(pytesseract)
        pytesseract.get_tesseract_version()
        _OCR_OK = True
    except Exception:
        _OCR_OK = False
    return _OCR_OK


def _tesseract_path(pytesseract):
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if Path(p).exists():
            pytesseract.pytesseract.tesseract_cmd = p
            return


def ocr_words(img, min_conf=20, psm=None):
    """[(text, l, t, r, b)] for every recognised word with at least `min_conf` confidence."""
    try:
        import pytesseract
        _tesseract_path(pytesseract)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT,
                                         config=f"--psm {psm}" if psm else "")
    except Exception as e:  # missing module or missing tesseract.exe
        raise OcrUnavailable(str(e)) from e
    words = []
    for i, txt in enumerate(data["text"]):
        txt = (txt or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = 0
        if txt and conf >= min_conf:
            l, t, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            words.append((txt, l, t, l + w, t + h))
    return words


def _same_picture(a, b, max_changed=40, delta=16):
    """True if two grayscale pictures of the same size differ in at most `max_changed` pixels
    (a blinking caret, not a new line of text)."""
    if a.size != b.size:
        return False
    from PIL import ImageChops
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > delta else 0)
    return diff.histogram()[255] <= max_changed


def ocr_words_tiled(img, tile=1700, overlap=60, workers=None, cache=None):
    """ocr_words for a very wide picture (several monitors): side-by-side strips read in parallel.
    Tesseract is single-threaded per picture, so this is close to N times faster on N strips.

    `cache` (a dict you keep between calls) lets a strip that looks the same as it did last time reuse
    its words: with three monitors, usually only one of them changes between two clicks.  A strip is only
    reused when it is practically identical, so new text on screen is always read."""
    if img.width <= tile * 1.3:
        boxes = [(0, 0, img.width, img.height)]
    else:
        n = -(-img.width // tile)
        step = -(-img.width // n)
        boxes = [(max(0, i * step - overlap), 0, min(img.width, (i + 1) * step + overlap), img.height)
                 for i in range(n)]
    import os
    from concurrent.futures import ThreadPoolExecutor
    gray = {}
    parts = {}
    todo = []
    for b in boxes:
        if cache is not None:
            gray[b] = img.crop(b).convert("L")
            hit = cache.get(b)
            if hit and _same_picture(hit[0], gray[b]):
                parts[b] = hit[1]
                continue
        todo.append(b)
    if todo:
        workers = workers or max(1, min(len(todo), os.cpu_count() or 1, 4))
        old = os.environ.get("OMP_THREAD_LIMIT")
        if len(todo) > 1:
            os.environ["OMP_THREAD_LIMIT"] = "1"  # one thread per strip, or the strips fight over the cores
        try:
            with ThreadPoolExecutor(workers) as ex:
                for b, words in zip(todo, ex.map(lambda bb: ocr_words(img.crop(bb)), todo)):
                    parts[b] = words
                    if cache is not None:
                        cache[b] = (gray[b], words)
        finally:
            if len(todo) > 1:
                if old is None:
                    os.environ.pop("OMP_THREAD_LIMIT", None)
                else:
                    os.environ["OMP_THREAD_LIMIT"] = old
    out, seen = [], set()
    for b in boxes:
        for txt, l, t, r, bt in parts[b]:
            key = (txt, round((l + b[0]) / 8), round(t / 8))  # the overlap reads some words twice
            if key not in seen:
                seen.add(key)
                out.append((txt, l + b[0], t, r + b[0], bt))
    return out


def plausible_label(text):
    """False for OCR fragments like 'ey ne mart' : needs a real-looking word (3+ letters, with a vowel)
    and mostly letters/digits."""
    if not text:
        return False
    alnum = sum(ch.isalnum() for ch in text)
    if alnum < 0.75 * len(text.replace(" ", "")):
        return False
    toks = [t.strip(".,;:()[]\"'") for t in text.split()]
    short_ok = {"as", "of", "in", "on", "to", "or", "at", "by", "up", "go", "is", "it", "no", "ok", "id", "my", "we",
                "us", "if", "an", "be", "do", "so", "ip"}
    good = [w for w in toks if w.lower() in short_ok or len(w) >= 3 and w.isalpha() and any(v in w.lower() for v in "aeiouy") or w.isdigit() and len(w) >= 2]
    return bool(toks) and len(good) / len(toks) >= 0.6


def pick_label(words, px, py, max_dist=90, max_words=4):
    """The text a person would call 'the thing I clicked' - from OCR words [(text, l, t, r, b)] and a click point.

    Takes the word nearest to the click (it must be within `max_dist` pixels), plus neighbours on the same line
    that are separated only by a normal word space.  Returns '' when nothing readable is close by.
    """
    cand = []
    for txt, l, t, r, b in words:
        txt = txt.strip(".,;:()[]{}<>\"'|")
        if sum(ch.isalnum() for ch in txt) < 2:
            continue
        dx = max(l - px, 0, px - r)
        dy = max(t - py, 0, py - b)
        cand.append(((dx * dx + dy * dy) ** 0.5, txt, l, t, r, b))
    if not cand:
        return ""
    best = min(cand, key=lambda c: c[0])
    if best[0] > max_dist:
        return ""
    h0 = max(best[5] - best[3], 1)
    cy0 = (best[3] + best[5]) / 2
    line = sorted((c for c in cand if abs((c[3] + c[5]) / 2 - cy0) <= 0.6 * h0), key=lambda c: c[2])
    i = next(k for k, c in enumerate(line) if c is best)
    lo = hi = i
    while hi + 1 < len(line) and hi - lo + 1 < max_words and line[hi + 1][2] - line[hi][4] <= 0.6 * h0:
        hi += 1
    while lo > 0 and hi - lo + 1 < max_words and line[lo][2] - line[lo - 1][4] <= 0.6 * h0:
        lo -= 1
    return clean_text(" ".join(c[1] for c in line[lo:hi + 1]))[:40]


def ocr_label_near(img, x, y, half_w=220, half_h=60, max_dist=90):
    """Readable text close to (x, y) in `img`, e.g. the caption of a control that exposes no name.
    Raises OcrUnavailable when Tesseract is missing.  Only reads a small crop, so it is quick."""
    l, t = max(0, int(x - half_w)), max(0, int(y - half_h))
    r, b = min(img.width, int(x + half_w)), min(img.height, int(y + half_h))
    if r - l < 8 or b - t < 8:
        return ""
    from PIL import ImageOps, ImageStat
    crop = img.crop((l, t, r, b)).convert("L")
    if ImageStat.Stat(crop).mean[0] < 120:
        crop = ImageOps.invert(crop)  # Tesseract reads dark-mode light-on-dark text badly
    crop = ImageOps.autocontrast(crop)
    k = 3
    crop = crop.resize((crop.width * k, crop.height * k), Image.LANCZOS)
    words = [(w, wl / k + l, wt / k + t, wr / k + l, wb / k + t)
             for w, wl, wt, wr, wb in ocr_words(crop, min_conf=60, psm=11)]
    label = pick_label(words, x, y, max_dist=max_dist)
    return label if plausible_label(label) else ""


def ocr_match_rects(words, kinds):
    """Rects of words that look like any of `kinds` ('ip', 'mac', 'key', 'email')."""
    pats = [OCR_PATTERNS[k] for k in kinds if k in OCR_PATTERNS]
    rects = []
    for txt, l, t, r, b in words:
        core = txt.strip(".,;:()[]{}<>\"'")
        if core and any(p.match(core) for p in pats):
            rects.append((l, t, r, b))
    return rects


def ocr_redact(img, kinds, style="solid", words=None, cache=None):
    """Mask sensitive-looking words in `img` (in place). Returns the number of words masked."""
    words = words if words is not None else ocr_words_tiled(img, cache=cache)
    rects = ocr_match_rects(words, kinds)
    for l, t, r, b in rects:
        apply_mask(img, (l - 3, t - 2, r + 3, b + 2), style, "")
    return len(rects)


# ---------------------------------------------------------------------------
# annotation (drawn at export time from the unannotated raw image, so re-numbering stays correct)
# ---------------------------------------------------------------------------
RED = (255, 0, 0)


def _arrow(d, p0, p1, s, color=RED, width=None):
    width = width or max(3, int(4 * s))
    d.line([p0, p1], fill=color, width=width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    L = 20 * s
    for da in (math.radians(155), -math.radians(155)):
        d.line([p1, (p1[0] + L * math.cos(ang + da), p1[1] + L * math.sin(ang + da))], fill=color, width=width)


FOCUS_MODES = {"off": "Off - show the whole screen",
               "window": "Blur all but the clicked window",
               "control": "Blur all but the clicked control"}


def focus_rect(marker, size, mode):
    """Area (l, t, r, b) to keep sharp for a step, in image pixels, or None when there is nothing sensible to keep."""
    w, h = size
    marker = marker or {}
    s = max(0.8, w / 1400)
    pt = marker.get("pt")
    if mode == "window":
        r = marker.get("win")
        if not r or len(r) != 4:
            return None
        keep = (r[0] - 2 * s, r[1] - 2 * s, r[2] + 2 * s, r[3] + 2 * s)
    elif mode == "control":
        r = marker.get("rect")
        if r and len(r) == 4 and (r[2] - r[0]) * (r[3] - r[1]) < 0.35 * w * h:
            pad = 28 * s  # a little context around the control
            keep = (r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad)
        elif pt:  # unnamed control, or one as big as the window: a patch around the click
            half = 150 * s
            keep = (pt[0] - half, pt[1] - half * 0.7, pt[0] + half, pt[1] + half * 0.7)
        else:
            return None
    else:
        return None
    l, t, rr, b = max(0, int(keep[0])), max(0, int(keep[1])), min(w, int(keep[2])), min(h, int(keep[3]))
    return (l, t, rr, b) if rr - l >= 8 and b - t >= 8 else None


def focus_blur(img, marker, mode):
    """Blur (and slightly dim) everything except the clicked window / control.  Returns img unchanged when it
    does not apply (mode off, no window recorded for old sessions, or the kept area is nearly the whole picture)."""
    if mode not in ("window", "control"):
        return img
    keep = focus_rect(marker, img.size, mode)
    if not keep:
        return img
    l, t, r, b = keep
    if (r - l) * (b - t) >= 0.85 * img.width * img.height:
        return img
    from PIL import ImageEnhance
    out = img.filter(ImageFilter.GaussianBlur(max(6, img.width / 90)))
    out = ImageEnhance.Brightness(out).enhance(0.82)
    out.paste(img.crop(keep), (l, t))
    ImageDraw.Draw(out).rectangle([l, t, r - 1, b - 1], outline=(255, 255, 255), width=max(1, int(img.width / 900)))
    return out


def annotate(img, marker, n=None):
    """Draw the step marker + number badge on `img` (in place) and return it.
    marker = {'shape': click|dbl|drag|scroll|none, 'pt': [x, y], 'rect': [l,t,r,b]|None,
              'to': [x, y]|None, 'dir': 'up'|'down'} in image pixels."""
    d = ImageDraw.Draw(img)
    s = max(0.8, img.width / 1400)
    marker = marker or {}
    shape = marker.get("shape", "none")
    pt = marker.get("pt")
    if pt is None or shape == "none":
        if n is not None:
            _badge(d, img, 22 * s, 22 * s, n, s)
        return img
    cx, cy = pt
    rect = marker.get("rect")
    if rect and shape in ("click", "dbl"):
        l, t, r, b = rect
        if r > l and b > t and not ((r - l) > 0.8 * img.width and (b - t) > 0.8 * img.height):
            d.rectangle([l, t, r, b], outline=RED, width=max(2, int(3 * s)))
    rad = 20 * s
    if shape == "drag" and marker.get("to"):
        tx, ty = marker["to"]
        d.ellipse([cx - 9 * s, cy - 9 * s, cx + 9 * s, cy + 9 * s], outline=RED, width=max(3, int(4 * s)))
        ang = math.atan2(ty - cy, tx - cx)
        _arrow(d, (cx + 9 * s * math.cos(ang), cy + 9 * s * math.sin(ang)), (tx, ty), s)
        d.ellipse([tx - 6 * s, ty - 6 * s, tx + 6 * s, ty + 6 * s], fill=RED)
        rad = 14 * s
    elif shape == "scroll":
        up = marker.get("dir") == "up"
        y0, y1 = (cy + 36 * s, cy - 36 * s) if up else (cy - 36 * s, cy + 36 * s)
        _arrow(d, (cx, y0), (cx, y1), s)
        d.ellipse([cx - 7 * s, cy - 7 * s, cx + 7 * s, cy + 7 * s], outline=RED, width=max(2, int(3 * s)))
        rad = 22 * s
    else:
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=RED, width=max(3, int(4 * s)))
        if shape == "dbl":
            r2 = rad * 1.45
            d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=RED, width=max(2, int(3 * s)))
            rad = r2
    if n is not None:
        _badge(d, img, cx + rad, cy - rad, n, s)
    return img


def _badge(d, img, bx, by, n, s):
    br = 14 * s
    bx = min(max(br, bx), img.width - br)
    by = min(max(br, by), img.height - br)
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=RED)
    d.text((bx, by), str(n), fill="white", font=get_font(18 * s, bold=True), anchor="mm")


# ---------------------------------------------------------------------------
# your own mark-up (boxes, arrows, text, numbered call-outs), stored per step and drawn after the click marker
# ---------------------------------------------------------------------------
MARK_COLOR = (21, 101, 192)
MARK_TOOLS = ("box", "arrow", "text", "num")
MARK_COLORS = [("Blue", "#1565c0"), ("Red", "#e53935"), ("Orange", "#fb8c00"), ("Green", "#2e9e4f"),
               ("Black", "#212121"), ("White", "#ffffff")]
MARK_FONTS = list(FONT_FILES)  # Sans, Serif, Console, Handwriting
MARK_SIZES = {"S": 0.7, "M": 1.0, "L": 1.5, "XL": 2.2}


def _mark_rgb(m):
    h = str(m.get("c", "")).lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else MARK_COLOR
    except ValueError:
        return MARK_COLOR


def _mark_alpha(m):
    try:
        return max(0.1, min(1.0, float(m.get("a", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def _mark_unit(m, width):
    try:
        z = max(0.3, min(4.0, float(m.get("z", 1.0))))
    except (TypeError, ValueError):
        z = 1.0
    return max(0.8, width / 1400) * z


def _wrap(d, txt, font, width):
    out = []
    for para in txt.split("\n"):
        line = ""
        for word in para.split(" "):
            t = (line + " " + word).strip()
            if line and d.textlength(t, font=font) > width:
                out.append(line)
                line = word
            else:
                line = t
        out.append(line)
    return "\n".join(out)


def _text_geometry(d, m, width):
    """(wrapped text, font, pad, (l, t, r, b)) of a text mark, before it is clamped into the picture."""
    s = _mark_unit(m, width)
    font = get_font(20 * s, bool(m.get("b", True)), m.get("f"))
    txt = str(m.get("text", "")).strip()
    p = [float(v) for v in m.get("p", [0, 0])]
    pad = 6 * s
    if len(p) == 4 and abs(p[2] - p[0]) > 30:
        txt = _wrap(d, txt, font, abs(p[2] - p[0]) - 2 * pad)
    x, y = min(p[0], p[2]) if len(p) == 4 else p[0], min(p[1], p[3]) if len(p) == 4 else p[1]
    bb = d.multiline_textbbox((0, 0), txt, font=font)
    w, h = bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad
    if len(p) == 4 and abs(p[2] - p[0]) > 30:
        w = max(w, abs(p[2] - p[0]))  # a text box dragged out keeps its full width (so it can be resized)
    x = min(max(0, x), max(0, width - w))
    return txt, font, pad, (x, max(0, y), x + w, max(0, y) + h), bb


def mark_bounds(m, size):
    """Extent (l, t, r, b) of a mark in image pixels (used for hit-testing and the selection frame), or None."""
    try:
        t, p = m.get("t"), [float(v) for v in m.get("p", [])]
        s = _mark_unit(m, size[0])
        if t in ("box", "arrow") and len(p) == 4:
            pad = max(3, 4 * s) if t == "box" else 12 * s
            return (min(p[0], p[2]) - pad, min(p[1], p[3]) - pad, max(p[0], p[2]) + pad, max(p[1], p[3]) + pad)
        if t == "num" and len(p) >= 2:
            r = 16 * s
            return (p[0] - r, p[1] - r, p[0] + r, p[1] + r)
        if t == "text" and len(p) >= 2 and str(m.get("text", "")).strip():
            d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
            return _text_geometry(d, m, size[0])[3]
    except (TypeError, ValueError, AttributeError):
        pass
    return None


def _draw_one(d, img_w, m):
    t, p = m.get("t"), [float(v) for v in m.get("p", [])]
    col, s = _mark_rgb(m), _mark_unit(m, img_w)
    if t == "box" and len(p) == 4:
        d.rectangle([min(p[0], p[2]), min(p[1], p[3]), max(p[0], p[2]), max(p[1], p[3])], outline=col,
                    width=max(2, int(4 * s)))
    elif t == "arrow" and len(p) == 4:
        _arrow(d, (p[0], p[1]), (p[2], p[3]), s, col, max(3, int(5 * s)))
    elif t == "text" and len(p) >= 2 and str(m.get("text", "")).strip():
        txt, font, pad, (l, tp, r, b), bb = _text_geometry(d, m, img_w)
        ox, oy = l + pad - bb[0], tp + pad - bb[1]
        if m.get("bg", "box") == "box":
            d.rounded_rectangle([l, tp, r, b], radius=6 * s, fill=(255, 255, 255), outline=col, width=max(2, int(3 * s)))
            d.multiline_text((ox, oy), txt, fill=col if sum(col) < 600 else (30, 30, 30), font=font)
        else:  # plain text with a halo so it stays readable on any picture
            halo = (255, 255, 255) if sum(col) < 450 else (20, 20, 20)
            d.multiline_text((ox, oy), txt, fill=col, font=font, stroke_width=max(2, int(2.5 * s)), stroke_fill=halo)
    elif t == "num" and len(p) >= 2:
        br = 16 * s
        d.ellipse([p[0] - br, p[1] - br, p[0] + br, p[1] + br], fill=col, outline="white" if sum(col) < 650 else (30, 30, 30),
                  width=max(2, int(2 * s)))
        d.text((p[0], p[1]), str(m.get("n", "")), fill="white" if sum(col) < 450 else (20, 20, 20),
               font=get_font(20 * s, True, m.get("f")), anchor="mm")


def draw_marks(img, marks):
    """Draw hand-made annotations on `img` (in place).  Each mark: {'t': box|arrow|text|num, 'p': [x0, y0, x1, y1] in
    image pixels, 'text', 'n', and optional 'c' colour, 'a' opacity 0.1-1, 'z' size factor, 'f' font, 'b' bold,
    'bg' 'box'|'plain'}.  Unknown or malformed entries are skipped."""
    if not marks:
        return img
    for m in marks:
        try:
            a = _mark_alpha(m)
            if a >= 0.99:
                _draw_one(ImageDraw.Draw(img), img.width, m)
            else:  # draw on a transparent layer, fade it, then lay it over the picture
                layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                _draw_one(ImageDraw.Draw(layer), img.width, m)
                layer.putalpha(layer.getchannel("A").point(lambda v, a=a: int(v * a)))
                img.paste(layer, (0, 0), layer)
        except (TypeError, ValueError, AttributeError):
            continue
    return img


# ---------------------------------------------------------------------------
# single instance
# ---------------------------------------------------------------------------
_instance_handle = None  # kept for the life of the process: the mutex goes away when we exit


def single_instance(name):
    """True if this is the only running copy (it now owns the named mutex), False if another copy already runs.
    Always True off Windows or if the check itself fails: never block someone from starting the program."""
    global _instance_handle
    try:
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        h = k.CreateMutexW(None, False, f"Local\\{name}")
        if not h:
            return True
        _instance_handle = h
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def tell_already_running(title, window_title=None):
    """Bring the running copy's window forward if it can be found, and say so in a plain message box."""
    try:
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.FindWindowW.restype = wintypes.HWND
        u.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        hwnd = u.FindWindowW(None, window_title or title)
        if hwnd:
            u.ShowWindow(wintypes.HWND(hwnd), 9)  # SW_RESTORE
            u.SetForegroundWindow(wintypes.HWND(hwnd))
        u.MessageBoxW(None, f"{title} is already running.\n\nLook for its toolbar on screen (or its tray icon). "
                      "Close that copy first if you want to start a new one.", title, 0x40 | 0x40000)  # info + topmost
    except Exception:
        pass


def simplify_path(points, eps=3.0, limit=80):
    """Thin a mouse path.  points = [(ms, x, y)]; keeps the corners and turns (Ramer-Douglas-Peucker on x, y), so a long
    wobbly path becomes a few dozen points.  The first and last point always stay."""
    if len(points) <= 2:
        return [tuple(p) for p in points]

    def dist(p, a, b):
        (_, px, py), (_, ax, ay), (_, bx, by) = p, a, b
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5

    while True:
        keep = {0, len(points) - 1}
        stack = [(0, len(points) - 1)]
        while stack:
            lo, hi = stack.pop()
            far, idx = 0.0, None
            for i in range(lo + 1, hi):
                d = dist(points[i], points[lo], points[hi])
                if d > far:
                    far, idx = d, i
            if idx is not None and far > eps:
                keep.add(idx)
                stack += [(lo, idx), (idx, hi)]
        if len(keep) <= limit:
            return [tuple(points[i]) for i in sorted(keep)]
        eps *= 1.5
