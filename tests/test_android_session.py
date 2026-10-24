import os, sys, json, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# A recording made by the Android app (android/core writes it; fixtures/android_session is one it wrote) must open in
# the desktop editor and export to every format.  Regenerate the fixture with:
#   cd android && ./gradlew :core:test -PcoreOnly=true -PsampleOut=../tests/fixtures/android_session
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1
    else: bad += 1; print("FAIL:", name, extra)

from pathlib import Path
from PIL import Image
import telestep_report as rep
from telestep_model import Session

src = Path(__file__).parent / "fixtures" / "android_session"
d = Path(tempfile.mkdtemp()) / "20261024_140509"
shutil.copytree(src, d)
data = json.loads((d / "session.json").read_text(encoding="utf-8"))
for st in data["steps"]:  # the fixture's pictures are placeholders: put a real phone-sized screenshot in their place
    for key in ("raw", "raw_after"):
        if st.get(key):
            (d / st[key]).parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (540, 1200), (230, 236, 245)).save(d / st[key], "JPEG")

s = Session.load(d)
check("loads", len(s.steps) == 5 and s.steps[0].kind == "click", [x.kind for x in s.steps])
check("captions kept", s.steps[0].caption() == 'Select "Wi-Fi"' and s.steps[0].caption("technical").startswith("Tap on"))
check("app and screen", s.steps[0].app == "Settings" and s.steps[0].window == "Network & internet")
check("marker in picture pixels", s.steps[0].marker["pt"] == [270.0, 130.0] and s.steps[0].geom["scale"] == 0.5)
check("dialog text", "Saved password will be removed" in s.steps[-1].dialog_text)
check("numbering", s.count() == 5)
tpl = rep.Template()
res = rep.export(s, tpl, ["md", "docx", "html", "pdf", "txt", "player"])
failed = {k: v for k, v in res.items() if str(v).startswith("FAILED")}
check("every format exports", not failed, failed)
md = Path(res["md"]).read_text(encoding="utf-8")
check("markdown has steps and pictures", 'Select "Wi-Fi"' in md and "images/" in md, md[:300])
s2 = Session.load(d)
check("re-saved by the desktop still loads", len(s2.steps) == 5)
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
