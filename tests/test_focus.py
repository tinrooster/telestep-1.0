import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_report as rep, telestep_core as core
from PIL import Image, ImageDraw, ImageChops
# a screenshot with fine detail so blur is measurable
s=make_session(3,big=True)
st=s.steps[0]
W,H=1920,1080
st.marker={"shape":"click","pt":[800,500],"rect":[700,450,900,550],"win":[500,300,1300,800]}
# base images
raw=Image.open(s.dir/st.raw).convert("RGB")
def region_diff(a,b,box): return ImageChops.difference(a.crop(box),b.crop(box)).getbbox() is not None
def sharp_same(a,b,box): return ImageChops.difference(a.crop(box),b.crop(box)).getbbox() is None
off=rep.render_step_image(s,st,1,"off"); win=rep.render_step_image(s,st,1,"window"); ctl=rep.render_step_image(s,st,1,"control")
# outside the window: changed; inside window (away from marker): identical to unblurred
check("window: outside blurred", region_diff(off,win,(0,0,400,200)))
check("window: inside sharp", sharp_same(off,win,(560,360,640,420)))   # clear of the click marker
check("control: outside blurred", region_diff(off,ctl,(0,0,400,200)) and region_diff(off,ctl,(1000,600,1200,700)))
check("control: control area sharp", sharp_same(off,ctl,(670,430,690,445)))
check("control: wider window blurred", region_diff(off,ctl,(520,320,600,380)))
check("raw file untouched", ImageChops.difference(raw,Image.open(s.dir/st.raw).convert("RGB")).getbbox() is None)
# fallbacks
st2=s.steps[1]; st2.marker={"shape":"click","pt":[800,500],"rect":None}
check("window mode, no win recorded -> unchanged", rep.render_step_image(s,st2,2,"window").tobytes()==rep.render_step_image(s,st2,2,"off").tobytes())
c2=rep.render_step_image(s,st2,2,"control"); check("control w/o rect -> patch around click", region_diff(rep.render_step_image(s,st2,2,"off"),c2,(0,0,300,200)))
st3=s.steps[2]; st3.marker={"shape":"click","pt":[800,500],"rect":None,"win":[0,0,1900,1070]}
check("window ~ whole screen -> unchanged", rep.render_step_image(s,st3,3,"window").tobytes()==rep.render_step_image(s,st3,3,"off").tobytes())
st3.marker["rect"]=[0,0,1800,1000]; c3=rep.render_step_image(s,st3,3,"control"); check("huge control -> click patch", region_diff(rep.render_step_image(s,st3,3,"off"),c3,(0,0,300,200)))
# template round trip + export uses it
t=rep.Template.from_settings({"template":{"focus":"window"}}); check("template focus", t.focus=="window")
check("bad focus -> off", rep.Template.from_settings({"template":{"focus":"zzz"}}).focus=="off")
out=rep.export(s,rep.Template(focus="window"),["md"]); check("export ok", not out["md"].startswith("FAILED"))
img=Image.open(s.dir/st.image).convert("RGB"); check("exported image has blur", region_diff(off.resize(img.size),img,(0,0,200,100)))
# support config
import telestep_support as sp
import json
(tmp/"f.json").write_text(json.dumps({"focus":"control"}),encoding="utf-8"); check("support focus", sp.load_config(tmp/"f.json")["focus"]=="control")
(tmp/"f2.json").write_text(json.dumps({"focus":"bogus"}),encoding="utf-8"); check("support bad focus", sp.load_config(tmp/"f2.json")["focus"]=="off")
cfgd=dict(sp.DEFAULTS, output=str(tmp/"o2"), collect_network=False, focus="window")
r=sp.package(s,cfgd); print("package ok", bool(r))
# visual
win.save(sys.argv[2]+"_win.jpg"); ctl.save(sys.argv[2]+"_ctl.jpg")
print(f"{ok} passed, {bad} failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
