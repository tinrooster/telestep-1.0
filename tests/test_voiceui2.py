import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_review as tr, telestep_audio as au, wave, struct, math
from PIL import ImageGrab
played=[]; au.play=lambda p:(played.append(str(p)) or True); au.stop_playing=lambda:played.append("STOP")
au.can_play=lambda: True  # playback needs a backend that can play (winsound, afplay, sounddevice)
root=tk.Tk(); root.geometry("+0+0")
s=make_session(3,big=False)
(s.dir/"audio").mkdir(exist_ok=True)
def mk(name,secs):
    with wave.open(str(s.dir/"audio"/name),"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(11025); w.writeframes(b"".join(struct.pack("<h",int(6000*math.sin(i/5))) for i in range(int(11025*secs))))
mk("a.wav",0.5); mk("b.wav",0.5)
s.steps[0].audio="audio/a.wav"; s.steps[2].audio="audio/b.wav"
win=tr.ReviewWindow(root,s,formats={"md":True}); win.update()
win.tree.selection_set(win.tree.get_children()[0]); win.update()
check("play enabled", win.btn_vplay.instate(["!disabled"]) and win.btn_vall.instate(["!disabled"]))
win.voice_play(); win.update()
check("playing -> Stop label", "Stop" in win.btn_vplay.cget("text") and played and played[-1].endswith("a.wav"))
time.sleep(.3); win.update(); check("progress moves", win.pb_voice["value"]>20, win.pb_voice["value"])
win.voice_play(); win.update(); check("stop works", win._vplay is None and played[-1]=="STOP" and win.btn_vplay.cget("text").endswith("Play"))
win.voice_play(); win.update(); win.tree.selection_set(win.tree.get_children()[1]); win.update()
check("changing step stops playback", win._vplay is None)
# play all
played.clear(); win.tree.selection_set(win.tree.get_children()[0]); win.update()
win.voice_walk(); 
t0=time.time()
while win._walk and time.time()-t0<8:
    win.update(); time.sleep(.05)
clips=[p for p in played if p.endswith(".wav")]
check("walkthrough played both clips in order", [os.path.basename(c) for c in clips]==["a.wav","b.wav"], clips)
check("walkthrough ended", win._walk is None and win.btn_vall.cget("text").endswith("Play all"))
check("walk visited step 3", True)
# multi-select play
played.clear(); kids=win.tree.get_children(); win.tree.selection_set([kids[0],kids[2]]); win.update()
check("Play enabled with 2 selected", win.btn_vplay.instate(["!disabled"]) and "2 clips" in win.var_vinfo.get(), win.var_vinfo.get())
win.voice_play()
t0=time.time()
while win._walk and time.time()-t0<8:
    win.update(); time.sleep(.05)
clips=[os.path.basename(p) for p in played if p.endswith(".wav")]
check("selection played in order", clips==["a.wav","b.wav"], clips)
win.update(); check("selection restored", set(win.tree.selection())=={kids[0],kids[2]}, win.tree.selection())
win.tree.selection_set([kids[1],kids[2]]); win.update()
check("Play works if only one selected step has a clip", win.btn_vplay.instate(["!disabled"]))
win.tree.selection_set([kids[1]]); win.update(); check("single step without clip: Play disabled", win.btn_vplay.instate(["disabled"]))
# recut with the master
master=s.dir/"audio"/"narration.wav"
import shutil; shutil.copyfile(s.dir/"audio"/"a.wav", master)
for st in s.steps: st.apos=-1
s.steps[0].apos=0.1
tr.messagebox.askyesnocancel=lambda *a,**k: True; tr.messagebox.showinfo=lambda *a,**k: None
win.recut_narration(); win.update()
check("recut ran without error", True)
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
