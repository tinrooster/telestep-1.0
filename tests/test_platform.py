import os, sys, ast
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Every backend must offer the same API: telestep_platform re-exports these names whatever the OS.
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1
    else: bad += 1; print("FAIL:", name, extra)

root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "telestep_platform")
init = ast.parse(open(os.path.join(root, "__init__.py"), encoding="utf-8").read())
api = {t.id for n in init.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Attribute)
       and getattr(n.value.value, "id", "") == "backend" for t in n.targets}
check("api found", len(api) > 20, sorted(api))

def names(fname):  # top-level defs, classes, assignments and imports of a backend, read without importing it
    tree = ast.parse(open(os.path.join(root, fname), encoding="utf-8").read())
    out = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)): out.add(n.name)
        elif isinstance(n, ast.Assign): out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.ImportFrom): out |= {a.asname or a.name for a in n.names}
    return out

for b in ("_windows.py", "_macos.py", "_generic.py"):
    missing = api - names(b)
    check(f"{b} has the whole API", not missing, sorted(missing))

audio_api = {"NAME", "DEFAULT_NAME", "UNAVAILABLE", "NEEDS", "available", "list_devices", "record", "can_play",
             "play", "stop_playing"}
for b in ("_audio_winmm.py", "_audio_sd.py"):
    missing = audio_api - names(b)
    check(f"{b} has the whole audio API", not missing, sorted(missing))

import telestep_platform as plat, telestep_core as core
check("backend chosen", plat.NAME in ("windows", "macos", "generic"), plat.NAME)
check("core re-exports", core.window_info is plat.window_info and core.HotkeyListener is plat.HotkeyListener)
check("one shared overlay list", core.SKIP_TITLES is plat.SKIP_TITLES)
check("parse_hotkey", core.parse_hotkey("ctrl+shift+f8") == (0x6, 0x77))
if plat.NAME == "generic":
    check("no window off Windows", plat.window_info(1, 1)["hwnd"] == 0 and plat.list_windows() == [])
    check("app info empty", core.app_info(1234) == {"app": "", "name": "", "version": "", "elevated": None})
    hk = plat.HotkeyListener({"ctrl+f8": lambda: None})
    check("hotkeys report failure", hk.start() is False and hk.failed == ["ctrl+f8"])
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
