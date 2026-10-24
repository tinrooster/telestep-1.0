import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, os, tempfile, queue, datetime as dt
from unittest import mock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"):
    sys.modules[m]=mock.MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import telestep_core as core, telestep_model as M, telestep_recorder as sr
ok=bad=0
def check(n,c,x=""):
    global ok,bad
    if c: ok+=1
    else: bad+=1; print("FAIL",n,x)
W=lambda t,l,tp,r,b:(t,l,tp,r,b)
# pick_label (pure)
words=[W("File",10,10,40,25),W("Edit",70,10,100,25),W("View",130,10,165,25),W("Save",300,100,335,115),W("as",340,100,355,115),W("Cancel",300,200,360,215),W("x",5,5,9,9)]
check("single menu word", core.pick_label(words,85,17)=="Edit", core.pick_label(words,85,17))
check("joins normal spacing", core.pick_label(words,320,108)=="Save as", core.pick_label(words,320,108))
check("near but not on", core.pick_label(words,300,140)=="Save as" or core.pick_label(words,300,140)=="" , "")
check("too far -> empty", core.pick_label(words,600,600)=="")
check("junk ignored", core.pick_label([W("|",10,10,12,25),W("x",20,10,25,25)],15,15)=="")
check("max chars", len(core.pick_label([W("w"*60,0,0,300,20)],10,10))<=40)
# wording
f,t=M.click_texts("click",{"name":"","kind":"Pane","button":"left","x":5,"y":6,"near":"Settings"})
check("no-name near", f=='Click near "Settings"' and 'near text "Settings"' in t, (f,t))
f,t=M.click_texts("click",{"name":"Message 73 of 74","kind":"Group","button":"left","x":5,"y":6,"near":"Rename"})
check("container near", f.endswith('near "Rename"') and t=='Left click on "Message 73 of 74" (Group) near text "Rename"', (f,t))
f,t=M.click_texts("click",{"name":"","kind":"","button":"left","x":5,"y":6})
check("no near unchanged", t=="Left click at (5, 6)" and "near" not in f, (f,t))
f,t=M.click_texts("dblclick",{"name":"Save","kind":"Button","button":"left","x":1,"y":1})
check("named button unchanged", f=='Double-click the "Save" button', f)
# real OCR if available
if core.ocr_available():
    img=Image.new("RGB",(900,400),(30,30,34)); d=ImageDraw.Draw(img)
    fnt=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",22)
    d.rectangle([380,180,560,230],fill=(60,60,70)); d.text((400,190),"Settings",font=fnt,fill="white")
    d.text((100,60),"Printer offline",font=fnt,fill="white")
    lab=core.ocr_label_near(img,470,205); print("real OCR label:",repr(lab))
    check("real OCR finds Settings", "Settings" in lab, lab)
    lab2=core.ocr_label_near(img,40,350); check("real OCR empty far away", lab2=="" , lab2)
else:
    print("tesseract not installed here - OCR call itself not exercised")
# recorder integration with a stubbed OCR
tmp=Path(tempfile.mkdtemp())
rec=sr.Recorder(tmp/"s", sr.CaptureOpts(), sr.RecordOpts())
rec._describe=lambda auto,x,y,pid=None:("", "Pane", None, False, False)
core.ocr_label_near=lambda img,x,y,**k: "Settings"
img=Image.new("RGB",(800,600),(50,50,50))
rec._do_click(None, dt.datetime.now(), 400,300,"left",img,{"left":0,"top":0,"width":800,"height":600},{"title":"App"},None)
st=rec.session.steps[-1]; check("recorder uses near", st.el.get("near")=="Settings" and 'near "Settings"' in st.friendly, (st.el,st.friendly))
# password field -> no OCR
rec._describe=lambda auto,x,y,pid=None:("", "Edit", None, True, False)
rec._do_click(None, dt.datetime.now(), 400,300,"left",img,{"left":0,"top":0,"width":800,"height":600},{"title":"App"},None)
check("password skips OCR", "near" not in rec.session.steps[-1].el)
# named button -> no OCR
rec._describe=lambda auto,x,y,pid=None:("Save","Button",None,False,False)
rec._do_click(None, dt.datetime.now(), 400,300,"left",img,{"left":0,"top":0,"width":800,"height":600},{"title":"App"},None)
check("named button skips OCR", "near" not in rec.session.steps[-1].el)
# Tesseract missing -> silently disabled after first try
def boom(img,x,y,**k): raise core.OcrUnavailable("none")
core.ocr_label_near=boom; rec._ocr_ok=None; rec._describe=lambda auto,x,y,pid=None:("", "Pane", None, False, False)
rec._do_click(None, dt.datetime.now(), 400,300,"left",img,{"left":0,"top":0,"width":800,"height":600},{"title":"App"},None)
check("missing tesseract tolerated", rec._ocr_ok is False and "near" not in rec.session.steps[-1].el)
# option off
rec2=sr.Recorder(tmp/"s2", sr.CaptureOpts(), sr.RecordOpts(ocr_labels=False)); rec2._describe=rec._describe; core.ocr_label_near=lambda i,x,y,**k:"X"
rec2._do_click(None, dt.datetime.now(), 400,300,"left",img,{"left":0,"top":0,"width":800,"height":600},{"title":"App"},None)
check("option off", "near" not in rec2.session.steps[-1].el)
print(f"{ok} passed, {bad} failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
