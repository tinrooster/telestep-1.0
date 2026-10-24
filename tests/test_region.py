import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk, os, tempfile
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep, telestep_core as core
root=tk.Tk(); root.geometry("+20+20"); app=telestep.App(root, settings_path=os.path.join(tempfile.mkdtemp(),"s.json"))
app.var_cfg.set(True); app.toggle_config()
app.screens=[{"left":0,"top":0,"width":1920,"height":1080},{"left":0,"top":0,"width":1920,"height":1080}]
app.nb.select(app.tab_capture); root.update()
core.window_rect=lambda x,y:{"left":300,"top":300,"width":400,"height":300}
app.region=(500,400,900,700)
for cursor,over in (((100,100),True),((1000,500),False),((600,500),False)):
    core.cursor_pos=lambda c=cursor:c; app.over_toolbar=lambda p,o=over:o
    for mode in ("Custom area","Window under click"):
        app.var_mode.set(mode); app.on_mode_change(); root.update()
        try:
            app.overlays.update("preview"); b=app.overlays.last_box
            vis=[o._visible for o in app.overlays.bars]
            print(mode, cursor, "over" if over else "off", "box", b and (b["left"],b["top"],b["width"],b["height"]), "bars visible", vis)
        except Exception as e:
            import traceback; traceback.print_exc()
if 'ok' in globals(): sys.exit(1 if bad else 0)
