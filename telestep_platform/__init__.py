"""telestep_platform - everything Telestep asks of the operating system, behind one small API.

The rest of the program is plain Python, Tk and Pillow.  Anything that needs the OS (which window is under the
pointer, which program owns it, monitors and work areas, global hotkeys, one-copy-only, opening files, keeping our
own windows out of screenshots, machine details) goes through here.  One backend per system, chosen on import:

  _windows.py   Win32 through ctypes
  _macos.py     macOS
  _generic.py   anything else (Linux): safe "nothing" answers, so the logic still runs and the tests pass

Every call degrades to "nothing" (empty info, None, False) instead of raising, except open_path / reveal_file,
which raise so the caller can say the folder could not be opened.
"""
import sys

from .common import EMPTY_INFO, SKIP_TITLES, parse_hotkey  # noqa: F401

if sys.platform == "win32":
    from . import _windows as backend
elif sys.platform == "darwin":
    from . import _macos as backend
else:
    from . import _generic as backend

NAME = backend.NAME

# process setup
set_dpi_aware = backend.set_dpi_aware
quiet_subprocesses = backend.quiet_subprocesses

# windows, processes, monitors
window_info = backend.window_info              # (x, y) -> {'hwnd', 'title', 'cls', 'pid'}
foreground_info = backend.foreground_info      # () -> same, for the active window
own_process_active = backend.own_process_active  # () -> True / False / None (unknown)
frame_rect = backend.frame_rect                # (hwnd) -> (l, t, r, b)
window_rect = backend.window_rect              # (x, y) -> box dict of the window under the point, or None
list_windows = backend.list_windows            # () -> [{'hwnd', 'title', 'cls', 'pid', 'rect'}], top of z-order first
work_area_at = backend.work_area_at            # (x, y) -> ((work l, t, r, b), (monitor l, t, r, b)) or None
cursor_pos = backend.cursor_pos                # () -> (x, y) or None
double_click_time = backend.double_click_time  # () -> seconds
is_admin = backend.is_admin                    # () -> bool
app_details = backend.app_details              # (pid) -> {'app', 'name', 'version', 'elevated'}

# hotkeys and single instance
HotkeyListener = backend.HotkeyListener        # (bindings).start() / .stop(); .failed, .registered
single_instance = backend.single_instance      # (name) -> True if we are the only copy
tell_already_running = backend.tell_already_running

# shell
open_path = backend.open_path                  # (path or URI): raises on failure
reveal_file = backend.reveal_file              # (path): show it selected in the file manager; raises on failure
beep = backend.beep                            # short non-blocking click sound

# our own Tk windows
exclude_from_capture = backend.exclude_from_capture  # (widget, on=True)
make_click_through = backend.make_click_through      # (widget)
widget_screen_rect = backend.widget_screen_rect      # (widget) -> (l, t, r, b) incl. title bar, or None

# machine details
os_details = backend.os_details                # () -> {label: value} for environment.txt
user_identity = backend.user_identity          # () -> (display name, sign-in e-mail)
desktop_dir = backend.desktop_dir              # () -> Path or None
network_info = backend.network_info            # () -> text
