import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_review as tr, telestep_core as core
import tkinter.ttk
from tkinter import messagebox
messagebox.askyesno=lambda *a,**k: True; messagebox.showinfo=lambda *a,**k: None
root=tk.Tk(); root.geometry("+0+0")
s=make_session(3,big=False)
for st in s.steps:
    if st.kind=="dialog": st.kind="click"
    if st.raw: st.marker={"shape":"click","pt":[400,300],"rect":None,"win":[100,100,1100,800]}
s.save()
win=tr.ReviewWindow(root,s,formats={"md":True}); win.update(); time.sleep(.3); win.update()
ev=lambda x,y: type("E",(),{"x":x,"y":y,"x_root":x,"y_root":y})()
win.tree.selection_set(win.tree.get_children()[0]); win.update(); time.sleep(.3); win.update()
st=win._cur
def banner(): return " ".join(str(win.cv.itemcget(i,"text")) for i in win.cv.find_withtag("hint") if win.cv.type(i)=="text")
def tool(t): win.var_tool.set(t); win._tool_changed(); win.update()
def cpos(ix,iy): return win._to_canvas(ix,iy)
def click(x,y): win._sel_press(ev(x,y)); win._sel_release(ev(x,y)); win.update()
def drag(x0,y0,x1,y1,steps=4):
    win._sel_press(ev(x0,y0))
    for i in range(1,steps+1): win._sel_drag(ev(x0+(x1-x0)*i/steps,y0+(y1-y0)*i/steps))
    win._sel_release(ev(x1,y1)); win.update()
# 1. banner follows the tool immediately
for t,expect in (("box","draw a box"),("arrow","draw an arrow"),("text","type"),("num","place a number"),("select","select"),("hide","hide something")):
    tool(t); check("banner for "+t, expect in banner().lower(), banner())
# 2. toolbar is directly under the picture
check("tools row under the picture", win.cv.grid_info()["row"]==0 and win.cv.master.grid_slaves(row=1)[0].winfo_children()[0].cget("text")=="Tools:")
# 3. box + move + resize
tool("box"); a=cpos(100,100); b=cpos(300,220); drag(*a,*b)
check("box drawn+selected", len(st.marks)==1 and win._msel==0, st.marks)
check("floating bar", win._mbar is not None and len(win.cv.find_withtag("mbar"))==1)
bx,by=win.cv.coords(win.cv.find_withtag("mbar")[0]); check("bar docked at the bottom of the preview", abs(by-(win.cv.winfo_height()-6))<2, (bx,by,win.cv.winfo_height()))
check("simple arrow cursor on draw tools", str(win.cv.cget("cursor"))=="arrow")
check("tool buttons look like buttons", all(str(w_.cget("relief"))=="raised" for w_ in win.cv.master.grid_slaves(row=1)[0].winfo_children() if isinstance(w_,tk.Radiobutton)))
check("four simple fonts", core.MARK_FONTS==["Sans","Serif","Console","Handwriting"] and core.font_family("Arial")=="Sans" and core.font_family("Consolas")=="Console")
p0=list(st.marks[0]["p"])
tool("select"); ea=cpos(p0[0]+(p0[2]-p0[0])/2,p0[1])  # top edge
drag(ea[0],ea[1],ea[0]+40,ea[1]+30)
p1=st.marks[0]["p"]; k=win._scale
check("box moved by drag", abs((p1[0]-p0[0])-40/k)<2 and abs((p1[1]-p0[1])-30/k)<2, (p0,p1))
c=cpos(p1[2],p1[3]); drag(c[0],c[1],c[0]+30,c[1]+20)   # bottom-right handle (box is selected)
p2=st.marks[0]["p"]; check("box resized from corner", abs((p2[2]-p1[2])-30/k)<2 and abs(p2[0]-p1[0])<0.5, (p1,p2))
# 4. arrow: endpoint drag
tool("arrow"); drag(*cpos(400,500),*cpos(550,430)); i=win._msel; check("arrow drawn", st.marks[i]["t"]=="arrow")
ap=list(st.marks[i]["p"]); e=cpos(ap[2],ap[3]); drag(e[0],e[1],e[0]-20,e[1]+25)
check("arrow tip dragged, tail fixed", abs(st.marks[i]["p"][0]-ap[0])<0.5 and abs(st.marks[i]["p"][2]-ap[2]+20/k)<2, st.marks[i])
# 4b. one-shot tools
check("box tool switched back to select after drawing", win.var_tool.get()=="select" and win._msel is not None)
tool("num"); n_=len(st.marks); click(*cpos(1000,150)); check("number placed", len(st.marks)==n_+1)
check("tool returns to Select after one number", win.var_tool.get()=="select")
click(*cpos(1000,500)); check("a further click does NOT add another number", len(st.marks)==n_+1)
win.delete_mark() if win._msel is not None else None
win.var_keep.set(True); tool("num"); n2=len(st.marks); click(*cpos(1100,250)); click(*cpos(1180,330)); check("Keep tool places several", len(st.marks)==n2+2 and win.var_tool.get()=="num")
check("banner mentions Select when keeping", "select / move" in banner().lower() or win._msel is not None)
win.var_keep.set(False); st.marks=[m for m in st.marks if m["t"]!="num"]; win._msel=None; win.show_preview()
# 5. numbers: click places, count up, click again on one moves it instead of adding
win.var_keep.set(True); tool("num"); click(*cpos(800,200)); click(*cpos(900,300)); win.var_keep.set(False); tool("select"); nums=[m for m in st.marks if m["t"]=="num"]
check("numbers 1,2", [m["n"] for m in nums]==[1,2])
n_before=len(st.marks); q=cpos(800,200); drag(q[0],q[1],q[0]+25,q[1]+25)
nm=[m for m in st.marks if m["t"]=="num"]; check("dragging a number moves it (no new mark)", len(st.marks)==n_before and abs(nm[0]["p"][0]-800-25/k)<3, nm[0])
win.delete_mark(); check("delete + renumber", [m["n"] for m in st.marks if m["t"]=="num"]==[1])
# 6. inline text: click, type into the editor on the picture, Enter commits
win.var_keep.set(True); tool("text"); n0=len(st.marks); click(*cpos(200,500)); check("editor opened on the picture", win._editor is not None and len(win.cv.find_withtag("editor"))==1)
check("banner explains typing", "enter" in banner().lower(), banner())
win._editor["w"].insert("1.0","Check this field"); win._commit_editor(); win.update()
check("text mark stored", len(st.marks)==n0+1 and st.marks[-1]["text"]=="Check this field" and win._editor is None)
ti=len(st.marks)-1
win.var_keep.set(True)
# drag-box text width
click_n=len(st.marks); drag(*cpos(700,500),*cpos(900,560)); check("dragged text box -> editor with width", win._editor and len(win._editor["mark"]["p"])==4)
win._editor["w"].insert("1.0","A long note that should wrap inside the box you dragged out"); win._commit_editor(); win.update()
check("wrapped text stored", st.marks[-1]["text"].startswith("A long note") and len(st.marks[-1]["p"])==4)
win._cancel_editor() if win._editor else None
tool("text"); click(*cpos(50,50)); win._cancel_editor(); check("Esc cancels", len(st.marks)==click_n+1)
tool("text"); click(*cpos(50,50)); win._commit_editor(); check("empty text adds nothing", len(st.marks)==click_n+1)
# double-click edit
win.var_keep.set(False); tool("select"); bb=core.mark_bounds(st.marks[ti],win._img_size); cx,cy=cpos((bb[0]+bb[2])/2,(bb[1]+bb[3])/2)
win._sel_press(ev(cx,cy)); win._sel_release(ev(cx,cy)); win._on_double_click(ev(cx,cy)); win.update()
check("double-click edits text", win._editor is not None and win._editor["idx"]==ti)
win._editor["w"].delete("1.0","end"); win._editor["w"].insert("1.0","Edited"); win._commit_editor(); check("text edited", st.marks[ti]["text"]=="Edited")
# 7. properties: opacity / colour / size / font
win._select(ti); win.update(); mb=win._mb
win._set_prop("c","#e53935"); win._set_prop("z",1.5); win._set_prop("f","Serif"); win._set_prop("bg","plain"); win._opacity_moved(40); win.update()
m=st.marks[ti]; check("props saved on mark", m["c"]=="#e53935" and m["z"]==1.5 and m["f"]=="Serif" and m["bg"]=="plain" and abs(m["a"]-0.4)<0.01, m)
check("next marks inherit last props", win._mp["c"]=="#e53935" and abs(win._mp["a"]-0.4)<0.01)
check("bar has font controls for text", "f" in mb and "bg" in mb)
win._select(0); win.update(); check("bar rebuilt for box (no font box)", "f" not in win._mb)
# opacity actually fades the render
img=Image.new("RGB",(1000,600),(255,255,255)); full=Image.new("RGB",(1000,600),(255,255,255)); half=full.copy()
core.draw_marks(full,[{"t":"num","p":[500,300],"n":1,"c":"#000000","a":1.0}]); core.draw_marks(half,[{"t":"num","p":[500,300],"n":1,"c":"#000000","a":0.4}])
check("40% opacity lighter than 100%", sum(half.getpixel((491,300)))>sum(full.getpixel((491,300)))+150 and half.getpixel((491,300))!=(255,255,255), (full.getpixel((491,300)),half.getpixel((491,300))))
# plain text halo / boxed text
for bgm in ("box","plain"):
    im=Image.new("RGB",(1000,600),(30,30,30)); core.draw_marks(im,[{"t":"text","p":[100,100],"text":"Hello","bg":bgm,"c":"#ffffff"}]); check("text renders "+bgm, im.getbbox() and im.getpixel((500,500))==(30,30,30) and len(set(im.crop((90,90,300,160)).getdata()))>1)
bb=core.mark_bounds({"t":"text","p":[100,100],"text":"Hello"},(1400,800)); check("text bounds", bb and bb[2]>bb[0]+20)
# 8. nudge + z-order + duplicate + keyboard delete
win._select(len(st.marks)-1); p_=list(st.marks[-1]["p"]); win.nudge(1,0); win.nudge(10,0); check("nudge", abs(st.marks[-1]["p"][0]-p_[0]-11)<0.01)
n=len(st.marks); win.duplicate_mark(); check("duplicate mark", len(st.marks)==n+1)
win.reorder_mark(False); check("send to back", win._msel==0)
win.cv.focus_force(); win.update(); n=len(st.marks); win.cv.event_generate("<Delete>"); win.update(); check("Delete key removes selected", len(st.marks)==n-1)
# 9. right-click menu
tool("hide"); import tkinter as tk_
cap={}
orig=tr.ReviewWindow._popup
tr.ReviewWindow._popup=staticmethod(lambda m,e: cap.setdefault("m",m))
tgt=[m for m in st.marks if m["t"]=="text"][0]; bb=core.mark_bounds(tgt,win._img_size); x_,y_=cpos((bb[0]+bb[2])/2,(bb[1]+bb[3])/2)
win._cv_menu(ev(x_,y_)); m=cap["m"]; labels=[m.entrycget(i,"label") for i in range(m.index("end")+1) if m.type(i) in ("command","cascade")]
check("menu: edit/delete mark on a mark", "Edit text" in labels and "Delete mark" in labels and "Annotate" in labels, labels)
check("right-click selected the mark", win._msel is not None and st.marks[win._msel] is tgt)
cap.clear(); win._cv_menu(ev(*cpos(1000,100))); m=cap["m"]; labels=[m.entrycget(i,"label") for i in range(m.index("end")+1) if m.type(i) in ("command","cascade")]
check("menu on empty area still has Annotate", "Annotate" in labels and "Delete mark" not in labels, labels)
sub=m.nametowidget(m.entrycget(labels.index("Annotate"),"menu")) if False else None
win._menu_text(500,400); check("menu 'Add text here' opens editor + switches tool", win._editor is not None and win.var_tool.get()=="select"); win._cancel_editor()
win._menu_num(520,420); check("menu 'Add number here'", st.marks[-1]["t"]=="num")
# 10. render never writes marks into raw; marks survive save/load
raw0=Image.open(s.dir/st.raw).convert("RGB").tobytes(); win.s.save()
check("marks persist", len(tr.Session.load(s.dir).steps[0].marks)==len(st.marks))
r=tr.rep.render_step_image(s,st,1); check("export render has marks, raw doesn't", r.tobytes()!=raw0 and Image.open(s.dir/st.raw).convert("RGB").tobytes()==raw0)
# 11. other step resets the selection and bar
win.tree.selection_set(win.tree.get_children()[1]); win.update(); check("switching step clears selection/bar", win._msel is None and win._mbar is None)
win.tree.selection_set(win.tree.get_children()[0]); win.update(); win._select(0); win.update(); time.sleep(.2); win.update()
from PIL import ImageGrab
try: ImageGrab.grab(bbox=(0,0,win.winfo_width()+10,win.winfo_height()+40)).save(sys.argv[2])
except Exception as e: print("noshot",e)
print(ok,"passed,",bad,"failed")
# ---- text resize + list stripes + single instance
win.var_keep.set(False); tool("select"); win.update()
ti=[i for i,m in enumerate(st.marks) if m["t"]=="text"][-1]; win._select(ti); win.update()
bb=core.mark_bounds(st.marks[ti],win._img_size); w0=bb[2]-bb[0]; midy=(bb[1]+bb[3])/2
rx,ry=cpos(bb[2],midy); drag(rx,ry,rx+60,ry)
bb2=core.mark_bounds(st.marks[ti],win._img_size); check("text widened by right handle", bb2[2]-bb2[0]>w0+30/win._scale and abs(bb2[0]-bb[0])<1, (w0,bb2[2]-bb2[0]))
check("text mark is now a sized box", len(st.marks[ti]["p"])==4)
lx,ly=cpos(bb2[0],(bb2[1]+bb2[3])/2); drag(lx,ly,lx+50,ly)
bb3=core.mark_bounds(st.marks[ti],win._img_size); check("left handle narrows from the left", bb3[2]-bb3[0]<bb2[2]-bb2[0]-20 and abs(bb3[2]-bb2[2])<1, (bb2,bb3))
check("text handles drawn", len(win.cv.find_withtag("mhandle"))>=3)
kids=win.tree.get_children(); check("alternate rows striped", "stripe" in win.tree.item(kids[1],"tags") and "stripe" not in win.tree.item(kids[0],"tags"))
check("row height set", int(tk.ttk.Style(win).lookup("Review.Treeview","rowheight") or 0)>=28)
import telestep_core as c2; check("single instance off-Windows is permissive", c2.single_instance("x") is True and c2.single_instance("x") is True)
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
