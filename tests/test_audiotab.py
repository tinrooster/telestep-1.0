import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk, os
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep, telestep_audio as ta
from PIL import ImageGrab
ok=bad=0
def check(n,c,x=""):
    global ok,bad
    if c: ok+=1
    else: bad+=1; print("FAIL",n,x)
root=tk.Tk(); app=telestep.App(root); root.update()
app.var_cfg.set(True); app.toggle_config(); app.nb.select(app.tab_audio); root.update()
check("audio tab exists", str(app.tab_audio) in app.nb.tabs())
check("mic defaults off", app.var_narrate.get() is False)
check("device default", app.var_audio_dev.get()==ta.DEFAULT_NAME and ta.preferred=="")
check("no-windows message", "Windows" in app.var_atest.get() and app.btn_atest.instate(["disabled"]), app.var_atest.get())
check("settings keys", app.record_opts().narrate is False)
d=dict(app.data); 
check("saved device blank for default", telestep.cfg.DEFAULTS["audio_device"]=="" and "audio_device" not in telestep.cfg.PRESET_KEYS)
# capture tab no longer has mic checkbox
check("capture rec_checks has 6 incl. mouse path", len(app.rec_checks)==6)
# fake a mic dev list
ta.list_devices=lambda:[(0,"USB Mic"),(1,"Headset")]; app._audio_refresh(); check("devices listed", list(app.cmb_audio["values"])==[ta.DEFAULT_NAME,"USB Mic","Headset"])
app.var_audio_dev.set("USB Mic"); app._audio_device_changed(); check("preferred set", ta.preferred=="USB Mic")
check("persisted", app.data.get("audio_device","x") is not None)
root.update(); x,y=root.winfo_rootx(),root.winfo_rooty()
ImageGrab.grab(bbox=(x,y,x+root.winfo_width(),y+root.winfo_height()),xdisplay=os.environ["DISPLAY"]).save("/tmp/audiotab.png")
# mic indicator on compact badge
app.var_cfg.set(False); app.toggle_config(); root.update()
class R: 
    mic_on=False; paused=False
app.state="rec"; app._mic_key=None; app._show_mic(False); root.update()
check("c_mic shown while recording", app.c_mic.winfo_manager()=="grid")
im=app.icons["mic_on"][0]; app._show_mic(True); check("icon swaps to pulse frame", app.c_mic.image in app.mic_frames)
app.state="idle"; app._show_mic(False); check("hidden when idle", app.c_mic.winfo_manager()=="")
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
