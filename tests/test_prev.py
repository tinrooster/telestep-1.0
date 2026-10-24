import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk, time, os, tempfile
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep
root=tk.Tk(); app=telestep.App(root, settings_path=os.path.join(tempfile.mkdtemp(),"s.json"))
shown=[]; app.overlays.update=lambda st: shown.append(st); app.overlays.hide=lambda: shown.append("hide")
app.var_cfg.set(True); app.toggle_config(); root.update()
def run(): shown.clear(); app.update_overlays(); return shown[-1]
root.focus_force(); root.update()
app.nb.select(app.tab_capture); root.update(); print("capture+focus:", run(), app._setting_up())
app.nb.select(app.tab_general); root.update(); assert run()=="hide"
app.nb.select(app.tab_capture); app.var_preview.set(False); assert run()=="hide"; app.var_preview.set(True)
app.var_cfg.set(False); app.toggle_config(); root.update(); assert run()=="hide"
app.var_cfg.set(True); app.toggle_config(); root.update()
# lose focus: focus_displayof None when another app is active
import telestep_core as _c; _c.own_process_active=lambda: False; assert run()=="hide"; _c.own_process_active=lambda: True; assert run()!="hide"; _c.own_process_active=lambda: None; app.root.focus_displayof=lambda: None; assert run()=="hide"; print("unfocused hides: ok")
print("ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
