"""Fallback backend (Linux and anything else): safe "nothing" answers, so the logic still runs and can be tested.

Window and process lookups report no window, hotkeys don't register, and the single-instance check never blocks.
Opening files uses the desktop's default handler (xdg-open)."""
import os
import subprocess
from pathlib import Path

from .common import EMPTY_INFO, parse_hotkey  # noqa: F401  (parse_hotkey: same API on every backend)

NAME = "generic"
OPENER = "xdg-open"


def set_dpi_aware():
    pass


def quiet_subprocesses():
    pass


# --- windows, processes, monitors
def window_info(x, y):
    return dict(EMPTY_INFO)


def foreground_info():
    return dict(EMPTY_INFO)


def own_process_active():
    return None


def frame_rect(hwnd):
    return (0, 0, 0, 0)


def window_rect(x, y):
    return None


def list_windows():
    return []


def work_area_at(x, y):
    return None


def cursor_pos():
    return None


def double_click_time():
    return 0.5


def is_admin():
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def app_details(pid):
    return {"app": "", "name": "", "version": "", "elevated": None}


# --- hotkeys
class HotkeyListener:
    """No system-wide hotkeys here: every binding is reported as failed, so the toolbar says so."""

    def __init__(self, bindings):
        self.bindings = dict(bindings)
        self.failed = list(self.bindings)
        self.registered = []

    def start(self):
        return not self.failed

    def stop(self):
        pass


# --- single instance
def single_instance(name):
    return True


def tell_already_running(title, window_title=None):
    pass


# --- shell
def open_path(path):
    """Open a file or folder with its default program.  Raises if that fails."""
    subprocess.Popen([OPENER, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal_file(path):
    """Show the folder holding the file (no portable way to pre-select it)."""
    open_path(Path(path).parent)


def beep(freq=1400, ms=25):
    pass


# --- our own Tk windows
def exclude_from_capture(widget, on=True):
    pass


def make_click_through(widget):
    pass


def widget_screen_rect(widget):
    return None


# --- machine details
def os_details():
    return {}


def user_identity():
    return "", ""


def desktop_dir():
    return None


def network_info():
    return ""

