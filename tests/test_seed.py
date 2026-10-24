import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
for m in ("pystray",): sys.modules[m]=mock.MagicMock()
import telestep, telestep_review as tr
root=tk.Tk(); app=telestep.App(root, settings_path=os.path.join(tempfile.mkdtemp(),"s.json"))
app.var_header.set("ACME Corp"); app.var_footer.set("Confidential"); app.var_author.set("A. Hay")
s=make_session(3,big=False); s.settings={"wording":"friendly"}
win=app.open_review(s); win.update()
check("header seeded", win.var_header.get()=="ACME Corp", win.var_header.get())
check("footer seeded", win.var_footer.get()=="Confidential"); check("author seeded", win.var_author.get()=="A. Hay")
win.destroy()
# session with its own saved template is left alone
s2=make_session(3,big=False); s2.settings={"wording":"friendly","template":{"header":"Mine","footer":"","logo":"","author":""}}
win2=app.open_review(s2); win2.update(); check("saved template kept", win2.var_header.get()=="Mine" and win2.var_footer.get()=="")
# default size shows the picture
win2.tree.selection_set(win2.tree.get_children()[0]); win2.update(); time.sleep(.2); win2.update()
print("window", win2.winfo_width(), win2.winfo_height(), "canvas", win2.cv.winfo_width(), win2.cv.winfo_height(), "req", win2.winfo_reqwidth(), win2.winfo_reqheight())
check("preview visible by default", win2.cv.winfo_height()>=250, win2.cv.winfo_height())
# squeezed -> message
win2.geometry("1000x560"); win2.update(); time.sleep(.2); win2.update(); win2.show_preview(); win2.update()
txt=[win2.cv.itemcget(i,"text") for i in win2.cv.find_all() if win2.cv.type(i)=="text"]
print("canvas h", win2.cv.winfo_height(), txt[:1])
print(f"{ok} passed, {bad} failed")
if 'ok' in globals(): sys.exit(1 if bad else 0)
