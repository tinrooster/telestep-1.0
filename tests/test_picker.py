import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, os, json, tempfile, time
from unittest import mock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"):
    sys.modules[m]=mock.MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk
from pathlib import Path
import telestep_widgets as w
ok=bad=0
def chk(n,c,x=""):
    global ok,bad
    if c: ok+=1
    else: bad+=1; print("FAIL",n,x)
base=Path(tempfile.mkdtemp())
def mk(name, created, title, steps):
    d=base/name; d.mkdir(); (d/"session.json").write_text(json.dumps({"title":title,"created":created,"steps":steps}),encoding="utf-8")
st=lambda k="click",skip=False: {"kind":k,"skip":skip}
mk("a","2026-10-20T09:00:00","Old one",[st(),st()])
mk("c","2026-10-23T01:10:00","Newest",[st(),st(),st("note"),st("section"),st(skip=True),st()])
mk("b","2026-10-22T14:30:00","Middle",[st()])
(base/"empty_dir").mkdir(); (base/"notes.txt").write_text("x")
(base/"broken").mkdir(); (base/"broken"/"session.json").write_text("{nope")
rows=w.list_sessions(base)
chk("only valid sessions", len(rows)==3, [r[2] for r in rows])
chk("newest first", [r[2] for r in rows]==["Newest","Middle","Old one"], [r[2] for r in rows])
chk("step count ignores notes/sections/excluded", rows[0][3]==3 and rows[1][3]==1 and rows[2][3]==2, [r[3] for r in rows])
chk("created formatted", rows[0][1]=="2026-10-23 01:10", rows[0][1])
chk("missing base ok", w.list_sessions(base/"nope")==[])
tk.Toplevel.wait_window=lambda self,*a: None; tk.Toplevel.grab_set=lambda self: None
root=tk.Tk()
p=w.SessionPicker(root, base); root.update()
chk("rows shown", len(p.tree.get_children())==3 and p.tree.selection()==("0",))
chk("open enabled", str(p.btn_open.cget("state"))=="normal")
p.ok(); chk("ok returns newest", p.result==base/"c", p.result)
p=w.SessionPicker(root, base); p.tree.selection_set("2"); p.ok(); chk("choose another", p.result==base/"a")
from tkinter import filedialog
filedialog.askdirectory=lambda **k: str(base/"b")
p=w.SessionPicker(root, base); p.browse(); chk("browse returns folder", p.result==base/"b")
filedialog.askdirectory=lambda **k: ""
p=w.SessionPicker(root, base); p.browse(); chk("browse cancel keeps picker", p.result is None and p.winfo_exists())
p.destroy()
empty=Path(tempfile.mkdtemp()); p=w.SessionPicker(root, empty)
chk("empty: open disabled, no result", str(p.btn_open.cget("state"))=="disabled" and (p.ok() or p.result is None))
# wiring: App.open_review with no session uses the picker
import telestep
from telestep_model import Session
os.environ["TELESTEP_SETTINGS"]=tempfile.mktemp(suffix=".json")
app=telestep.App(root, os.environ["TELESTEP_SETTINGS"]); app.base=base; root.update()
seen={}
(base/"c"/"steps.docx").write_bytes(b"x"*3000); (base/"c"/"walkthrough.html").write_bytes(b"y"*2000000)
p=w.SessionPicker(root, base); v=p.tree.item("0","values")
chk("exports + size shown", "docx" in v[3] and "player" in v[3] and v[4].endswith("MB"), v)
chk("unexported marked", p.tree.item("2","values")[3]=="(not exported)")
from tkinter import messagebox
messagebox.askyesno=lambda *a,**k: False
p.tree.selection_set("0"); p.delete(); chk("delete declined keeps it", (base/"c").exists())
messagebox.askyesno=lambda *a,**k: True
p.delete(); chk("delete removes folder + row", not (base/"c").exists() and len(p.tree.get_children())==2)
class FakePicker:
    def __init__(self, parent, b): seen["base"]=b; self.result=None
telestep.w.SessionPicker=FakePicker
app.open_review(); chk("toolbar uses picker, cancel opens nothing", seen["base"]==base and app.review is None)
tips=[]
for b in (app.btn_review, app.btn_folder): pass
src=open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "telestep.py"), encoding="utf-8").read()
chk("tooltips clarified", "pick from a list" in src and "File Explorer" in src)
print(f"{ok} passed, {bad} failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
