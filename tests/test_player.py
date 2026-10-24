import os
import sys, os, re, wave, struct, math, tempfile, subprocess
from pathlib import Path
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"): sys.modules[m]=MagicMock()
sys.path.insert(0,"/home/claude/telestep_work/Telestep")
import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())   # make_session helper
import telestep_report as rep, telestep_player as pl
ok=bad=0
def check(n,c,x=""):
    global ok,bad
    if c: ok+=1
    else: bad+=1; print("FAIL",n,x)
s=make_session(4,big=False)
(s.dir/"audio").mkdir(exist_ok=True)
with wave.open(str(s.dir/"audio"/"a.wav"),"wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(11025); w.writeframes(b"".join(struct.pack("<h",int(5000*math.sin(i/5))) for i in range(int(11025*1.0))))
s.steps[0].audio="audio/a.wav"
tpl=rep.Template()
p=rep.export(s,tpl,["player","html"])
check("player written", Path(p["player"]).name=="walkthrough.html" and Path(p["player"]).exists(), p)
t=Path(p["player"]).read_text(encoding="utf-8")
check("audio + images embedded", "data:audio/wav;base64," in t and "data:image/jpeg;base64," in t)
check("start overlay", 'id="start"' in t)
js=re.findall(r"<script>(.*?)</script>",t,re.S)[0]
Path("/tmp/pl.js").write_text(js)
r=subprocess.run(["node","--check","/tmp/pl.js"],capture_output=True,text=True); check("JS syntax ok", r.returncode==0, r.stderr[:300])
print("size KB", Path(p["player"]).stat().st_size//1024)
open("/tmp/pl_path.txt","w").write(p["player"])
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
