import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep_widgets as w
f=w.hotkey_from_event
assert f("F7",0)==("f7",None)
assert f("F7",0x4|0x1)==("ctrl+shift+f7",None)
assert f("a",0)[0] is None
assert f("a",0x4)==("ctrl+a",None)
assert f("A",0x4|0x1)==("ctrl+shift+a",None)
assert f("Control_L",0x4)==(None,"")
assert f("Escape",0)[0] is None
assert f("Next",0x4)==("ctrl+pagedown",None)
assert f("Pause",0)==("pause",None)
assert f("F25",0)[0] is None
assert w.pretty_hotkey("ctrl+shift+f7")=="Ctrl+Shift+F7"
r=tk.Tk(); v=tk.StringVar(value="f9")
used={"f8"}
e=w.HotkeyEntry(r,v,"f9",validate=lambda s:"dup" if s in used else None); e.pack(); r.update()
assert e.display.get()=="F9"
e._start(); assert e.capturing and "Press" in e.display.get()
class Ev:  # fake event
    def __init__(s,k,st=0): s.keysym,s.state=k,st
e._key(Ev("F8")); assert v.get()=="f9" and e.capturing   # refused
e._key(Ev("F6",0x4)); assert v.get()=="ctrl+f6" and not e.capturing
e._start(); e._key(Ev("Escape")); assert v.get()=="ctrl+f6" and not e.capturing
e._start(); e._key(Ev("BackSpace")); assert v.get()=="f9"
e._start(); e._key(Ev("q")); assert v.get()=="f9" and e.capturing
e.state(["disabled"]); e._stop(); assert e._start()=="break" and not e.capturing
print("widget ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
