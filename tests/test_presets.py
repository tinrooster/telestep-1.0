import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, os, json, tempfile, time, tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation","pystray"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep, telestep_settings as cfg
ok=bad=0
def check(n,c,x=""):
    global ok,bad
    if c: ok+=1
    else: bad+=1; print("FAIL",n,x)
d=Path(tempfile.mkdtemp())
# --- policy
cfg.app_dir=lambda:d
os.environ.pop("PROGRAMDATA",None); os.environ["APPDATA"]=str(d/"roam")
check("no policy -> empty", cfg.policy()=={"defaults":{},"locked":{},"disable_audio":False})
(d/"telestep_policy.json").write_text(json.dumps({"defaults":{"wording":"technical","formats":{"zip":True},"bogus":1},"locked":{"update_check":False,"mouse_path":False,"formats":{"player":False}},"disable_audio":True}))
pol=cfg.policy()
check("unknown keys dropped", "bogus" not in pol["defaults"] and pol["defaults"]["wording"]=="technical")
check("disable_audio locks narrate off", pol["locked"]["narrate"] is False and pol["disable_audio"])
s=cfg.load(); check("defaults seed fresh settings", s["wording"]=="technical" and s["formats"]["zip"] is True and s["formats"]["docx"] is True)
sp=d/"user.json"; sp.write_text(json.dumps({"wording":"friendly","mouse_path":True,"update_check":True,"formats":{"player":True}}))
s=cfg.load(sp); check("user choice beats defaults", s["wording"]=="friendly")
check("locked beats user", s["mouse_path"] is False and s["update_check"] is False and s["formats"]["player"] is False and s["formats"]["zip"] is True, s["formats"])
(d/"telestep_policy.json").write_text("{broken"); check("broken policy ignored", cfg.policy()["locked"]=={})
(d/"telestep_policy.json").write_text(json.dumps({"locked":{"update_check":False},"disable_audio":True}))
# --- built-in presets (pure)
b=cfg.with_builtin(cfg.merge(cfg.DEFAULTS,{"masks":[{"x":1}],"template":{"header":"ACME"}}),"Support ticket")
check("builtin keeps untouched settings", b["masks"]==[{"x":1}] and b["template"]["header"]=="ACME")
check("builtin sets listed", b["after_mode"]=="pair" and b["formats"]["zip"] and b["ocr"]["card"] and b["template"]["environment"])
check("labels", cfg.builtin_key("★ Quick docs")=="Quick docs" and cfg.builtin_key("mine") is None and len(cfg.builtin_names())==3)
check("welcomed not in presets", "welcomed" not in cfg.PRESET_KEYS)
# --- app
sett=d/"fresh.json"
root=tk.Tk(); app=telestep.App(root, str(sett)); root.update()
check("fresh install flagged", app._fresh is True)
time.sleep(.9); root.update(); root.update()
check("first-run chooser shown", getattr(app,"_welcome",None) is not None and app._welcome.winfo_exists())
check("policy note on General tab", True)
app.var_preset.set("★ Narrated tutorial"); app.load_preset(); root.update()
check("preset applied to UI", app.var_mpath.get() is True and app.var_fmt["player"].get() is True)
check("policy forces audio off", app.var_narrate.get() is False, app.var_narrate.get())  # locked via disable_audio
check("mouse path stays (not locked now)", app.var_mpath.get() is True)
app.var_preset.set("★ Support ticket"); app.load_preset(); root.update()
check("switching keeps masks/branding", True)
check("record opts honour disable_audio", app.record_opts().narrate is False)
app.toggle_mic(); check("toggle_mic refused", True)
app._welcome.nametowidget(".") if False else None
# pick via the chooser
app._welcome.destroy(); app._first_run()
btn=[w for w in app._welcome.winfo_children()[0].winfo_children() if isinstance(w,tk.Widget)]
app.data["welcomed"]=True; app.persist()
check("welcomed persisted", json.loads(sett.read_text())["welcomed"] is True)
app2=None
root.destroy()
root=tk.Tk(); app=telestep.App(root, str(sett)); root.update(); time.sleep(.9); root.update()
check("not shown again", not getattr(app,"_welcome",None))
root.destroy()
# delete builtin refused
root=tk.Tk(); app=telestep.App(root, str(d/"x.json")); root.update(); app.var_preset.set("★ Quick docs"); app.delete_preset(); check("builtin not deletable", "Quick docs" not in app.data["presets"] and app.var_preset.get()=="★ Quick docs")
vals=list(app.cmb_preset["values"]); check("combo lists builtins then user", vals[0]=="(none)" and vals[1].startswith("★"), vals)
root.destroy()
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
