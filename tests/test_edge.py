import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py"), encoding="utf-8").read())
import telestep
root = tk.Tk(); root.geometry("+20+20")
app = telestep.App(root, settings_path=os.path.join(tempfile.mkdtemp(), "s.json")); root.update()
# pretend there is one 1920x1080 screen (index 0 is "all screens")
app.screens = [{"left": 0, "top": 0, "width": 1920, "height": 1080}, {"left": 0, "top": 0, "width": 1920, "height": 1080}]
app.var_compact.set(True); app._sync_mode(); root.update()
w, h = root.winfo_width(), root.winfo_height()
# icon dropped at the very right edge / bottom edge / off the corner
for (x, y) in [(1920 - w, 400), (1915, 400), (900, 1075), (2500, -50)]:
    app._drag = (0, 0)
    app._c_drag(type("E", (), {"x_root": x, "y_root": y})()); root.update()
    check(f"icon kept on screen from {x},{y}", 0 <= root.winfo_x() <= 1920 - w and 0 <= root.winfo_y() <= 1080 - h, (root.winfo_x(), root.winfo_y()))
# icon touching the right edge: expanding grows leftwards and stays on screen; collapsing returns it
app._cx0, app._cy0 = 1920 - w - 2, 500; root.geometry(f"+{app._cx0}+{app._cy0}"); root.update()
app._expand_compact(True); root.update()
check("expanded fully on screen", root.winfo_x() >= 0 and root.winfo_x() + root.winfo_reqwidth() <= 1920, (root.winfo_x(), root.winfo_reqwidth()))
app._expand_compact(False); root.update()
check("collapses back to its spot", root.winfo_x() == 1920 - w - 2 and root.winfo_y() == 500, (root.winfo_x(), root.winfo_y()))
# near the bottom: grows upward if it would not fit
app._cx0, app._cy0 = 500, 1080 - h; root.geometry(f"+{app._cx0}+{app._cy0}"); root.update()
app._expand_compact(True); root.update()
check("bottom edge ok", root.winfo_y() + root.winfo_reqheight() <= 1080, (root.winfo_y(), root.winfo_reqheight()))
print(f"{ok} passed, {bad} failed"); sys.exit(1 if bad else 0)
