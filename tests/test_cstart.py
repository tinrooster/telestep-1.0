import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tempfile, json, tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep
d=Path(tempfile.mkdtemp()); (d/"s.json").write_text(json.dumps({"compact_toolbar":True,"toolbar_opacity":70}))
root=tk.Tk(); app=telestep.App(root,str(d/"s.json")); root.update()
assert app._compact_on and root.overrideredirect() and app.cframe.winfo_ismapped() and not app.main.winfo_ismapped()
print("starts compact; alpha", round(float(root.attributes("-alpha")),2))
app.on_close(force=True) if False else None
print("cstart ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
