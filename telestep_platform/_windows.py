"""Windows backend: Win32 through ctypes (window/process info, monitors, hotkeys, single instance, shell)."""
import ctypes
import os
import subprocess
import threading
from pathlib import Path

from .common import EMPTY_INFO, SKIP_TITLES, box, parse_hotkey

NAME = "windows"


def set_dpi_aware():
    """Must happen before any coordinates are read, or clicks land offset on scaled displays."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def quiet_subprocesses():
    """Telestep is a window-only program, but the helper programs it starts (Tesseract for OCR, ipconfig in Support
    mode) are console programs: each one can flash a black window, and OCR starts several per click.  Ask Windows not
    to create a console for any child process we start."""
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not flag or getattr(subprocess.Popen, "_telestep_quiet", False):
        return
    real = subprocess.Popen

    class QuietPopen(real):
        _telestep_quiet = True

        def __init__(self, *a, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | flag
            super().__init__(*a, **kw)

    subprocess.Popen = QuietPopen


# ---------------------------------------------------------------------------
# windows, processes, monitors
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
        return dict(EMPTY_INFO)


def foreground_info():
    try:
        from ctypes import wintypes
        hwnd = _sig(_dll("user32").GetForegroundWindow, wintypes.HWND)()
        return _info_of(hwnd) if hwnd else dict(EMPTY_INFO)
    except Exception:
        return dict(EMPTY_INFO)


def own_process_active():
    """True/False: is the foreground window one of this program's (toolbar, dialogs, drop-downs)?  None if unknown.
    More reliable than Tk's focus, which reads 'none' right after a dialog or drop-down closes."""
    try:
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


def frame_rect(hwnd):
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
        rects = [frame_rect(ga(hwnd0, flag)) for flag in (2, 3)]  # GA_ROOT, GA_ROOTOWNER
        l = min(r[0] for r in rects)
        t = min(r[1] for r in rects)
        r_ = max(r[2] for r in rects)
        b = max(r[3] for r in rects)
        return box(l, t, r_, b) if r_ > l and b > t else None
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
                l, t, r, b = frame_rect(hwnd)
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


def app_details(pid):
    """{'app': 'chrome.exe', 'name': 'Google Chrome', 'version': '124.0.1', 'elevated': bool|None}."""
    path = process_path(pid)
    ver = file_version_info(path) if path else {}
    return {
        "app": Path(path).name if path else "",
        "name": ver.get("ProductName") or ver.get("FileDescription") or "",
        "version": ver.get("ProductVersion") or ver.get("FileVersion") or "",
        "elevated": process_elevated(pid),
    }


# ---------------------------------------------------------------------------
# global hotkeys without a keyboard hook (RegisterHotKey on its own message-loop thread)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# shell: open files and folders, beep
# ---------------------------------------------------------------------------
def open_path(path):
    """Open a file, folder or ms-settings: URI with its default program.  Raises if that fails."""
    os.startfile(str(path))


def reveal_file(path):
    """Show a file selected in File Explorer."""
    subprocess.Popen(["explorer", f"/select,{path}"])


def beep(freq=1400, ms=25):
    """Short click sound, played on a helper thread so it never delays the caller."""
    import winsound
    threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()


# ---------------------------------------------------------------------------
# our own Tk windows
# ---------------------------------------------------------------------------
def _hwnd(widget):
    return ctypes.windll.user32.GetAncestor(widget.winfo_id(), 2)  # GA_ROOT


def exclude_from_capture(widget, on=True):
    """Keep the window out of screenshots (it stays visible on screen)."""
    try:
        ctypes.windll.user32.SetWindowDisplayAffinity(_hwnd(widget), 0x11 if on else 0)  # WDA_EXCLUDEFROMCAPTURE
    except Exception:
        pass


def make_click_through(widget):
    """Clicks pass through the window to whatever is underneath, and it never takes focus."""
    try:
        user32 = ctypes.windll.user32
        hwnd = _hwnd(widget)
        ex = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        # LAYERED | TRANSPARENT (click-through) | TOOLWINDOW | NOACTIVATE
        user32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x08000000)
    except Exception:
        pass


def widget_screen_rect(widget):
    """Screen rectangle (l, t, r, b) of a Tk window including its title bar, or None."""
    try:
        from ctypes import wintypes
        rc = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(_hwnd(widget), ctypes.byref(rc))
        return (rc.left, rc.top, rc.right, rc.bottom)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# machine details (environment.txt, Support mode)
# ---------------------------------------------------------------------------
def os_details():
    """Extra lines for the machine summary: {'Windows': 'Windows 11 Pro 23H2 (build 22631.3447)', 'Memory': '16.0 GB'}."""
    env = {}
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")

        def q(name):
            try:
                return str(winreg.QueryValueEx(k, name)[0])
            except OSError:
                return ""

        name, disp, build, ubr = q("ProductName"), q("DisplayVersion") or q("ReleaseId"), q("CurrentBuild"), q("UBR")
        if build and int(build) >= 22000:
            name = name.replace("Windows 10", "Windows 11")
        env["Windows"] = f"{name} {disp} (build {build}.{ubr})".strip()
    except Exception:
        pass
    try:
        class MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = MEM()
        m.dwLength = ctypes.sizeof(MEM)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            env["Memory"] = f"{m.ullTotalPhys / 2**30:.1f} GB"
    except Exception:
        pass
    return env


def user_identity():
    """(display name, e-mail-style sign-in name) of the signed-in user when Windows knows them, else ('', '')."""
    name = upn = ""
    try:
        for fmt in (3, 8):  # NameDisplay, NameUserPrincipal
            buf = ctypes.create_unicode_buffer(256)
            size = ctypes.c_ulong(256)
            val = buf.value if ctypes.windll.secur32.GetUserNameExW(fmt, buf, ctypes.byref(size)) else ""
            if fmt == 3:
                name = val
            else:
                upn = val
    except Exception:
        pass
    return name, upn


def desktop_dir():
    """The real Desktop folder (follows OneDrive redirection), or None."""
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return None


def network_info():
    """`ipconfig /all` as text ('' if unavailable)."""
    try:
        r = subprocess.run(["ipconfig", "/all"], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n").strip()
    except Exception:
        return ""
