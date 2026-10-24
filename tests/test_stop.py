import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, time, tkinter as tk, queue
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep
root=tk.Tk(); app=telestep.App(root); root.update()
app.var_review.set(False)
class S:
    steps=[]; 
    def count(self): return 0
class Rec:
    paused=False
    def __init__(s): s.q=queue.Queue(); [s.q.put(i) for i in range(5)]
    def pending(s): return s.q.qsize()
    def stop(s):
        while not s.q.empty(): s.q.get(); time.sleep(0.5)
        return S()
app.rec=Rec(); app.state="recording"
t0=time.time(); app.stop(); blocked=time.time()-t0
print("stop() returned in %.2fs"%blocked); assert blocked<0.5
ticks=0; seen=set()
while app._saving and time.time()-t0<10:
    root.update(); ticks+=1; seen.add(app.var_status.get()); time.sleep(0.05)
print("ticks",ticks,sorted(seen)[:3]); assert ticks>10
assert any("left" in x for x in seen)
assert app.last_session is not None and app.idle_msg=="No steps recorded", app.idle_msg
app.start() if False else None
# start refused while saving
app._saving=object(); app.start(); assert app.rec is None; app._saving=None
print("stop ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
