import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys, time
from unittest import mock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"): sys.modules[m]=mock.MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw, ImageFont
import telestep_core as core
F=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",15)
img=Image.new("RGB",(5760,1080),(250,250,250)); d=ImageDraw.Draw(img)
for m in range(3):
    for i in range(40):
        d.text((m*1920+30+(i%3)*600, 30+i*25),f"Router Input Distribution Amp 10.0.{m}.{i} user{i}@example.com status ok",fill=(20,20,20),font=F)
t=time.time(); a=core.ocr_words(img); t1=time.time()-t
t=time.time(); b=core.ocr_words_tiled(img); t2=time.time()-t
ip=lambda ws:sum(1 for w in ws if w[0].startswith("10.0."))
em=lambda ws:sum(1 for w in ws if "@example" in w[0])
print(f"whole {t1:.1f}s words {len(a)} ip {ip(a)} em {em(a)} | tiled {t2:.1f}s words {len(b)} ip {ip(b)} em {em(b)}")
assert ip(b)>=ip(a)*0.9 and em(b)>=em(a)*0.9
# duplicates from overlap
assert len(b)<=len(a)*1.1
# label on dark UI
dk=Image.new("RGB",(800,300),(20,24,30)); dd=ImageDraw.Draw(dk)
G=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",13)
dd.text((300,140),"Auto fill off",fill=(220,225,230),font=G)
lab=core.ocr_label_near(dk,330,147); print("dark label:",repr(lab)); assert "fill" in lab.lower() or "auto" in lab.lower()
for txt,exp in [("ey ne mart War",False),("Gana",True),("ay",False),("Inventory",True),("om",False),("Save as",True),("10.0.1.5",False),("em one oe",True),("",False),("Receiving",True)]:
    r=core.plausible_label(txt); print(repr(txt),r)
print("done")
if 'ok' in globals(): sys.exit(1 if bad else 0)
