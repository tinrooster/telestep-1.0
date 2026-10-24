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
def mk():
    img=Image.new("RGB",(5760,1080),(250,250,250)); d=ImageDraw.Draw(img)
    for m in range(3):
        for i in range(30):
            d.text((m*1920+30, 30+i*30),f"Router Input Amp 10.0.{m}.{i} user{i}@example.com ok",fill=(20,20,20),font=F)
    return img
calls=[0]; real=core.ocr_words
def counting(img,*a,**k): calls[0]+=1; return real(img,*a,**k)
core.ocr_words=counting
cache={}
img=mk()
t=time.time(); w1=core.ocr_words_tiled(img,cache=cache); print("first",calls[0],f"{time.time()-t:.1f}s",len(w1)); n1=calls[0]; assert n1>=3
calls[0]=0; t=time.time(); w2=core.ocr_words_tiled(mk(),cache=cache); print("identical",calls[0],f"{time.time()-t:.1f}s"); assert calls[0]==0 and len(w2)==len(w1)
im2=mk(); ImageDraw.Draw(im2).rectangle([500,500,501,515],fill=(0,0,0))  # caret-sized change
calls[0]=0; core.ocr_words_tiled(im2,cache=cache); print("caret",calls[0]); assert calls[0]==0
im3=mk(); ImageDraw.Draw(im3).text((2100,1000),"secret admin@corp.com",fill=(0,0,0),font=F)  # new text on monitor 2
calls[0]=0; w3=core.ocr_words_tiled(im3,cache=cache); print("new text",calls[0]); assert 1<=calls[0]<=2
assert any("admin@corp" in w[0] for w in w3)
# redact path uses cache and masks the new email
im4=mk(); ImageDraw.Draw(im4).text((4000,1000),"leak bob@x.org",fill=(0,0,0),font=F)
calls[0]=0; n=core.ocr_redact(im4,["email"],"solid",cache=cache); print("redact",calls[0],n); assert n>=1
print("cache ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
