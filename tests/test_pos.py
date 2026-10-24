import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk, time, os
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep
from PIL import ImageGrab
ok=bad=0
def check(n,c,x=""):
    global ok,bad
    if c: ok+=1
    else: bad+=1; print("FAIL",n,x)
root=tk.Tk(); root.geometry("+50+50"); app=telestep.App(root); root.update()
app.var_compact.set(True); app._sync_mode(); root.update()
check("idle: record button shown", app.cbtn_rec.winfo_manager()=="pack")
check("idle: no rec/mic indicators", app.c_rec.winfo_manager()=="" and app.c_mic.winfo_manager()=="")
app.set_state("rec"); app.state="rec"; app._mic_key=None; app._show_mic(True); root.update()
check("rec: record button hidden", app.cbtn_rec.winfo_manager()=="")
check("rec: logo, rec, mic visible", app.c_icon.winfo_ismapped() and app.c_rec.winfo_ismapped() and app.c_mic.winfo_ismapped())
x0=app.c_mic.winfo_x(); xr=app.c_rec.winfo_x()
def shot(n):
    root.update(); time.sleep(.2); root.update()
    x,y=root.winfo_rootx(),root.winfo_rooty(); ImageGrab.grab(bbox=(x-3,y-3,x+root.winfo_width()+3,y+root.winfo_height()+3),xdisplay=os.environ["DISPLAY"]).save(n)
shot("/tmp/c1.png")
app._expand_compact(True); root.update(); shot("/tmp/c2.png")
check("expanding keeps rec + mic in place", app.c_mic.winfo_x()==x0 and app.c_rec.winfo_x()==xr, (x0,app.c_mic.winfo_x()))
frames=set()
for _ in range(20):
    app._pulse_mic(); frames.add(app._pulse_i); time.sleep(.06)
check("mic pulses through several frames", len(frames)>=4, frames)
app._show_mic(False); check("muted shows static off icon", app.c_mic.image is app.mic_off_big)
app.set_state("idle"); app.state="idle"; app._compact_refresh(); root.update()
check("back to idle: record button returns", app.cbtn_rec.winfo_manager()=="pack")
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
