import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tempfile, tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep, telestep_core as core
d=Path(tempfile.mkdtemp()); root=tk.Tk(); app=telestep.App(root,str(d/"s.json")); root.update()
al=lambda: round(float(root.attributes("-alpha")),2)
assert al()==1.0
app.scale_opacity.set(55); root.update(); app._adjusting_opacity=False; app._apply_opacity()
print("var",app.var_opacity.get(),"alpha",al()); assert app.var_opacity.get()==55 and al()==0.55
app._hover=True; app._apply_opacity(); assert al()==1.0, "solid on hover"
app.var_solid_hover.set(False); app._apply_opacity(); assert al()==0.55
app.var_solid_hover.set(True); app._adjusting_opacity=True; app._apply_opacity(); assert al()==0.55, "dragging shows the level"
app._adjusting_opacity=False
# poll hover logic via cursor_pos
app._hover=False
core.cursor_pos=lambda:(app.toolbar_rect[0]+3,app.toolbar_rect[1]+3) if app.toolbar_rect else (0,0)
app.toolbar_rect=app.toolbar_rect or (0,0,100,40)
import telestep_widgets as w
w.window_screen_rect=lambda r:(10,10,200,60); core.cursor_pos=lambda:(20,20)
app.poll(); assert app._hover and al()==1.0
core.cursor_pos=lambda:(900,900); app.poll(); assert not app._hover and al()==0.55
# settings open -> solid, collapsed -> see-through
app._hover=False; app.var_cfg.set(True); app.toggle_config(); root.update(); assert al()==1.0, al()
app._adjusting_opacity=True; app._apply_opacity(); assert al()==0.55, "drag previews"
app._adjusting_opacity=False; app._apply_opacity(); assert al()==1.0
app.var_cfg.set(False); app.toggle_config(); root.update(); assert al()==0.55, al()
# persistence
g=app.gather(); assert g["toolbar_opacity"]==55 and g["toolbar_solid_hover"] is True
app.apply({**g,"toolbar_opacity":80}); root.update(); assert app.var_opacity.get()==80 and al()==0.8
app.apply({**g,"toolbar_opacity":5}); assert app.var_opacity.get()==30
print("opacity ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
