import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"): sys.modules[m]=MagicMock()
class Item:
    def __init__(s,text,action=None,default=False,visible=True,enabled=True): s.text,s.action,s.visible,s.enabled=text,action,visible,enabled
class Menu:
    SEPARATOR="--"
    def __init__(s,*items): s.items=items
class Icon:
    def __init__(s,*a): s.menu=a[3]; s.icon=a[1]
    def run_detached(s): pass
    def stop(s): pass
ps=MagicMock(); ps.MenuItem=Item; ps.Menu=Menu; ps.Icon=Icon
sys.modules["pystray"]=ps
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep, telestep_widgets as w
root=tk.Tk(); app=telestep.App(root); root.update()
app.tray.ok=True; app.tray.icon=None; app.tray.start()
def show(state):
    app.state=state; out=[]
    for i in app.tray.icon.menu.items:
        if i=="--": out.append("--"); continue
        v=i.visible(i) if callable(i.visible) else i.visible
        if not v: continue
        t=i.text(i) if callable(i.text) else i.text
        out.append(t+("" if i.enabled else " [header]"))
    return out
for s in ("idle","rec","paused"): print(s, show(s))
assert "Start recording" in show("idle") and "Start recording" not in show("rec")
assert "Resume" in show("paused") and "Pause" in show("rec")
# hotkey boxes locked correctly
app.set_state("rec"); root.update(); assert app.hk_entries[0].instate(["disabled"])
app.set_state("idle"); root.update(); assert str(app.hk_entries[0].cget("state"))=="readonly"
# shot origin
from telestep_recorder import Recorder
import telestep_recorder as R
R.cursor_pos=lambda:(5,5)
cap={}
r=Recorder.__new__(Recorder); import queue; r.q=queue.Queue(); r.paused=False; r.stop_evt=MagicMock(); r.stop_evt.is_set.return_value=False
r._last_pos=(900,400); r.ignore_rects=[]; r.cap=MagicMock(); r._sct=MagicMock(side_effect=lambda:(cap.setdefault("used",True) and (_ for _ in ()).throw(RuntimeError())))
import telestep_recorder
orig=telestep_recorder.in_rects
seen=[]
telestep_recorder.in_rects=lambda x,y,rects: seen.append((x,y)) or False
r.manual_shot(from_menu=True); r.manual_shot()
print(seen)
assert seen==[(900,400),(5,5)]
print("ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
