import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_review as tr, telestep_audio as au, wave, struct, math
from PIL import ImageGrab
root=tk.Tk(); root.geometry("+0+0")
s=make_session(3,big=False)
st=s.steps[0]
(s.dir/"audio").mkdir(exist_ok=True)
with wave.open(str(s.dir/"audio"/"a.wav"),"wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(11025); w.writeframes(b"".join(struct.pack("<h",int(6000*math.sin(i/5))) for i in range(11025*4)))
st.audio="audio/a.wav"
win=tr.ReviewWindow(root,s,formats={"md":True}); win.update()
win.tree.selection_set(win.tree.get_children()[0]); win.update(); time.sleep(.3); win.update()
check("info shows length", win.var_vinfo.get()=="4 s", win.var_vinfo.get())
check("remove enabled", win.btn_vdel.instate(["!disabled"]))
check("row marked", "\U0001F50A" in win.tree.item(st.id,"values")[3])
check("record disabled off-Windows", win.btn_vrec.instate(["disabled"]))
win.tree.selection_set(win.tree.get_children()[1]); win.update()
check("none on step w/o audio", win.var_vinfo.get().startswith("(") and win.btn_vplay.instate(["disabled"]))
win.tree.selection_set(win.tree.get_children()[0]); win.update()
win.voice_remove(); win.update()
check("removed", st.audio=="" and not (s.dir/"audio"/"a.wav").exists() and win.var_vinfo.get().startswith("("))
x,y=win.winfo_rootx(),win.winfo_rooty()
ImageGrab.grab(bbox=(x,y,x+win.winfo_width(),y+win.winfo_height()), xdisplay=os.environ["DISPLAY"]).save(sys.argv[2])
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
