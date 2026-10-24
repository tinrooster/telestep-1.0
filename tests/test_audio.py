import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, os, tempfile, wave, struct, math, queue, zipfile, datetime as dt
from pathlib import Path
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep_audio as au, telestep_model as tm, telestep_recorder as sr, telestep_report as rep
ok=bad=0
def check(n,c,x=""):
    global ok,bad
    if c: ok+=1
    else: bad+=1; print("FAIL",n,x)
def mkwav(path, segs, rate=11025):
    with wave.open(str(path),"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        for secs,amp in segs:
            w.writeframes(b"".join(struct.pack("<h",int(amp*math.sin(i/5))) for i in range(int(secs*rate))))
d=Path(tempfile.mkdtemp())
# --- cutting
mkwav(d/"m.wav",[(1.5,8000),(1.5,0),(0.5,8000),(2.5,8000)])
r=au.cut_clips(d/"m.wav",[("a",1.5),("b",3.0),("c",3.5)],d/"out")
check("speech kept, silence dropped", set(r)=={"a","c"}, r)
check("clip a ~1.5s", abs(au.duration(d/"out"/"a.wav")-1.5)<0.05)
check("last clip takes the tail", abs(au.duration(d/"out"/"c.wav")-3.0)<0.05, au.duration(d/"out"/"c.wav"))
mkwav(d/"s.wav",[(0.2,8000),(2,8000)])
check("too-short clip dropped", "x" not in au.cut_clips(d/"s.wav",[("x",0.2),("y",2.2)],d/"o2"))
check("bad file is harmless", au.cut_clips(d/"nope.wav",[("a",1)],d/"o3")=={})
# --- clock with pauses
n=au.Narrator(); t0=dt.datetime(2026,1,1,12,0,0); n.start_dt=t0; n.running=True
n.pauses=[(t0+dt.timedelta(seconds=10),t0+dt.timedelta(seconds=20))]
f=lambda s:n.pos_at(t0+dt.timedelta(seconds=s))
check("before pause", f(5)==5); check("during pause", f(15)==10); check("after pause", f(25)==15)
n.pauses.append((t0+dt.timedelta(seconds=30),None)); check("open pause", f(40)==20, f(40))
check("not started", au.Narrator().pos_at(t0)==-1)
check("no mic off-Windows", au.available() is False and au.Narrator().start()[0] is False)
# --- recorder
class Fake:
    def __init__(s,wav): s.wav=wav
    def pos_at(s,w): return (w-T0).total_seconds()
    def stop(s,p):
        Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_bytes(Path(s.wav).read_bytes()); return True
    def pause(s): s.p=1
    def resume(s): s.p=0
T0=dt.datetime(2026,1,1,9,0,0)
R=sr.Recorder.__new__(sr.Recorder)
R._pending_comment=""; R._stages={}; R.q=queue.Queue(); R.events=queue.Queue(); R.session=tm.Session(tempfile.mkdtemp(),"t"); R.session.make_dirs()
R.o=MagicMock(key_mode="count"); R._last_pw=False; R._stage=lambda n: __import__("contextlib").nullcontext(); sr.core.app_info=lambda pid:{}
R.narr=Fake(d/"m.wav")
R._do_type(None,T0+dt.timedelta(seconds=1.5),"abc",3)
R._do_note(None,T0+dt.timedelta(seconds=2),"note","note")
R._do_type(None,T0+dt.timedelta(seconds=3),"abc",3)
R._do_type(None,T0+dt.timedelta(seconds=3.5),"abc",3)
st=R.session.steps
check("apos stored", [round(s.apos,1) for s in st]==[1.5,-1.0,3.0,3.5], [s.apos for s in st])
R._finish_audio()
check("clips attached", [bool(s.audio) for s in st]==[True,False,True,True], [s.audio for s in st])
check("master removed", not (Path(R.session.dir)/"audio"/"_narration.wav").exists())
check("narr cleared", R.narr is None)
# pause follows
R.narr=Fake(d/"m.wav"); R.mic_on=True; R.paused=False; R.events=queue.Queue(); sr.Recorder.toggle_pause(R); check("pause mutes", R.narr.p==1); sr.Recorder.toggle_pause(R); check("resume unmutes", R.narr.p==0)
# --- model
S=R.session; a=st[0]; b=st[3]
check("audio file exists", (S.dir/a.audio).exists())
tw=S.duplicate(a); check("duplicate copies audio", tw.audio!=a.audio and (S.dir/tw.audio).exists())
expect=au.duration(S.dir/a.audio)+au.duration(S.dir/b.audio)
m=S.merge([a,b]); h=m
check("merge joins", h.audio and abs(au.duration(S.dir/h.audio)-expect)<0.1, (au.duration(S.dir/h.audio) if h.audio else None, expect))
check("merged away clip removed", not (S.dir/b.audio).exists() if b.audio!=h.audio else True)
S.delete(tw); check("delete removes audio", not (S.dir/tw.audio).exists())
# --- reports
S.steps=[h]; h.friendly="Click it"
tpl=rep.Template(); 
for fmt in ("md","html","zip"):
    try:
        p=rep.WRITERS[fmt](S,tpl)
    except Exception as e:
        check(fmt+" writes",False,repr(e)); continue
    if fmt=="md": check("md links voice", "[Voice note](audio/" in Path(p).read_text(encoding="utf-8"))
    if fmt=="html": check("html has player", "<audio controls" in Path(p).read_text(encoding="utf-8") and "data:audio/wav;base64," in Path(p).read_text(encoding="utf-8"))
    if fmt=="zip": check("zip has audio", any(n.startswith("audio/") for n in zipfile.ZipFile(p).namelist()), zipfile.ZipFile(p).namelist())
# old sessions load
old=tm.Step.from_dict({"id":"x","kind":"click"}); check("old step defaults", old.audio=="" and old.apos==-1)
print(ok,"passed,",bad,"failed")
# --- mic switch + diagnostics
class FakeN:
    made=[]
    def __init__(s,*a,**k): s.level=0; s.log=[]; s.error=""; FakeN.made.append(s)
    def start(s): return (not FakeN.fail, "no microphone")
    def pause(s): s.log.append("p")
    def resume(s): s.log.append("r")
    def pos_at(s,w): return (w-T0).total_seconds()
    def stop(s,p):
        if FakeN.nofile: s.error="save failed: x"; return False
        Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_bytes(Path(FakeN.wav).read_bytes()); return True
FakeN.fail=False; FakeN.nofile=False; FakeN.wav=d/"m.wav"
au.Narrator=FakeN
def newrec():
    R=sr.Recorder.__new__(sr.Recorder); R._pending_comment=""; R._stages={}; R.q=queue.Queue(); R.events=queue.Queue()
    R.session=tm.Session(tempfile.mkdtemp(),"t"); R.session.make_dirs(); R.o=MagicMock(key_mode="count"); R._last_pw=False
    R._stage=lambda n: __import__("contextlib").nullcontext(); R.paused=False; return R
R=newrec(); check("mic starts off", R.mic_on is False and R.narr is None)
check("switch on opens mic", R.set_mic(True) and R.narr is not None and R.mic_on and R.narr.log[-1]=="r")
check("event sent", ("mic",True) in list(R.events.queue))
R.set_mic(False); check("off mutes", R.narr.log[-1]=="p")
R.set_mic(True); R.paused=True; R._sync_mic(); check("pause overrides mic", R.narr.log[-1]=="p")
R.paused=False; R._sync_mic(); check("unpause restores", R.narr.log[-1]=="r")
FakeN.fail=True; R2=newrec(); check("mic failure reported", R2.set_mic(True) is False and R2.mic_on is False and any(e[0]=="warn" for e in list(R2.events.queue)))
FakeN.fail=False
# steps before the mic was on are skipped; clips only for narrated ones
R3=newrec(); R3._do_type(None,T0+dt.timedelta(seconds=1),"a",1); R3.set_mic(True); R3._do_type(None,T0+dt.timedelta(seconds=2),"b",1); R3._do_type(None,T0+dt.timedelta(seconds=3.5),"c",1)
R3.narr.pos_at=lambda w:(w-T0).total_seconds()
for s_ in R3.session.steps[:1]: check("early step not narrated", s_.apos==-1)
R3._finish_audio(); check("later steps got clips", [bool(s_.audio) for s_ in R3.session.steps]==[False,True,True], [s_.audio for s_ in R3.session.steps])
# failure keeps evidence
FakeN.nofile=True; R4=newrec(); R4.set_mic(True); R4._do_type(None,T0,"a",1); R4._finish_audio()
pt=R4.session.dir/"audio"/"narration_problem.txt"; check("problem file written", pt.exists() and "save failed" in pt.read_text())
FakeN.nofile=False; mkwav(d/"q.wav",[(3,0)]); FakeN.wav=d/"q.wav"
R5=newrec(); R5.set_mic(True); R5._do_type(None,T0+dt.timedelta(seconds=1),"a",1); R5._finish_audio()
a5=R5.session.dir/"audio"; check("silent recording kept for diagnosis", (a5/"narration.wav").exists() and "loud enough" in (a5/"narration_problem.txt").read_text())
print(ok,"passed,",bad,"failed")
# --- smart cutting
import random
random.seed(1)
def synth(path, speech, total, dips=(), rate=11025):
    """speech: [(start,end)] seconds loud; dips: [(a,b)] quiet inside speech."""
    with wave.open(str(path),"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        out=[]
        for i in range(int(total*rate)):
            t=i/rate; v=random.randint(-10,10)
            if any(a<=t<b for a,b in speech) and not any(a<=t<b for a,b in dips): v+=int(7000*math.sin(i/4))
            out.append(struct.pack("<h",v))
        w.writeframes(b"".join(out))
def dur(f): return au.duration(f)
sd=d/"sm"; sd.mkdir()
synth(d/"s1.wav",[(1,3),(5,7),(9,10)],13)
marks=[("c1",2.0),("c2",6.5),("c3",12.0)]
r=au.smart_clips(d/"s1.wav",marks,sd/"n","next")
check("next: each clip present", set(r)=={"c1","c2","c3"}, r)
check("next: gap speech -> next click", abs(dur(sd/"n"/"c3.wav")-(1.0+0.3)) < 0.2, dur(sd/"n"/"c3.wav") if "c3" in r else None)
check("next: overlapping speech stays whole", abs(dur(sd/"n"/"c1.wav")-(2.0+0.3))<0.2, dur(sd/"n"/"c1.wav"))
r=au.smart_clips(d/"s1.wav",marks,sd/"p","prev")
check("prev: gap speech -> previous click", abs(dur(sd/"p"/"c2.wav")-3.85)<0.2 and "c3" not in r, (r, dur(sd/"p"/"c2.wav")))
# long utterance across two clicks, with a breath near the 2nd click
synth(d/"s2.wav",[(0,10)],10,dips=[(4.4,4.8)])
r=au.smart_clips(d/"s2.wav",[("a",1.0),("b",5.0)],sd/"m","next")
da,db=dur(sd/"m"/"a.wav"),dur(sd/"m"/"b.wav")
check("continuous speech split at the breath", set(r)=={"a","b"} and abs(da-4.6)<0.5 and abs(db-5.4)<0.5, (da,db))
# silence only -> nothing
synth(d/"s3.wav",[],5); check("silence gives no clips", au.smart_clips(d/"s3.wav",[("a",1.0)],sd/"q")=={})
# short click-noise dropped
synth(d/"s4.wav",[(1,1.1)],4); check("click noise dropped", au.smart_clips(d/"s4.wav",[("a",1.0)],sd/"q4")=={})
# waits are trimmed: two utterances for one click separated by a long silence
synth(d/"s5.wav",[(0.5,1.5),(8,9)],10); r=au.smart_clips(d/"s5.wav",[("a",9.5)],sd/"w","next")
check("long waits cut out", abs(dur(sd/"w"/"a.wav")-(1.0+1.0+0.3+0.3+0.25))<0.35, dur(sd/"w"/"a.wav"))
check("assign modes constant", sr.ASSIGN==("next","prev"))
print(ok,"passed,",bad,"failed")

# --- crash-safe streaming + recovery
import importlib
importlib.reload(au)
dd=Path(tempfile.mkdtemp()); raw=dd/"audio"/"narration.raw"
pcm=b"".join(struct.pack("<h",int(8000*math.sin(i/5))) for i in range(11025*3))
n=au.Narrator(raw=raw); n.format=(11025,1); n.running=True
for i in range(0,len(pcm),4410): n._append(pcm[i:i+4410])
check("raw file grows while recording", raw.exists() and raw.stat().st_size==len(pcm), raw.stat().st_size)
check("format sidecar written", Path(str(raw)+".fmt").read_text()=="11025 1")
check("nothing held in memory", len(n._data)==0)
out=dd/"audio"/"narration.wav"; check("stop converts", n.stop(out) and abs(au.duration(out)-3.0)<0.01)
check("raw removed after stop", not raw.exists() and not Path(str(raw)+".fmt").exists())
# crash: raw left behind
S2=tm.Session(tempfile.mkdtemp(),"crash"); S2.make_dirs(); (S2.dir/"audio").mkdir(exist_ok=True)
(S2.dir/"audio"/"narration.raw").write_bytes(b"".join(struct.pack("<h",int(8000*math.sin(i/5))) if 11025*1<=i<11025*3 else struct.pack("<h",0) for i in range(11025*5)))
(S2.dir/"audio"/"narration.raw.fmt").write_text("11025 1")
for k,t in enumerate((1.5,4.5)):
    S2.add(tm.Step(f"id{k}","click",apos=t,friendly=f"c{k}"))
got=au.recover_session(S2)
check("recovered + clips cut", got==1 and S2.steps[0].audio and (S2.dir/S2.steps[0].audio).exists(), (got,[s.audio for s in S2.steps]))
check("wav kept for re-cutting", (S2.dir/"audio"/"narration.wav").exists() and not (S2.dir/"audio"/"narration.raw").exists())
check("nothing to recover is None", au.recover_session(S2) is None)
# tiny/empty raw is discarded
S3=tm.Session(tempfile.mkdtemp(),"c3"); S3.make_dirs(); (S3.dir/"audio").mkdir(exist_ok=True); (S3.dir/"audio"/"narration.raw").write_bytes(b"\0"*100)
check("tiny raw discarded", au.recover_session(S3) is None and not (S3.dir/"audio"/"narration.raw").exists())
# cancel removes raw
n2=au.Narrator(raw=dd/"audio"/"x.raw"); n2.format=(11025,1); n2.running=True; n2._append(pcm[:5000]); n2.cancel(); check("cancel cleans up", not (dd/"audio"/"x.raw").exists())
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
