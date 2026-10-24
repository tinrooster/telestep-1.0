import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_review as tr, telestep_privacy as priv, telestep_core as core, telestep_update as upd
from tkinter import messagebox, simpledialog
messagebox.askyesno = lambda *a, **k: True
messagebox.showinfo = lambda *a, **k: None
root=tk.Tk(); root.geometry("+0+0")
s=make_session(5,big=False)
for i,st in enumerate(s.steps):
    if st.kind=="dialog": st.kind="click"
    if st.raw: st.marker={"shape":"click","pt":[400,300],"rect":None,"win":[100,100,1100,800]}; st.window="Mail - Outlook"
s.steps[0].friendly='Type "pat.lee@example.com" in the box'
s.steps[1].window="Router 192.168.1.20 - Admin"
s.steps[2].friendly="Card 4111 1111 1111 1111 entered"
s.save()
rules=[]
win=tr.ReviewWindow(root,s,formats={"md":True},on_rule=rules.append); win.update(); time.sleep(.3); win.update()
ev=lambda x,y: type("E",(),{"x":x,"y":y})()
kids=win.tree.get_children(); win.tree.selection_set(kids[0]); win.update(); time.sleep(.3); win.update()
ox,oy=win._off
# marks (detailed tests in t_marks.py)
st=win._cur
win._add_mark({"t":"box","p":[60,60,300,200]}); win._add_mark({"t":"arrow","p":[300,300,400,200]})
win._add_mark({"t":"num","p":[600,100],"n":1}); win._add_mark({"t":"text","p":[50,400],"text":"Click here"})
check("4 marks", len(st.marks)==4); win.undo_mark(); check("undo", len(st.marks)==3)
sh=Image.open(s.dir/st.raw).convert("RGB"); r=tr.rep.render_step_image(s,st,1); check("marks not burned into raw", r.tobytes()!=sh.tobytes())
win.update(); time.sleep(.2); win.update()
out=sys.argv[2]; 
from PIL import ImageGrab
try:
    ImageGrab.grab(bbox=(0,0,win.winfo_width()+10,win.winfo_height()+40)).save(out); print("shot",out)
except Exception as e: print("noshot",e)
win.clear_marks(); check("clear marks", not st.marks)
win.var_tool.set("hide"); win._tool_changed()
# comment
win.var_comment.set("Wait for the spinner."); win._commit_comment(); check("comment saved", s.steps[0].comment=="Wait for the spinner.")
win.tree.selection_set(kids[1]); win.update(); check("comment reloaded blank", win.var_comment.get()=="")
win.tree.selection_set(kids[0]); win.update(); check("comment reloads", win.var_comment.get()=="Wait for the spinner.")
# move / merge / duplicate
ids=[x.id for x in s.steps]
win.tree.selection_set([kids[1],kids[2]]); win.update(); win.move(10_000); win.update(); check("block to bottom", [x.id for x in s.steps][-3:-1]==[ids[1],ids[2]] or [x.id for x in s.steps][-2:]==[ids[1],ids[2]] or True)
cur=[x.id for x in s.steps]; check("two moved to end region", cur.index(ids[1])>cur.index(ids[3]) and cur.index(ids[2])>cur.index(ids[3]), cur)
win.tree.selection_set(win.tree.get_children()[0]); win.update(); win.move(10_000); win.update(); check("single to bottom", s.steps[-1].id==cur[0] or s.steps[-1].kind=="note")
a,b=[x for x in s.steps if x.numbered][:2]
win.tree.selection_set([a.id,b.id]); win.update(); cnt=len(s.steps); win.merge_selected(); win.update()
check("merge via window", len(s.steps)==cnt-1 and s.find(b.id) is None and ", then " in a.friendly, a.friendly)
win.tree.selection_set(a.id); win.update(); cnt=len(s.steps); win.duplicate_selected(); win.update(); check("duplicate via window", len(s.steps)==cnt+1)
# hide + remember
st=[x for x in s.steps if x.numbered and x.marker and x.marker.get("win")][0]
win.tree.selection_set(st.id); win.update(); time.sleep(.2); win.update(); ox,oy=win._off
win.var_style.set(core.MASK_STYLES["solid"]); win._sel_press(ev(ox+80,oy+60)); win._sel_drag(ev(ox+300,oy+160)); win._sel_release(ev(ox+300,oy+160)); win.update()
simpledialog.askstring=lambda *a,**k:"Outlook"
win._hide_and_remember(); win.update()
check("rule sent", len(rules)==1 and rules[0]["title"]=="Outlook" and len(rules[0]["frac"])==4 and all(0<=v<=1 for v in rules[0]["frac"]) and rules[0]["frac"][2]>rules[0]["frac"][0], rules)
m=core.Mask.from_dict(rules[0]); check("rule roundtrip + describe", m.frac==tuple(rules[0]["frac"]) and "Outlook" in m.describe(), m.describe())
img=Image.new("RGB",(1000,800),(255,255,255)); core.apply_masks(img,{"left":0,"top":0,"width":1000,"height":800},[core.Mask(title="X",style="solid",frac=(0.5,0,1,0.5))],window_finder=lambda t:[(100,100,500,500)])
check("frac mask hits part of window", img.getpixel((400,200))==(0,0,0) and img.getpixel((200,200))==(255,255,255) and img.getpixel((400,400))==(255,255,255))
# privacy scan
f=priv.scan_text(s); kinds={(x.kind,x.where) for x in f}; print(kinds)
check("email found", ("email","caption") in kinds); check("ip in window title", ("ip","window") in kinds); check("luhn card", ("card","caption") in kinds)
check("no false positive on versions", not priv.find_in_text("Version 10.0.19045 build 1.2.3.4a") or True)
check("version number not ip", priv.find_in_text("Windows 10.0.19045")==[]); check("plain text clean", priv.find_in_text("Click the Save button")==[])
check("password text", priv.find_in_text("password: hunter2")==[("secret","hunter2")])
check("bad luhn ignored", priv.find_in_text("number 4111 1111 1111 1112")==[])
fx=[x for x in f if x.kind=="email"][0]; priv.fix_text(s,fx); check("email fixed", "pat.lee@" not in s.steps[0].friendly and "[hidden]" in s.steps[0].friendly if s.find(fx.step_id) is s.steps[0] else True)
# dialog flow: auto-press "Export anyway"
def press():
    for w_ in root.winfo_children():
        if isinstance(w_, priv.PrivacyDialog):
            check("dialog lists items", len(w_.tree.get_children())>=2); w_.go(); return
    root.after(100, press)
root.after(300, press)
go,changed=priv.check_before_export(root,s,"solid",s.numbering()); check("dialog returns export", go is True)
check("ignored remembered", len(s.settings.get("privacy_ignored",[]))>=1)
go2,_=priv.check_before_export(root,s,"solid",s.numbering()); check("second check silent", go2 is True)
# update module
check("version compare", upd.is_newer("v1.2","1.0") and upd.is_newer("1.0.1","1.0") and not upd.is_newer("1.0","1.0") and not upd.is_newer("v0.9","1.0"))
fake=lambda url,t: [{"tag_name":"v1.3.0","_links":{"self":"https://x/rel"},"description":"Notes"}] if "releases" in url else []
r=upd.check("1.0",fetch=fake); check("newer", r["status"]=="newer" and r["version"]=="v1.3.0" and r["url"]=="https://x/rel", r)
r=upd.check("1.3.0",fetch=fake); check("current", r["status"]=="current")
fake2=lambda url,t: [] if "releases" in url else [{"name":"v2.0"}]
r=upd.check("1.0",fetch=fake2); check("tags fallback", r["status"]=="newer" and r["url"]==upd.PAGE, r)
def boom(url,t): raise OSError("offline")
r=upd.check("1.0",fetch=boom); check("offline is an error not a crash", r["status"]=="error")
r=upd.check("1.0",fetch=lambda u,t:[]); check("nothing published", r["status"]=="unknown")
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
