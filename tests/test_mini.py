import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk, os, tempfile
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep
from PIL import ImageGrab
root=tk.Tk(); root.geometry("+20+20"); app=telestep.App(root, settings_path=os.path.join(tempfile.mkdtemp(),"s.json"))
app.var_cfg.set(True); app.toggle_config(); root.update()
mini=app.tabbar.winfo_children()[-1]; print(mini.cget("text"), mini.winfo_ismapped())
x,y=root.winfo_rootx(),root.winfo_rooty()
ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).crop((x,y,x+root.winfo_width(),y+90)).save(sys.argv[1])
mini.event_generate("<Button-1>"); root.update()
assert not app.var_cfg.get() and not app.cfg.winfo_ismapped(); print("collapsed ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
