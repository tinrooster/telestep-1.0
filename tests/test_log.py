import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tempfile, tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep
d=Path(tempfile.mkdtemp()); root=tk.Tk()
app=telestep.App(root, str(d/"settings.json")); root.update()
app.var_title.set("log test")
app.start(); root.update()
class S:
    steps=[1]; title="log test"
    def count(s): return 3
app.rec=None; app._finish_stop(S()) if False else None
app._dlog(f"----- Recording \"x\" saved -----")
txt=(d/"telestep_debug.log").read_text(encoding="utf-8")
print(txt[:900])
assert "===== Telestep" in txt and "----- Recording \"log test\" started" in txt and "capture:" in txt
print("log ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
