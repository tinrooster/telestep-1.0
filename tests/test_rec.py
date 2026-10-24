import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep_recorder as sr
R=sr.Recorder.__new__(sr.Recorder)
class C: ProcessId=999; Name="x"; ControlTypeName="ListControl"; BoundingRectangle=MagicMock(left=0,top=0,right=1,bottom=1)
uia=MagicMock(); uia.ControlFromPoint.return_value=C()
from telestep_platform._windows import _UiaInspector  # the Windows backend's adapter over uiautomation
auto=_UiaInspector(uia)
assert R._describe(auto,1,1,pid=123)[0]=="" , "other-process element must be ignored"
assert R._describe(auto,1,1,pid=999)[0]=="x"
assert R._describe(auto,1,1)[0]=="x"
class P: Name="Parent"
class C2: ProcessId=1; Name=""; ControlTypeName="PaneControl"; BoundingRectangle=MagicMock(left=0,top=0,right=4,bottom=3)
C2.GetParentControl=lambda self: P()
uia2=MagicMock(); uia2.ControlFromPoint.return_value=C2()
assert R._describe(_UiaInspector(uia2),1,1)==("Parent","Pane",(0,0,4,3),False,True), "unnamed element takes its parent's name"
geom={"left":0,"top":0,"scale":0.5}
assert R._win_marker(geom,5,5,{"left":10,"top":20,"width":100,"height":50})==[5.0,10.0,55.0,35.0]
print("rec ok")
import queue, time as _t
R.events=queue.Queue()
class Slow:
    def __init__(s): s.n=0
    def __call__(s,x,y): s.n+=1; return C()
uia.ControlFromPoint=Slow()
real=sr.time.monotonic; fake=[0.0]
def mono():
    fake[0]+=3.0; return fake[0]   # every call advances 3 s -> each lookup "takes" 3 s
sr.time.monotonic=mono
R._describe(auto,1,1,pid=7); R._describe(auto,1,1,pid=7)
sr.time.monotonic=real
n=uia.ControlFromPoint.n
assert R._describe(auto,1,1,pid=7)[0]=="" and uia.ControlFromPoint.n==n, "3rd call skips UIA"
assert not R.events.empty()
assert R._describe(auto,1,1,pid=999)[0]=="x"
print("slow ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
