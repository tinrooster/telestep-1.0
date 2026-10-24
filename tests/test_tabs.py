import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk, time, os, tempfile
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep
from PIL import ImageGrab
d=tempfile.mkdtemp()
root=tk.Tk(); root.geometry("+20+20")
app=telestep.App(root, settings_path=os.path.join(d,"s.json"))
app.var_cfg.set(True); app.toggle_config(); root.update(); time.sleep(.3); root.update()
names=[t[1].cget("text") for t in app._tabs]; print(names)
for i,(tab,lbl,bar) in enumerate(app._tabs):
    app.nb.select(tab); root.update()
    on=[l.cget("text") for _,l,b in app._tabs if b.cget("bg")==app.TAB_ACCENT]
    assert on==[names[i]], (on,names[i])
# click on a tab label switches
tab,lbl,bar=app._tabs[1]
lbl.event_generate("<Button-1>"); root.update()
assert app.nb.select()==str(app.tab_capture), app.nb.select()
# privacy tab: OCR probe is async
app.nb.select(app.tab_privacy); root.update()
assert app.var_ocr_note.get().startswith("Checking")
t0=time.time()
while time.time()-t0<3 and app.var_ocr_note.get().startswith("Checking"):
    root.update(); time.sleep(.05)
print("ocr note:", app.var_ocr_note.get())
app.nb.select(app.tab_capture); root.update(); time.sleep(.3); root.update()
x,y=root.winfo_rootx(),root.winfo_rooty()
ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).crop((x-5,y-5,x+root.winfo_width()+5,y+root.winfo_height()+5)).save(sys.argv[1])
# watchdog: simulate a UI freeze > 3 s and check the log
time.sleep(0.1)
t0=time.time()
root.update()
time.sleep(4.0)   # blocks the UI thread
root.update(); time.sleep(.3); root.update()
app._dbg.flush()
txt=open(app._dbg_path).read()
print("log has stack:", "most recent call first" in txt, "| gap line:", "unresponsive" in txt)
app.on_close(force=True)
print("log removed when non-empty? still exists:", os.path.exists(app._dbg_path))
# clean exit leaves no empty log
d2=tempfile.mkdtemp(); root2=tk.Tk(); app2=telestep.App(root2, settings_path=os.path.join(d2,"s.json")); root2.update()
p=app2._dbg_path; app2.on_close(force=True); print("empty log deleted:", not os.path.exists(p))
if 'ok' in globals(): sys.exit(1 if bad else 0)
