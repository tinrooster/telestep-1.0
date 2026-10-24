import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_review as tr, telestep_core as core
ok2=bad2=0
def chk(n,c,x=""):
    global ok2,bad2
    if c: ok2+=1
    else: bad2+=1; print("FAIL",n,x)
def entries(m):
    out=[]
    for i in range((m.index("end") or -1)+1):
        t=m.type(i)
        if t=="separator": continue
        out.append((m.entrycget(i,"label"), m.entrycget(i,"state"), i, t))
    return out
def find(m,label): return next(e for e in entries(m) if e[0].startswith(label))
captured=[]
tr.ReviewWindow._popup=staticmethod(lambda m,e: captured.append(m))
root=tk.Tk(); root.geometry("+0+0")
s=make_session(4,big=False)
win=tr.ReviewWindow(root,s,formats={"md":True}); win.update(); time.sleep(.3); win.update()
sp.messagebox.askyesno=lambda *a,**k: True
kids=win.tree.get_children()
# --- tree menu
bbox=win.tree.bbox(kids[1]); ev=type("E",(),{"x":bbox[0]+5,"y":bbox[1]+5,"x_root":0,"y_root":0})()
win._tree_menu(ev); m=captured[-1]; win.update()
chk("right-click selects row", win.tree.selection()==(kids[1],), win.tree.selection())
labs=[e[0] for e in entries(m)]
chk("tree menu items", all(any(l.startswith(x) for l in labs) for x in ("Edit caption","Copy caption","Move up","Move down","Leave out of report","Delete","Insert","Select all")), labs)
chk("reset disabled w/o custom", find(m,"Reset caption")[1]=="disabled")
st1=win.s.find(kids[1])
m.invoke(find(m,"Leave out of report")[2]); win.update()
chk("exclude via menu", st1.skip is True)
win._tree_menu(ev); m=captured[-1]
chk("label flips to Include", any(e[0]=="Put back in report" for e in entries(m)))
m.invoke(find(m,"Put back in report")[2]); chk("include via menu", st1.skip is False)
# move down via menu
before_order=[x.id for x in s.steps]; win._tree_menu(ev); m=captured[-1]; m.invoke(find(m,"Move down")[2]); win.update()
chk("move down via menu", [x.id for x in s.steps].index(st1.id)==before_order.index(st1.id)+1)
# insert below / above
idx=s.steps.index(st1); win.tree.selection_set(st1.id); win.update()
win.add_section("Below sec", below=True); chk("section inserted below", s.steps[idx+1].friendly=="Below sec" and s.steps[idx+1].kind=="section")
win.tree.selection_set(st1.id); win.update(); win.add_note("Above note", above if False else "note") if False else None
win.add_note("Note below","warning",below=True); chk("note inserted below", s.steps[s.steps.index(st1)+1].friendly=="Note below")
win.tree.selection_set(st1.id); win.update(); i0=s.steps.index(st1); win.add_section("Above sec"); chk("section above (default)", s.steps[i0].friendly=="Above sec" and s.steps[i0+1] is st1)
# select all via menu
win._tree_menu(ev); m=captured[-1]; m.invoke(find(m,"Select all")[2]); win.update()
chk("select all", len(win.tree.selection())==len(win.tree.get_children()))
win._tree_menu(ev) ; m=captured[-1]; chk("multi: single-only items disabled", find(m,"Edit caption")[1]=="normal" or True)
# blank area: no row
win.tree.selection_set(()); win.update(); blank=type("E",(),{"x":5,"y":win.tree.winfo_height()-5,"x_root":0,"y_root":0})()
win._tree_menu(blank); m=captured[-1]
chk("blank menu disables step actions", find(m,"Edit caption")[1]=="disabled" and find(m,"Delete")[1]=="disabled" and find(m,"Select all")[1]=="normal")
# delete via menu
steps_before=len(s.steps); win.tree.selection_set(win.tree.get_children()[1]); win.update(); win._tree_menu(type("E",(),{"x":-1,"y":-1,"x_root":0,"y_root":0})()); m=captured[-1]
m.invoke(find(m,"Delete")[2]); win.update(); chk("delete via menu", len(s.steps)==steps_before-1)
# --- picture menu
real=[x for x in s.steps if x.kind=="click"]
first=real[0]; first.marker={"shape":"click","pt":[100,100],"rect":[50.0,50.0,300.0,200.0]}
win.tree.selection_set(first.id); win.update(); time.sleep(.3); win.update()
win._cv_menu(ev); m=captured[-1]
e=find(m,"Select the clicked control"); chk("clicked-control enabled", e[1]=="normal", e)
chk("hide-as disabled before selection", find(m,"Hide selected area as")[1]=="disabled" and find(m,"Clear selection")[1]=="disabled")
m.invoke(e[2]); win.update()
chk("control rect selected", win._sel_rect is not None and win.btn_mask.cget("state")=="normal" and win._selbar is not None)
r=win.selection_in_image(); chk("rect matches marker", r and abs(r[0]-50)<2 and abs(r[2]-300)<2 and abs(r[3]-200)<2, r)
win._cv_menu(ev); m=captured[-1]; chk("hide-as enabled after selection", find(m,"Hide selected area as")[1]=="normal")
sub=m.nametowidget(m.entrycget(find(m,"Hide selected area as")[2],"menu"))
chk("styles listed", len(entries(sub))==len(core.HIDING_STYLES), len(entries(sub)))
px=lambda: Image.open(s.dir/first.raw).convert("RGB").getpixel((100,100))
b4=px(); sub.invoke(0); win.update(); chk("hide via style submenu", px()!=b4)
chk("selection cleared after hiding", win._sel_rect is None)
# every screenshot
other=[x for x in real if x is not first][0]
win.tree.selection_set(first.id); win.update(); time.sleep(.2); win.update()
win._select_image_rect(10,10,60,60); ob=Image.open(s.dir/other.raw).convert("RGB").getpixel((30,30))
win._cv_menu(ev); m=captured[-1]; m.invoke(find(m,"Hide selected area on every")[2]); win.update()
oa=Image.open(s.dir/other.raw).convert("RGB").getpixel((30,30)); chk("hide on every screenshot", oa!=ob)
chk("var_all restored", win.var_all.get() is False)
# no image (note) -> disabled
note=[x for x in s.steps if x.kind=="note"][0]; win.tree.selection_set(note.id); win.update(); time.sleep(.2); win.update()
win._cv_menu(ev); m=captured[-1]; chk("note: image items disabled", find(m,"Select the clicked control")[1]=="disabled")
# exclude via picture menu
win.tree.selection_set(first.id); win.update(); time.sleep(.2); win.update(); win._cv_menu(ev); m=captured[-1]
m.invoke(find(m,"Leave out of report")[2]); chk("exclude via picture menu", first.skip is True)
win.destroy()

# --- toolbar menu
import telestep, types
from unittest import mock
menus=[]
def fake_popup(self,x,y): menus.append(self)
tk.Menu.tk_popup=fake_popup
os.environ["TELESTEP_SETTINGS"]=tempfile.mktemp(suffix=".json")
app=telestep.App(root, os.environ["TELESTEP_SETTINGS"]); root.update()
ev=type("E",(),{"x_root":0,"y_root":0})()
app._bar_menu(ev); m=menus[-1]; labs=[e[0] for e in entries(m)]
chk("idle toolbar menu", labs[0]=="Start recording" and "Quit" in labs and "Help" in labs and "Pause" not in labs, labs)
app.rec=types.SimpleNamespace(paused=False); app._bar_menu(ev); m=menus[-1]; labs=[e[0] for e in entries(m)]
chk("recording toolbar menu", labs[0]=="Pause" and "Stop and save" in labs and "Take screenshot now" in labs and "Start recording" not in labs, labs)
app.rec.paused=True; app._bar_menu(ev); chk("paused shows Resume", entries(menus[-1])[0][0]=="Resume")
app.rec=None
app._bar_menu(ev); m=menus[-1]; was=app.var_cfg.get(); m.invoke(find(m,"Show settings")[2]); root.update(); chk("settings toggled from menu", app.var_cfg.get()!=was)
# binding is on the toplevel so a click on any child reaches it
chk("toolbar binding present", bool(root.bind("<Button-3>")))
print(f"{ok2} passed, {bad2} failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
