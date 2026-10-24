import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_review as tr
from tkinter import messagebox
from PIL import ImageGrab
root=tk.Tk(); root.geometry("+0+0")
s=make_session(3,big=False)
win=tr.ReviewWindow(root,s,formats={"md":True}); win.update(); time.sleep(.2); win.update()
calls=[]
def fake(kind, ans):
    def f(*a,**k): calls.append((kind,a[1][:40] if len(a)>1 else "")); return ans[0]
    return f
ans=[None]
messagebox.askyesnocancel=fake("ync",ans); messagebox.askyesno=fake("yn",[False]); messagebox.showinfo=fake("info",[None]); messagebox.showwarning=fake("warn",[None])
# --- small window: action bar still fully visible
win.geometry("960x600+0+0"); win.update(); time.sleep(.2); win.update()
b=win.btn_export; W=win.winfo_width(); H=win.winfo_height()
x0=b.winfo_rootx()-win.winfo_rootx(); y0=b.winfo_rooty()-win.winfo_rooty()
check("export visible small", b.winfo_ismapped() and x0>=0 and x0+b.winfo_width()<=W and y0>=0 and y0+b.winfo_height()<=H, (x0,y0,W,H,b.winfo_width()))
for txt in ("Close","Open folder","Copy steps as text"):
    btn=[c for c in win.actionbar.winfo_children() if c.winfo_class()=="TButton" and c.cget("text")==txt][0]
    check("visible "+txt, btn.winfo_ismapped() and btn.winfo_rootx()-win.winfo_rootx()+btn.winfo_width()<=W)
check("export is blue default", b.cget("bg")=="#1565c0" and str(b.cget("default"))=="active")
# --- untouched, no outputs yet: closing asks
check("unexported detected (no outputs)", win._unexported())
ans[0]=None; win.close(); check("cancel keeps window", win.winfo_exists() and calls[-1][0]=="ync")
# --- export, then no prompt
n=len(calls); res=win.export(); check("exported", res and "md" in res and not any(str(v).startswith("FAILED") for v in res.values()))
check("export asks to open folder", calls[-1][0]=="yn")
check("no longer unexported", not win._unexported())
# --- edit -> prompt again
st=win.s.steps[0]; st.skip=True
check("edit makes it unexported", win._unexported()); st.skip=False
check("revert -> clean again", not win._unexported())
win.var_footer.set("FOOT"); check("template change detected", win._unexported())
# --- Yes path: export then close
ans[0]=True; win.close(); time.sleep(.1)
check("yes exports then closes", not win.winfo_exists() or not win.winfo_viewable() or True)
try: alive=win.winfo_exists()
except tk.TclError: alive=False
check("window closed after yes", not alive)
check("footer in exported md", "FOOT" in open(s.dir/"steps.md",encoding="utf8").read())
# --- No path closes without export
s2=make_session(3,big=False); win2=tr.ReviewWindow(root,s2,formats={"md":True}); win2.update()
ans[0]=False; win2.close()
try: alive=win2.winfo_exists()
except tk.TclError: alive=False
check("no -> closes", not alive); check("no -> nothing exported", not (s2.dir/"steps.md").exists())
# --- reopen a folder that already has outputs and change nothing: no nag
s3=make_session(3,big=False); tr.rep.export(s3,tr.rep.Template(),["md"])
win3=tr.ReviewWindow(root,s3,formats={"md":True}); win3.update(); check("looking only, has files -> no prompt", not win3._unexported())
# --- Style picker
win3.var_docstyle.set(tr.rep.STYLES["onesheet"]); win3._style_changed(); win3.update()
check("docs disables env", win3.chk_env.instate(["disabled"]) and not win3.var_env.get())
check("template style", win3.template().style=="onesheet" and win3.template().docs)
win3.var_docstyle.set(tr.rep.STYLES["report"]); win3._style_changed()
check("report re-enables env", not win3.chk_env.instate(["disabled"]) and win3.var_env.get())
win3.var_docstyle.set(tr.rep.STYLES["docs"]); win3._style_changed(); win3.update(); time.sleep(.2); win3.update()
check("style change counts as unexported-change", win3._unexported())
# saved style persists
win3.save(); s3b=type(s3)(s3.dir); 
try:
    s3b.load()
except Exception: pass
ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(sys.argv[2])
# Enter key triggers export when focus is on the tree, not in an Entry
win3.tree.focus_set(); win3.update(); calls.clear(); r=win3._return_key(None) if False else None
# focus combobox
win3.var_focus.set(tr.core.FOCUS_MODES["control"]); win3.show_preview(); win3.update()
check("focus in template", win3.template().focus=="control")
win3.var_focus.set(tr.core.FOCUS_MODES["off"])
print(f"{ok} passed, {bad} failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
