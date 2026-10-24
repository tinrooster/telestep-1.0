import os, tempfile
SHOTARGS = [os.path.join(tempfile.gettempdir(), 'telestep_shot_%d.png' % i) for i in range(4)]
import sys as _s; _s.argv = [_s.argv[0]] + SHOTARGS
import sys
from unittest import mock
for m in ("pynput","pynput.mouse","pynput.keyboard","mss","uiautomation"): sys.modules[m]=mock.MagicMock()
sys.argv = [sys.argv[0]] + SHOTARGS
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image
import telestep_core as core
assert core.canon_style("hatch")=="soft" and core.canon_style("frosted")=="blur" and core.canon_style("zzz")=="solid" and core.canon_style("blur_heavy")=="blur_heavy"
assert core.Mask.from_dict({"rect":[0,0,5,5],"style":"hatch"}).style=="soft"
im=Image.new("RGB",(100,60),(200,10,10)); core.apply_mask(im,(10,10,90,50),"frosted","x"); core.apply_mask(im,(10,10,90,50),"hatch","x"); core.apply_mask(im,(0,0,3,3),"blur_heavy"); core.apply_mask(im,(0,0,1,1),"pixelate_fine")
assert core.apply_mask(im,(500,500,600,600),"blur") is None
import telestep_recorder as sr
assert sr._split_style("name:frosted","solid")==("name","blur")
print("legacy ok")
if 'ok' in globals(): sys.exit(1 if bad else 0)
