import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep, telestep_widgets as w
root=tk.Tk()
app=telestep.App(root) if hasattr(telestep,"App") else None
root.update()
assert app.hk_entries and all(isinstance(e,w.HotkeyEntry) for e in app.hk_entries)
e=app.hk_entries[0]; e._start()
class Ev: keysym="F6"; state=0x4
e._key(Ev)
print(app.var_hk["pause"].get() if "pause" in app.var_hk else None)
print(app.record_opts().hotkeys if hasattr(app.record_opts(),"hotkeys") else "opts ok")
# duplicate refused
e2=app.hk_entries[1]; e2._start(); e2._key(Ev); print("dup note:", e2.display.get())
print("app ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
