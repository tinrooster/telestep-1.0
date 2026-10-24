import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, queue
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep_recorder as sr
R=sr.Recorder.__new__(sr.Recorder); R.q=queue.Queue(); R.events=queue.Queue()
def fill(n):
    while R.q.qsize()<n: R.q.put(1)
    while R.q.qsize()>n: R.q.get()
def evs():
    out=[]
    while not R.events.empty(): out.append(R.events.get()[1])
    return out
fill(10); assert R._backlog_ok() and evs()==[]
fill(25); assert R._backlog_ok() and evs()==["warn"]
fill(30); assert R._backlog_ok() and evs()==[], "warn only once"
fill(60); assert not R._backlog_ok() and R.holding and evs()==["hold"]
fill(40); assert not R._backlog_ok() and evs()==[], "stays held until drained"
fill(16); assert not R._backlog_ok()
fill(15); assert R._backlog_ok() and not R.holding and evs()==["resumed"]
fill(5); assert R._backlog_ok(); fill(25); assert R._backlog_ok() and evs()==["warn"], "warns again after draining"
print("backlog ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
