import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, os, tempfile, json, queue, datetime as dt
from unittest.mock import MagicMock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"): sys.modules[m]=MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telestep_recorder as sr, telestep_settings as cfg, telestep_model as tm
ok=bad=0
def check(n,c,x=""):
    global ok,bad
    if c: ok+=1
    else: bad+=1; print("FAIL",n,x)
R=sr.Recorder.__new__(sr.Recorder)
R._pending_comment=""; R._stages={}; R._flush_typing=lambda:None
R.q=queue.Queue(); R.session=tm.Session(tempfile.mkdtemp(),"t"); R.o=MagicMock(key_mode="count"); R._last_pw=False
R._stage=lambda n: __import__("contextlib").nullcontext()
sr.core.app_info=lambda pid:{}
R.add_comment("Wait for the page"); kind,when,text=R.q.get(); check("queued", kind=="comment" and text=="Wait for the page")
R._do_comment(None,when,text); R._do_comment(None,when,"then scroll")
R._do_note(None,dt.datetime.now(),"a note","note"); check("note doesn't take the comment", R._pending_comment=="Wait for the page then scroll" and R.session.steps[-1].comment=="")
R._do_type(None,dt.datetime.now(),"abc",3); st=R.session.steps[-1]
check("next step gets the comment", st.comment=="Wait for the page then scroll", st.comment); check("then cleared", R._pending_comment=="")
R._do_type(None,dt.datetime.now(),"abc",3); check("only once", R.session.steps[-1].comment=="")
check("hotkey default", cfg.DEFAULT_HOTKEYS["comment"]=="ctrl+shift+f5")
# portable
d=tempfile.mkdtemp(); cfg.app_dir=lambda:__import__("pathlib").Path(d)
for k in ("TELESTEP_PORTABLE","APPDATA"): os.environ.pop(k,None)
check("not portable by default", not cfg.portable())
os.environ["APPDATA"]=os.path.join(d,"roam"); check("appdata path", str(cfg.settings_path()).startswith(os.path.join(d,"roam")))
open(os.path.join(d,"portable.txt"),"w").write("")
check("portable via marker", cfg.portable() and cfg.settings_path()==__import__("pathlib").Path(d)/"settings.json")
s=cfg.load(); check("portable recordings next to program", s["base_dir"]==str(__import__("pathlib").Path(d)/"Recordings"), s["base_dir"])
s["base_dir"]="X:\\mine"; cfg.save(s); check("chosen folder wins", cfg.load()["base_dir"]=="X:\\mine")
check("update default off", cfg.load()["update_check"] is False)
check("presets skip network + per-machine keys", "update_check" not in cfg.PRESET_KEYS and "update_last" not in cfg.PRESET_KEYS)
check("old settings get new ocr/format keys", cfg.merge(cfg.DEFAULTS,{"ocr":{"ip":True},"formats":{"md":False}})["ocr"]["card"] is False and "zip" in cfg.merge(cfg.DEFAULTS,{"formats":{"md":False}})["formats"])
os.remove(os.path.join(d,"portable.txt")); os.remove(os.path.join(d,"settings.json")); check("back to normal", not cfg.portable())
print(ok,"passed,",bad,"failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
