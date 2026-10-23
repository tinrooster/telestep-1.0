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


def get_font(size, bold=False):
    size = int(max(8, size))
    key = (size, bold)
    if key in _fonts:
        return _fonts[key]
    names = (("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf") if bold
             else ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"))
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
    "hatch": "Hatched gray",
    "pixelate": "Pixelated",
    "frosted": "Frosted glass",
    "match": "Match background",
    "dim": "Faded (de-emphasize only - still readable!)",
}
HIDING_STYLES = [k for k in MASK_STYLES if k != "dim"]


@dataclass
class Mask:
    """One thing to hide in every screenshot: a fixed screen rectangle, or any window whose title
    contains `title` (the mask then follows the window as it moves)."""
    rect: tuple = None  # (l, t, r, b) screen pixels
    title: str = ""
    style: str = "solid"
    label: str = ""

    def to_dict(self):
        return {"rect": list(self.rect) if self.rect else None, "title": self.title,
                "style": self.style, "label": self.label}

    @classmethod
    def from_dict(cls, d):
        r = d.get("rect")
        return cls(tuple(r) if r else None, d.get("title", ""), d.get("style", "solid"), d.get("label", ""))

    def describe(self):
        st = MASK_STYLES.get(self.style, self.style).split(" (")[0]
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
    if style == "soft" or style == "hatch":
        base, line = (226, 229, 234), (190, 196, 206)
        tile = Image.new("RGB", (w, h), base)
        if style == "hatch":
            td = ImageDraw.Draw(tile)
            step = max(8, min(w, h) // 10)
            for k in range(-h, w, step):
                td.line([(k, h), (k + h, 0)], fill=line, width=max(1, step // 6))
        img.paste(tile, (l, t))
        d.rectangle([l, t, r - 1, b - 1], outline=(165, 171, 182))
        if label and w >= 48 and h >= 16:
            font = get_font(min(h * 0.45, 22), bold=True)
            tw = d.textlength(label, font=font)
            if tw < w - 6:
                if style == "hatch":  # keep the label legible over the stripes
                    pad = 4
                    d.rectangle([l + (w - tw) / 2 - pad, t + h / 2 - font.size * 0.7,
                                 l + (w + tw) / 2 + pad, t + h / 2 + font.size * 0.7], fill=base)
                d.text((l + w / 2, t + h / 2), label, fill=(95, 102, 115), font=font, anchor="mm")
    elif style == "pixelate":
        region = img.crop((l, t, r, b))
        block = max(10, int(min(w, h) / 4))
        small = region.resize((max(1, w // block), max(1, h // block)), Image.BILINEAR)
        img.paste(small.resize((w, h), Image.NEAREST), (l, t))
    elif style == "frosted":
        region = img.crop((l, t, r, b))
        block = max(6, int(min(w, h) / 8))
        region = region.resize((max(1, w // block), max(1, h // block)), Image.BILINEAR).resize((w, h), Image.NEAREST)
        region = region.filter(ImageFilter.GaussianBlur(max(8, min(w, h) / 6)))
        img.paste(Image.blend(region, Image.new("RGB", (w, h), (255, 255, 255)), 0.38), (l, t))
        d.rectangle([l, t, r - 1, b - 1], outline=(235, 238, 242))
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
        for r in rects:
            c = _intersect(_box(*r), box)
            if c:
                l, t = c["left"] - box["left"], c["top"] - box["top"]
                label = m.label or ("Hidden" if m.style in ("soft", "hatch") else "")
                apply_mask(img, (l, t, l + c["width"], t + c["height"]), m.style, label)


# ---------------------------------------------------------------------------
# optional OCR redaction (IP / MAC / keys / e-mail) - needs pytesseract + the Tesseract program
# ---------------------------------------------------------------------------
OCR_PATTERNS = {
    "ip": re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?::\d{1,5})?$"),
    "mac": re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"),
    "key": re.compile(r"^(?:[A-Za-z0-9+/=_-]{28,}|[0-9A-Fa-f]{24,}|(?:[A-Z0-9]{4,6}-){3,}[A-Z0-9]{4,6})$"),
    "email": re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$"),
}
OCR_LABELS = {"ip": "IP addresses", "mac": "MAC addresses", "key": "Keys / long tokens", "email": "E-mail addresses"}


class OcrUnavailable(RuntimeError):
    pass


def ocr_available():
    try:
        import pytesseract
        _tesseract_path(pytesseract)
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _tesseract_path(pytesseract):
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if Path(p).exists():
            pytesseract.pytesseract.tesseract_cmd = p
            return


def ocr_words(img):
    """[(text, l, t, r, b)] for every recognised word."""
    try:
        import pytesseract
        _tesseract_path(pytesseract)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception as e:  # missing module or missing tesseract.exe
        raise OcrUnavailable(str(e)) from e
    words = []
    for i, txt in enumerate(data["text"]):
        txt = (txt or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = 0
        if txt and conf >= 20:
            l, t, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            words.append((txt, l, t, l + w, t + h))
    return words


def ocr_match_rects(words, kinds):
    """Rects of words that look like any of `kinds` ('ip', 'mac', 'key', 'email')."""
    pats = [OCR_PATTERNS[k] for k in kinds if k in OCR_PATTERNS]
    rects = []
    for txt, l, t, r, b in words:
        core = txt.strip(".,;:()[]{}<>\"'")
        if core and any(p.match(core) for p in pats):
            rects.append((l, t, r, b))
    return rects


def ocr_redact(img, kinds, style="solid", words=None):
    """Mask sensitive-looking words in `img` (in place). Returns the number of words masked."""
    words = words if words is not None else ocr_words(img)
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
