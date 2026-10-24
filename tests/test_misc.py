import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_review as tr, telestep_settings as cfg, telestep
from tkinter import messagebox
messagebox.showinfo = lambda *a, **k: None
root = tk.Tk()
s = make_session(3, big=False)
win = tr.ReviewWindow(root, s, formats={"md": True}); win.update()
win.exported = {"md": str(s.dir / "big.md")}
check("no note when small", win._size_note() == "")
with open(s.dir / "big.md", "wb") as f:
    f.truncate(26 * 1024 * 1024)
check("size note when >25MB", "Large file" in win._size_note() and "26 MB" in win._size_note(), win._size_note())
# originals deleted -> tools off, hint explains
tr.rep.export(s, tr.rep.Template(style="onesheet"), ["html"])
messagebox.askyesno = lambda *a, **k: True
win.delete_originals(); win.update()
check("flag set", win._originals_gone())
check("hint says why", "deleted" in win.var_hint.get(), win.var_hint.get())
check("mask refuses", win.apply_mask() == 0)
# tray hint text
class FakeIcon: title = ""
t = telestep.Tray.__new__(telestep.Tray) if hasattr(telestep, "Tray") else None
if t is not None:
    t.icon = FakeIcon(); t.set_hint("rec", True); check("tray mic on", "microphone ON" in t.icon.title, t.icon.title)
    t.set_hint("rec", False); check("tray mic off", "microphone off" in t.icon.title)
    t.set_hint("idle"); check("tray idle", t.icon.title == "Telestep - not recording")
print(f"{ok} passed, {bad} failed"); sys.exit(1 if bad else 0)
