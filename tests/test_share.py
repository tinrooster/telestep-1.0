import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import zipfile
import telestep_report as rep
s = make_session(4, big=False)
s.steps[0].audio = "audio/a.wav"; (s.dir / "audio").mkdir(exist_ok=True); (s.dir / "audio" / "a.wav").write_bytes(b"RIFFxxxx")
(s.dir / "audio" / "narration.wav").write_bytes(b"RIFFfull")
try:
    rep.write_share_copy(s, tmp / "x.zip"); check("needs export first", False)
except ValueError:
    check("needs export first", True)
out = rep.export(s, rep.Template(style="onesheet"), ["html", "md"])
z = rep.write_share_copy(s, tmp / "share.zip")
names = zipfile.ZipFile(z).namelist()
check("exports included", any(n.endswith(".html") for n in names) and any(n.startswith("images/") for n in names), names)
check("no originals/session", not any(n.startswith("raw/") or n == "session.json" or "narration" in n for n in names), names)
check("voice note included", "audio/a.wav" in names, names)
check("voice optional", "audio/a.wav" not in zipfile.ZipFile(rep.write_share_copy(s, tmp / "s2.zip", include_audio=False)).namelist())
n = rep.delete_originals(s)
check("originals deleted", n >= 4 and not any((s.dir / "raw").iterdir()) and not (s.dir / "audio" / "narration.wav").exists() and (s.dir / "audio" / "a.wav").exists(), n)
check("flag saved", s.settings.get("originals_removed"))
out2 = rep.export(s, rep.Template(style="onesheet"), ["html"])
imgs = list((s.dir / "images").glob("*.jpg"))
check("re-export keeps pictures", out2 and len(imgs) >= 3, imgs)
print(f"{ok} passed, {bad} failed"); sys.exit(1 if bad else 0)
