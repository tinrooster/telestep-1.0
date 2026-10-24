import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep
root=tk.Tk(); app=telestep.App(root); root.update()
print(repr(app.var_summary.get()), app.lbl_summary.winfo_ismapped())
assert app.lbl_summary.winfo_ismapped()
app.var_title.set("Printer fix"); root.update()
assert "Printer fix" in app.var_summary.get()
k=next(iter(app.var_ocr)); app.var_ocr[k].set(True); root.update(); assert "OCR" in app.var_summary.get()
app.var_cfg.set(True); app.toggle_config(); root.update(); assert not app.lbl_summary.winfo_ismapped()
app.var_cfg.set(False); app.toggle_config(); root.update(); assert app.lbl_summary.winfo_ismapped()
app.set_state("rec"); root.update(); assert not app.lbl_summary.winfo_ismapped()
app.set_state("idle"); root.update(); assert app.lbl_summary.winfo_ismapped()
print(app.var_summary.get(), root.winfo_width()); print("sum ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
