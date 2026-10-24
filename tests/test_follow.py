import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk, os, tempfile
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep, telestep_core as core, telestep_widgets as w
root=tk.Tk(); root.geometry("+20+20"); app=telestep.App(root, settings_path=os.path.join(tempfile.mkdtemp(),"s.json"))
app.screens=[{"left":0,"top":0,"width":3840,"height":1080},{"left":0,"top":0,"width":1920,"height":1080},{"left":1920,"top":0,"width":1920,"height":1080}]
app.var_cfg.set(True); app.toggle_config(); app.screens=[{"left":0,"top":0,"width":3840,"height":1080},{"left":0,"top":0,"width":1920,"height":1080},{"left":1920,"top":0,"width":1920,"height":1080}]; root.focus_force(); root.update()
app.nb.select(app.tab_capture); root.update()
core.cursor_pos=lambda:(100,100); app.over_toolbar=lambda p:True      # cursor parked on the toolbar
core.window_rect=lambda x,y:{"left":300,"top":300,"width":400,"height":300}
boxes=[]
orig=app.overlays.bars[0].show if app.overlays.bars else None
def outline():
    print("  screens",len(app.screens),"mode",app.current_mode(),"state",app.state)
    app.overlays.update("preview"); b=app.overlays.last_box; return (b["left"],b["width"]) if b else None
app.var_mode.set("Window under click"); app.on_mode_change(); print("window mode ->", outline())
app.var_mode.set("Screen 2 (1920x1080 at 1920,0)"); app.choices.setdefault("Screen 2 (1920x1080 at 1920,0)",("monitor",2)); app.on_mode_change()
b=outline(); print("screen 2 ->", b); assert b==(1920,1920), b
app.var_mode.set("All screens"); app.on_mode_change(); b=outline(); print("all ->", b); assert b==(0,3840), b
app.var_mode.set("Window under click"); app.on_mode_change(); b=outline(); print("window again ->", b); assert b[1]==1920 or b[1]==400
app.var_mode.set("Screen under click"); app.on_mode_change(); b=outline(); assert b==(0,1920), b
print("ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
