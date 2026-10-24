import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep_help as h
root=tk.Tk(); w=h.HelpWindow(root,"about"); root.update()
def walk(x):
    for c in x.winfo_children():
        yield c; yield from walk(c)
assert any("log folder" in str(c.cget("text")) for c in walk(w) if c.winfo_class()=="TLabel")
h.open_log_folder("/tmp/xx_log/telestep_debug.log"); print("about ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
