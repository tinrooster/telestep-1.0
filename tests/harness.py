"""Shared setup for the Telestep tests: stubs the Windows-only libraries and builds fake recordings.
Run everything with:  python tests/run_tests.py   (Linux needs a virtual display, e.g. xvfb-run)."""
import sys, os, tempfile, zipfile, queue, threading, time, json, random
from unittest import mock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"):
    sys.modules[m]=mock.MagicMock()
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,os.path.dirname(HERE))
tmpout=os.path.join(tempfile.mkdtemp(),"shot.png")
sys.argv=[sys.argv[0],__file__,tmpout]
import tkinter as tk
from pathlib import Path
from PIL import Image
import numpy as np
import telestep_support as sp
from telestep_model import Session, Step, new_id, collect_environment

ok=0; bad=0
def check(name, cond, extra=""):
    global ok,bad
    if cond: ok+=1
    else: bad+=1; print("FAIL:", name, extra)

tmp=Path(tempfile.mkdtemp())
def make_session(n=12, big=True):
    s=Session(tmp/f"s{random.randint(0,99999)}", "Support recording"); s.make_dirs()
    s.environment=collect_environment(); s.host="TEST-PC"
    rng=np.random.default_rng(1)
    for i in range(n):
        st=Step(new_id(),"click",f"14:0{i%10}:00",f'Click "Btn{i}"',f'Left click on "Btn{i}" (Button)',window="Win",app="app.exe",app_version="1.2")
        arr=(rng.random((1080,1920,3))*255).astype("uint8") if big else np.full((1080,1920,3),90,"uint8")
        Image.fromarray(arr).save(s.dir/"raw"/f"{st.id}.jpg","JPEG",quality=90)
        st.raw=f"raw/{st.id}.jpg"; st.marker={"x":500,"y":400,"kind":"click"} if False else None
        if i==3: st.dialog_text="Error 0x80070005\nAccess denied"; st.kind="dialog"
        s.add(st,autosave=False)
    n=Step(new_id(),"note","14:09:00","","",level="warning"); n.friendly=n.tech="It freezes here"; s.add(n,autosave=False)
    s.save(); return s

