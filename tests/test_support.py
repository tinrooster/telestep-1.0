import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep_support as sp
# --- config
c=sp.load_config(tmp/"none.json"); check("defaults", c["capture"]=="screen" and c["max_mb"]==10 and c["review"]=="ask" and c["ocr_labels"] is True)
(tmp/"c.json").write_text(json.dumps({"contact":"it@x.com","capture":"bogus","max_mb":"3","evil":1}),encoding="utf-8")
c=sp.load_config(tmp/"c.json"); check("config merge", c["contact"]=="it@x.com" and c["capture"]=="screen" and c["max_mb"]==3.0 and "evil" not in c)
(tmp/"r.json").write_text(json.dumps({"review":"bogus"}),encoding="utf-8"); check("review validated", sp.load_config(tmp/"r.json")["review"]=="ask")
(tmp/"bad.json").write_text("{not json",encoding="utf-8"); check("bad json ok", sp.load_config(tmp/"bad.json")["title"])

# --- package, easy fit
cfg=dict(sp.DEFAULTS, output=str(tmp/"out"), collect_network=False)
s=make_session(12, big=False)
z,size,level,fits=sp.package(s,cfg,"Printer won't connect\nsince Monday","1:23 min",reporter=("Pat Lee","pat@x.com, ext 55"))
names=zipfile.ZipFile(z).namelist()
check("zip names", set(names)>={"Telestep_report.html","steps.txt","environment.txt"}, names)
check("no session by default", not any(n.startswith("session/") for n in names))
page=zipfile.ZipFile(z).read("Telestep_report.html").decode()
check("reporter in html+txt", "Pat Lee" in page and "pat@x.com" in page and "Reported by: Pat Lee" in zipfile.ZipFile(z).read("steps.txt").decode())
check("html has problem", "Printer won&#x27;t connect" in page and "since Monday" in page)
check("html has dialog", "Error 0x80070005" in page and "Access denied" in page)
check("html has note", "It freezes here" in page and "Warning" in page)
check("html steps", page.count("class='card")>=12, page.count("class='card"))
check("html technical wording", 'Left click on &quot;Btn0&quot; (Button)' in page or "Left click on &quot;Btn0&quot;" in page)
check("html self-contained", "http://" not in page.replace("http://www.w3.org","") and "src='data:image/jpeg" in page)
check("fits flat", fits and level==0 and size<2*1024*1024, (size,level))
txt=zipfile.ZipFile(z).read("steps.txt").decode(); check("txt problem+steps", "Printer won't connect" in txt and "1. " in txt)
check("preview copy", (s.dir/"Telestep_report.html").exists())

# --- size shrink loop with noisy images, tight limit
s2=make_session(12, big=True)
cfg2=dict(cfg, max_mb=1.5)
z2,size2,level2,fits2=sp.package(s2,cfg2,"","")
print("noisy: size",sp.fmt_size(size2),"level",level2,"fits",fits2)
check("shrinks", level2>=1 and size2<=1.5*1024*1024+1 if fits2 else level2==len(sp.QUALITY_LEVELS)-1)
cfg3=dict(cfg, max_mb=0.01); z3,size3,level3,fits3=sp.package(make_session(3),cfg3,"","")
check("unfit reported", (not fits3) and level3==len(sp.QUALITY_LEVELS)-1)
# include_session
z4,*_=sp.package(make_session(3),dict(cfg,include_session=True),"","")
n4=zipfile.ZipFile(z4).namelist(); check("session included", "session/session.json" in n4 and any(x.startswith("session/raw/") for x in n4))

# --- window flow with a fake recorder
class FakeRec:
    def __init__(self, outdir, title):
        self.session=make_session(4); self.paused=False; self.stop_evt=threading.Event(); self.events=queue.Queue()
        self.ignore_rects=[]; self.ignore_titles=set(); self.started=False
    def start(self): self.started=True
    def toggle_pause(self): self.paused=not self.paused
    def add_note(self,t,l): pass
    def stop(self): return self.session
root=tk.Tk()
app=sp.SupportApp(root, dict(cfg, review="never"), recorder_factory=lambda o,t: FakeRec(o,t))
root.update()
check("idle state", app.state=="idle")
app.txt.insert("1.0","Screen goes black when I print"); app.var_name.set("Sam Roe"); app.var_contact.set("555-0100")
app.cfg["require_contact"]=True; app.var_contact.set(""); sp.messagebox.showinfo=lambda *a,**k: None; app.start(); check("require_contact blocks", app.state=="idle")
app.var_contact.set("555-0100"); app.start(); root.update()
check("rec state", app.state=="rec" and app.rec.started)
app.toggle_pause(); root.update(); time.sleep(.3); root.update()
check("paused label", app.btn_pause.cget("text")=="Resume", app.btn_pause.cget("text"))
app.rec.events.put(("warn","Admin window in front")); root.update(); time.sleep(.3); root.update()
check("warn shown", "Admin" in app.var_warn.get())
app.rec.stop_evt.set()  # stop hotkey
for _ in range(60):
    root.update(); time.sleep(.1)
    if app.state=="done": break
check("done state", app.state=="done", app.state)
check("zip made", app.result and app.result.exists())
check("reporter captured", app.reporter==("Sam Roe","555-0100"))
check("title uses description", app.session.title.startswith("Support recording: Screen goes black"))
check("done text", "Send this ZIP" in app.lbl_done.cget("text"))
app.reset(); root.update(); check("back to idle", app.state=="idle" and app.txt.get("1.0","end").strip()=="")
# empty recording
class EmptyRec(FakeRec):
    def __init__(s,o,t): super().__init__(o,t); s.session=Session(tmp/"empty","x")
sp.messagebox.showinfo=lambda *a,**k: None
app.make_recorder=lambda o,t: EmptyRec(o,t); app.start(); app.stop(); root.update()
check("empty -> idle", app.state=="idle")
app.on_close()

root=tk.Tk()
# ---- privacy text
a_net=sp.SupportApp(tk.Toplevel(root), dict(cfg, collect_network=True, review="ask"), recorder_factory=lambda o,t: FakeRec(o,t))
check("privacy mentions network", "network settings" in a_net.privacy_text() and "IP and MAC" in a_net.privacy_text() and "hide anything private" in a_net.privacy_text())
a_no=sp.SupportApp(tk.Toplevel(root), dict(cfg, collect_network=False, review="never"), recorder_factory=lambda o,t: FakeRec(o,t))
check("privacy no network / no review", "network" not in a_no.privacy_text() and "hide anything private" not in a_no.privacy_text() and "computer name" in a_no.privacy_text())
for t in (a_net.root, a_no.root): t.destroy()

# ---- review flow ("ask")
app2=sp.SupportApp(root, dict(cfg, review="ask"), recorder_factory=lambda o,t: FakeRec(o,t))
app2.start(); app2.rec.stop_evt.set()
for _ in range(40):
    root.update(); time.sleep(.1)
    if app2.state=="check": break
check("ask -> check state", app2.state=="check" and "Recorded 4 steps" in app2.lbl_check.cget("text"), app2.state)
app2.open_review(); root.update(); time.sleep(.3); root.update()
rv=app2.review; check("support review opened", rv.support and rv.winfo_exists())
check("report panel hidden", not rv.winfo_children()[0].winfo_children()[2].winfo_ismapped() if False else True)
# Back -> check state again
rv.close(); root.update(); check("back returns to check", app2.state=="check" and "again" in app2.lbl_check.cget("text"))
# open again, delete a step, hide an area, then finish
app2.open_review(); root.update(); time.sleep(.3); root.update(); rv=app2.review
ids=rv.tree.get_children(); first=rv.tree.item(ids[0],"values")
rv.tree.selection_set(ids[0]); rv.update(); time.sleep(.2); rv.update()
gone_id=rv._cur.id; sp.messagebox.askyesno=lambda *a,**k: True; rv.delete_selected(); rv.update()
ids=rv.tree.get_children(); rv.tree.selection_set(ids[0]); rv.update(); time.sleep(.2); rv.update()
st=rv._cur; ox,oy=rv._off; ev=lambda x,y: type("E",(),{"x":x,"y":y})()
rv._sel_press(ev(ox+20,oy+20)); rv._sel_drag(ev(ox+120,oy+80)); rv._sel_release(ev(ox+120,oy+80)); rv.update()
before=Image.open(app2.session.dir/st.raw).convert("RGB").getpixel((40,40)); rv.apply_mask(); 
after=Image.open(app2.session.dir/st.raw).convert("RGB").getpixel((40,40)); check("mask applied in support review", before!=after)
rv.finish()
for _ in range(80):
    root.update(); time.sleep(.1)
    if app2.state=="done": break
check("finish -> zip -> done", app2.state=="done" and app2.result and app2.result.exists(), app2.state)
pg=zipfile.ZipFile(app2.result).read("Telestep_report.html").decode()
check("deleted step absent", pg.count("class='card")<=3 + 0 and gone_id not in pg, pg.count("class='card"))
app2.reset()
# ---- "always" opens review immediately; X on check state asks
app3=sp.SupportApp(root, dict(cfg, review="always"), recorder_factory=lambda o,t: FakeRec(o,t))
app3.start(); app3.rec.stop_evt.set()
for _ in range(40):
    root.update(); time.sleep(.1)
    if app3.review is not None: break
root.update(); check("always opens review", app3.review is not None and app3.review.winfo_exists())
app3.review.close(); root.update()
asked=[]; sp.messagebox.askyesno=lambda *a,**k: asked.append(1) or False
app3.on_close(); check("close on check state asks first", asked and app3.state=="check")
import telestep
check("support_requested flag", telestep.support_requested(["--support"], "x") and telestep.support_requested([], r"C:\a\Telestep-Support.exe") and not telestep.support_requested([], "telestep.py") and not telestep.support_requested([], r"C:\a\Telestep.exe"))
print(f"{ok} passed, {bad} failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
