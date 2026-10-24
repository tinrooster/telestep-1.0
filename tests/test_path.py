import os
import sys, os, re, queue, time, random, subprocess
from pathlib import Path
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"): sys.modules[m]=MagicMock()
sys.path.insert(0,"/home/claude/telestep_work/Telestep")
import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_core as core, telestep_recorder as sr, telestep_report as rep, telestep_model as tm
ok=bad=0
def check(n,c,x=""):
    global ok,bad
    if c: ok+=1
    else: bad+=1; print("FAIL",n,x)
random.seed(2)
line=[(i*50, 100+i*8+random.uniform(-1,1), 200+i*3+random.uniform(-1,1)) for i in range(60)]
sp=core.simplify_path(line)
check("straight line collapses", len(sp)<=6 and sp[0]==line[0] and sp[-1]==line[-1], len(sp))
zig=[(i*50, 100+(i%2)*40, 100+i*10) for i in range(40)]
check("turns are kept", len(core.simplify_path(zig))>=30)
big=[(i*20, random.uniform(0,900), random.uniform(0,900)) for i in range(2000)]
check("limit respected", len(core.simplify_path(big,limit=80))<=80)
check("tiny input", core.simplify_path([(0,1,1)])==[(0,1,1)])
# recorder
R=sr.Recorder.__new__(sr.Recorder); R.o=MagicMock(mouse_path=True); R.paused=False
R.on_move(10,10); time.sleep(.06); R.on_move(20,20); R.on_move(21,21)  # third is throttled
check("throttled sampling", len(R._trail)==2, len(R._trail))
now=time.monotonic(); tr=R._take_trail(now,100,100)
check("trail taken + reset", tr and len(tr)==3 and R._trail is None and tr[-1][1:]==(100,100))
R.o.mouse_path=False; check("off -> nothing", R._take_trail(now,1,1) is None)
R.o.mouse_path=True; R.paused=True; R.on_move(5,5); check("paused ignored", R._trail is None); R.paused=False
R.paused=False
R._map=lambda g,x,y: sr.Recorder._map(R,g,x,y)
geom={"left":0,"top":0,"scale":0.5}
trail=[(0,100,100),(0.5,300,200),(1.0,600,400),(1.5,5000,5000),(2.0,800,500)]
pp=R._path_for(geom,trail,(960,540))
check("mapped to picture px, off-screen dropped", pp and pp[0]==[0,50,50] and all(0<=p[1]<=980 for p in pp), pp)
check("ms from first sample", pp[-1][0]==2000, pp)
check("hardly moved -> None", R._path_for(geom,[(0,10,10),(1,11,11)],(960,540)) is None)
check("single point -> None", R._path_for(geom,[(0,10,10)],(960,540)) is None)
# end to end into player
s=make_session(3,big=False)
s.steps[0].path=[[0,50,60],[400,200,150],[900,480,300]]
s.steps[1].path=[[0,10,10],[800,300,200]]
tpl=rep.Template(); out=rep.export(s,tpl,["player"])
t=Path(out["player"]).read_text(encoding="utf-8")
import json
data=json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>',t,re.S).group(1))
check("path normalised to fractions", data[0]["path"] and all(0<=p[1]<=1 and 0<=p[2]<=1 for p in data[0]["path"]) and data[0]["path"][0][0]==0, data[0]["path"])
check("step without path has none", data[2]["path"]==[])
check("pointer button hidden unless paths", 'id="curb"' in t)
Path("/tmp/pl_path.txt").write_text(out["player"])
js=re.findall(r"<script>(.*?)</script>",t,re.S)[0]; Path("/tmp/pl.js").write_text(js)
r=subprocess.run(["node","--check","/tmp/pl.js"],capture_output=True,text=True); check("JS syntax ok", r.returncode==0, r.stderr[:300])
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
