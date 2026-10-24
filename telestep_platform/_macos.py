"""macOS backend.

Shell, machine details and the single-instance lock use only the standard library and the tools every Mac has
(open, afplay, sw_vers, sysctl, defaults).  Window, element and hotkey lookups still come from the generic backend
(no window reported, hotkeys not registered); they move to Quartz / Accessibility through pyobjc next."""
import fcntl
import subprocess
import tempfile
from pathlib import Path

from ._generic import (EMPTY_INFO, HotkeyListener, app_details, cursor_pos, exclude_from_capture,  # noqa: F401
                       foreground_info, frame_rect, is_admin, list_windows, make_click_through, own_process_active,
                       parse_hotkey, quiet_subprocesses, set_dpi_aware, tell_already_running, widget_screen_rect,
                       window_info, window_rect, work_area_at)

NAME = "macos"


def _out(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def double_click_time():
    try:
        return float(_out("defaults", "read", "-g", "com.apple.mouse.doubleClickThreshold")) or 0.5
    except ValueError:
        return 0.5


# --- single instance: an exclusive lock on a file in the temp folder, released when the process exits
_locks = {}


def single_instance(name):
    """True if this is the only running copy, False if another copy holds the lock.  True if the check fails."""
    if name in _locks:
        return True
    try:
        f = open(Path(tempfile.gettempdir()) / f"{name}.lock", "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            return False
        _locks[name] = f
        return True
    except Exception:
        return True


# --- shell
def open_path(path):
    """Open a file, folder or x-apple.systempreferences: URL with its default program.  Raises if that fails."""
    subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal_file(path):
    """Show a file selected in Finder."""
    subprocess.Popen(["open", "-R", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def beep(freq=1400, ms=25):
    try:
        subprocess.Popen(["afplay", "-v", "0.4", "/System/Library/Sounds/Tink.aiff"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# --- machine details
def os_details():
    env = {}
    ver, build = _out("sw_vers", "-productVersion"), _out("sw_vers", "-buildVersion")
    if ver:
        env["macOS"] = f"{ver} (build {build})" if build else ver
    try:
        env["Memory"] = f"{int(_out('sysctl', '-n', 'hw.memsize')) / 2**30:.1f} GB"
    except ValueError:
        pass
    cpu = _out("sysctl", "-n", "machdep.cpu.brand_string")
    if cpu:
        env["Processor"] = cpu
    return env


def user_identity():
    """(full name, '') - macOS has no sign-in e-mail to read without an MDM profile."""
    return _out("id", "-F"), ""


def desktop_dir():
    d = Path.home() / "Desktop"
    return d if d.exists() else None


def network_info():
    """Interfaces and DNS servers as text ('' if unavailable)."""
    parts = [_out("ifconfig"), _out("scutil", "--dns")]
    return "\n\n".join(p for p in parts if p)


