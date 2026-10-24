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
d=Path(tempfile.mkdtemp()); root=tk.Tk(); app=telestep.App(root,str(d/"s.json")); root.update()
st=lambda w: str(w.cget("state")) if hasattr(w,"cget") else ""
dis=lambda w: "disabled" in w.state()
app.var_ocr["email"].set(True); app.var_ocr["key"].set(True)
o=app.record_opts(); assert set(o.ocr_kinds)=={"email","key"} and o.ocr_labels
app.chk_ocr_on.invoke(); root.update()   # switch off
assert app.var_ocr_on.get()==False
o=app.record_opts(); assert o.ocr_kinds==[] and not o.ocr_labels
assert app.var_ocr["email"].get() and app.var_ocr["key"].get(), "ticks kept"
assert all(dis(c) for c in app.ocr_checks) and dis(app.chk_ocr_labels)
assert "OCR" not in app.var_summary.get() and "OCR" not in app.var_scope.get()
app.chk_ocr_on.invoke(); root.update()   # back on
assert not any(dis(c) for c in app.ocr_checks) and not dis(app.chk_ocr_labels)
assert set(app.record_opts().ocr_kinds)=={"email","key"} and "OCR" in app.var_summary.get()
app.set_state("rec"); assert all(dis(c) for c in app.ocr_checks) and dis(app.chk_ocr_on)
app.set_state("idle"); assert not any(dis(c) for c in app.ocr_checks)
# persistence
app.chk_ocr_on.invoke(); root.update()
data=app.gather(); assert data["ocr_enabled"] is False and data["ocr"]["email"] is True
import telestep_settings as cfg
print([n for n in dir(app) if "save" in n.lower() or "collect" in n.lower()][:8])
print("octog ok")
app.apply({**data,"ocr_enabled":True}); root.update(); assert app.var_ocr_on.get() and not dis(app.ocr_checks[0])
app.apply({**data,"ocr_enabled":False}); root.update(); assert not app.var_ocr_on.get() and dis(app.ocr_checks[0])
print("roundtrip ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
