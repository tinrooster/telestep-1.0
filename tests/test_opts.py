import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys
from unittest import mock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"):
    sys.modules[m]=mock.MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import os, tempfile, tkinter as tk
os.environ["TELESTEP_SETTINGS"]=tempfile.mktemp(suffix=".json")
import telestep
root=tk.Tk()
try:
    app=telestep.App(root, os.environ["TELESTEP_SETTINGS"]); root.update()
    print("App built OK; tray ok:", app.tray.ok, "| closetray var:", app.var_closetray.get())
    app.var_tray.set(True); app.tray.icon=object()
    app.on_close(); root.update()
    print("after X with tray: state =", root.state())
    app.on_close(force=True)
except Exception as e:
    import traceback; traceback.print_exc()
if 'ok' in globals(): sys.exit(1 if bad else 0)
