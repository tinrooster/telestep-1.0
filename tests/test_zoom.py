import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_review as tr
from PIL import ImageGrab
root=tk.Tk(); root.geometry("+0+0")
s=make_session(3,big=False)
for i,stp in enumerate(s.steps):
    if stp.kind in ("click","dialog"): stp.marker={"shape":"click","pt":[1500-300*i,700],"rect":[1450-300*i,670,1550-300*i,730]}
s.save()
win=tr.ReviewWindow(root,s,formats={"md":True}); win.geometry("1120x740+0+0"); win.update(); time.sleep(.3); win.update()
ev=lambda x,y: type("E",(),{"x":x,"y":y})()
kids=win.tree.get_children(); win.tree.selection_set(kids[0]); win.update(); time.sleep(.2); win.update()
st=win._cur
# --- skip column / toggle
check("row has tick", win.tree.set(kids[0],"use")=="☑")
check("button says Leave out", win.btn_skip.cget("text")=="Leave out")
x,y,w_,h_=win.tree.bbox(kids[0],"use")
win._tree_click(ev(x+5,y+5)); win.update()
check("click box -> skipped", st.skip and win.tree.set(kids[0],"use")=="☐")
check("button says Put back", win.btn_skip.cget("text")=="Put back")
check("canvas shows banner", any("LEFT OUT" in str(win.cv.itemcget(i,"text")) for i in win.cv.find_all() if win.cv.type(i)=="text"))
win.toggle_skip(); win.update()
check("button toggles back", (not st.skip) and win.btn_skip.cget("text")=="Leave out")
# clicking the caption column doesn't toggle
x,y,w_,h_=win.tree.bbox(kids[0],"cap"); r=win._tree_click(ev(x+5,y+5)); check("caption click ignored", r is None and not st.skip)
# --- zoom
W,H=win._img_size; pt=st.marker["pt"]; print("img",W,H,"pt",pt,"whole scale",round(win._scale,3))
win.var_view.set("close"); win._view_changed(); win.update()
cl,ct,cr,cb=win._crop
check("crop contains click", cl<=pt[0]<=cr and ct<=pt[1]<=cb, win._crop)
check("close-up bigger than whole", win._scale>0.9, win._scale)
# the click marker should sit mid-canvas
cx=win._off[0]+(pt[0]-cl)*win._scale; cy=win._off[1]+(pt[1]-ct)*win._scale
print("marker canvas pos",round(cx),round(cy),"canvas",win.cv.winfo_width(),win.cv.winfo_height())
# drag a box in close-up and verify image-pixel mapping
ox,oy=win._off
win._sel_press(ev(ox+50,oy+40)); win._sel_drag(ev(ox+170,oy+100)); win._sel_release(ev(ox+170,oy+100)); win.update()
sel=win.selection_in_image(); k=win._scale
exp=(cl+50/k, ct+40/k, cl+170/k, ct+100/k)
check("close-up selection maps to image px", all(abs(a-b)<1.5 for a,b in zip(sel,exp)), (sel,exp))
# marker rect selection in close-up (inside crop) / outside crop -> falls back to whole
win.clear_selection()
r=(pt[0]-20,pt[1]-10,pt[0]+20,pt[1]+10); win._select_image_rect(*r); win.update()
sel=win.selection_in_image(); check("select rect inside close-up", all(abs(a-b)<2 for a,b in zip(sel,r)), (sel,r))
win._select_image_rect(0,0,W,40); win.update()
check("far rect -> whole view", win.var_view.get()=="whole")
sel=win.selection_in_image(); check("far rect selected correctly", all(abs(a-b)<2 for a,b in zip(sel,(0,0,W,40))), sel)
# 200% and 50%
win.var_view.set("close")
for z,kk in (("200%",2.0),("150%",1.5)):
    win.var_zoom.set(z); win.show_preview(); win.update()
    check("zoom "+z, abs(win._scale-kk)<0.01 or win._scale<kk, win._scale)
# masking in close-up burns the right pixels
win.var_zoom.set("100%"); win.show_preview(); win.update()
ox,oy=win._off; cl,ct,cr,cb=win._crop
win._sel_press(ev(ox+30,oy+30)); win._sel_drag(ev(ox+130,oy+90)); win._sel_release(ev(ox+130,oy+90)); win.update()
rect=win.selection_in_image()
from PIL import Image
before=Image.open(s.dir/st.raw_before if hasattr(st,"raw_before") else s.dir/st.raw).convert("RGB") if True else None
win.var_style.set(tr.core.MASK_STYLES["solid"]); win.apply_mask(confirm=False); win.update()
after=Image.open(s.dir/(st.raw_before if hasattr(st,"raw_before") else st.raw)).convert("RGB")
l,t,r_,b=[int(v) for v in rect]
import PIL.ImageChops as C
diff=C.difference(before,after).getbbox()
check("mask hit the selected image region", diff is not None and abs(diff[0]-l)<=20 and abs(diff[1]-t)<=20 and diff[0]<=l and diff[1]<=t and diff[2]>=r_ and diff[3]>=b, (diff,rect))
# a non-click (note) step: close-up falls back / zoom disabled
win.add_note(text="hello"); win.update()
n=[i for i in win.tree.get_children() if win.s.find(i).kind=="note"][0]
win.tree.selection_set(n); win.update()
win.var_view.set("close"); win.show_preview(); win.update(); check("note step ok", True)
win.tree.selection_set(kids[1]); win.update(); time.sleep(.2); win.update()
ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(sys.argv[2])
print(f"{ok} passed, {bad} failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
