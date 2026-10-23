"""
telestep_support.py - Support mode: a one-button recorder for sending a problem to IT.

The user types (optionally) what is wrong, clicks Record, repeats the problem, clicks Stop.  Telestep then writes ONE
zip file to the Desktop containing:
    Telestep_report.html   a compact one-sheet report: problem, summary, system details, every step with a screenshot
    steps.txt              the steps as plain text
    environment.txt        computer / OS / display details
    network.txt            ipconfig /all (can be turned off)
    session/               (optional) the full session, so IT can open it in Telestep's review editor

Nothing is uploaded or sent anywhere.  Start it with  Telestep.exe --support  or by naming the exe "*Support*.exe".
Optional settings go in telestep_support.json next to the exe (see telestep_support.example.json).
"""
import base64
import datetime as dt
import html
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image

import telestep_recorder as sr
import telestep_report as rep
import telestep_widgets as w
from telestep_model import VERSION, environment_text

TITLE = "Telestep Support"
CONFIG_NAME = "telestep_support.json"
DEFAULTS = {
    "ask_contact": True,  # ask the user for their name and phone/email (pre-filled from Windows when known)
    "require_contact": False,  # insist on a name and contact before recording
    "contact": "",  # shown on the finish screen and in the report, e.g. "helpdesk@example.com or ext. 1234"
    "title": "Support recording",
    "output": "desktop",  # "desktop" or a folder path
    "max_mb": 10,  # shrink the screenshots until the zip is under this size (email limits)
    "capture": "screen",  # screen | all | window
    "key_mode": "count",  # none | count  (typed text is never recorded unless you set "text")
    "after_mode": "off",  # off | replace | pair  (also capture the result of each click)
    "exclude_taskbar": False,
    "collect_network": True,
    "include_session": False,
}
# (max image width, JPEG quality), tried in order until the zip fits max_mb
QUALITY_LEVELS = [(1100, 68), (900, 58), (720, 50), (560, 42)]


# ----------------------------------------------------------------------------------------------- config
def app_dir():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def load_config(path=None):
    cfg = dict(DEFAULTS)
    p = Path(path) if path else app_dir() / CONFIG_NAME
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if cfg["capture"] not in ("screen", "all", "window"):
        cfg["capture"] = "screen"
    if cfg["key_mode"] not in ("none", "count", "text"):
        cfg["key_mode"] = "count"
    if cfg["after_mode"] not in ("off", "replace", "pair"):
        cfg["after_mode"] = "off"
    try:
        cfg["max_mb"] = max(1.0, float(cfg["max_mb"]))
    except (TypeError, ValueError):
        cfg["max_mb"] = DEFAULTS["max_mb"]
    return cfg


def windows_identity():
    """(display name, e-mail-style sign-in name) of the signed-in user when Windows knows them, else (login name, '')."""
    name = upn = ""
    try:
        import ctypes
        for fmt in (3, 8):  # NameDisplay, NameUserPrincipal
            buf = ctypes.create_unicode_buffer(256)
            size = ctypes.c_ulong(256)
            val = buf.value if ctypes.windll.secur32.GetUserNameExW(fmt, buf, ctypes.byref(size)) else ""
            if fmt == 3:
                name = val
            else:
                upn = val
    except Exception:
        pass
    return (name or os.environ.get("USERNAME") or os.environ.get("USER") or "", upn if "@" in upn else "")


def desktop_dir():
    """The real Desktop folder (follows OneDrive redirection), falling back to the home folder."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        pass
    d = Path.home() / "Desktop"
    return d if d.exists() else Path.home()


def output_dir(cfg):
    out = cfg.get("output", "desktop")
    p = desktop_dir() if str(out).lower() == "desktop" else Path(os.path.expandvars(str(out)))
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        p = desktop_dir()
    return p


def temp_root():
    return Path(tempfile.gettempdir()) / "Telestep_support"


def network_info():
    """`ipconfig /all` as text ('' if unavailable).  Windows only."""
    try:
        r = subprocess.run(["ipconfig", "/all"], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n").strip()
    except Exception:
        return ""


# ----------------------------------------------------------------------------------------------- report
def _jpeg_b64(img, width, quality):
    if img.width > width:
        img = img.resize((width, max(1, round(img.height * width / img.width))), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def collect_images(session):
    """{step id: (annotated PIL image | None, 'after' PIL image | None)} - loaded once, reused for each quality level."""
    nums, out = session.numbering(), {}
    for s in session.steps:
        if s.skip or s.kind in ("note", "section"):
            continue
        try:
            main = rep.render_step_image(session, s, nums.get(s.id, 0))
        except Exception:
            main = None
        after = None
        if s.raw_after and (session.dir / s.raw_after).exists():
            try:
                after = Image.open(session.dir / s.raw_after).convert("RGB")
            except Exception:
                after = None
        out[s.id] = (main, after)
    return out


_CSS = """
:root { --acc: #1565c0; --bad: #c62828; }
* { box-sizing: border-box; }
body { font: 14px/1.45 "Segoe UI", system-ui, sans-serif; color: #1c1f23; margin: 0; padding: 18px 22px 40px; background: #fff; }
h1 { margin: 0; font-size: 22px; } h1 small { color: #667; font-size: 13px; font-weight: 400; }
h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--acc); margin: 20px 0 6px;
     border-bottom: 2px solid var(--acc); padding-bottom: 2px; }
.top { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; } .top img { height: 40px; }
.meta { color: #556; font-size: 13px; }
.problem { background: #fff8e1; border-left: 4px solid #f9a825; padding: 8px 12px; white-space: pre-wrap; }
.err { background: #ffebee; border-left: 4px solid var(--bad); padding: 6px 12px; margin: 4px 0; font-family: Consolas, monospace; font-size: 12.5px; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 4px 28px; }
table.kv { border-collapse: collapse; font-size: 12.5px; width: 100%; } table.kv td { padding: 1px 8px 1px 0; vertical-align: top; }
table.kv td:first-child { color: #667; white-space: nowrap; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(430px, 1fr)); gap: 12px; }
.card { border: 1px solid #cfd4dc; border-radius: 6px; padding: 8px 10px; break-inside: avoid; }
.card.has-dialog { border-color: var(--bad); }
.card .n { color: var(--acc); font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }
.card .cap { font-weight: 600; margin: 1px 0; } .card .m { color: #778; font-size: 11.5px; }
.card img { width: 100%; border: 1px solid #dde; border-radius: 3px; margin-top: 6px; display: block; }
.card .lbl { font-size: 11px; color: #778; margin-top: 4px; }
.note { border-left: 4px solid #1e88e5; background: #e3f2fd; padding: 6px 12px; border-radius: 3px; break-inside: avoid; grid-column: 1 / -1; }
.note.warning { border-color: #e65100; background: #fff3e0; } .note.tip { border-color: #2e7d32; background: #e8f5e9; }
details { margin-top: 8px; } pre { background: #f6f7f9; padding: 8px; overflow: auto; font-size: 11.5px; }
footer { margin-top: 28px; color: #889; font-size: 12px; border-top: 1px solid #dde; padding-top: 6px; }
@page { size: A4; margin: 10mm; }
@media print { body { padding: 0; } .grid { grid-template-columns: repeat(2, 1fr); } }
"""


def _h(text):
    return html.escape(str(text or "")).replace("\n", "<br>")


def build_report_html(session, images, cfg, description, duration, width, quality, network="", reporter=("", "")):
    nums = session.numbering()
    env = {k: v for k, v in (session.environment or {}).items() if k != "Python"}
    steps = [s for s in session.steps if not s.skip]
    apps = []
    for s in steps:
        a = (s.app + (f" {s.app_version}" if s.app_version else "")).strip()
        if a and a not in apps:
            apps.append(a)
    errors = [(nums.get(s.id, 0), s.dialog_text.strip().splitlines()[0][:300]) for s in steps if s.dialog_text.strip()]
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{_h(session.title)}</title>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'><style>{_CSS}</style></head><body>"]
    logo = ""
    try:
        import telestep_help
        lp = telestep_help.logo_path(small=True)
        if lp:
            logo = f"<img alt='' src='data:image/png;base64,{base64.b64encode(Path(lp).read_bytes()).decode()}'>"
    except Exception:
        pass
    out.append(f"<div class='top'>{logo}<div><h1>{_h(session.title)} <small>Telestep support report</small></h1>"
               f"<div class='meta'>{_h(env.get('Computer') or session.host)} &middot; {_h(env.get('User', ''))} &middot; "
               f"{_h(session.created.replace('T', ' ')[:16])} &middot; {session.count()} steps"
               f"{' &middot; ' + _h(duration) if duration else ''}</div></div></div>")
    who = " - ".join(x for x in reporter if x)
    if who:
        out.append(f"<h2>Reported by</h2><div class='problem' style='background:#e8f0fe;border-color:#1565c0'>{_h(who)}</div>")
    if description:
        out.append(f"<h2>Problem described by the user</h2><div class='problem'>{_h(description)}</div>")
    if errors:
        out.append("<h2>Error / message boxes seen</h2>")
        out += [f"<div class='err'>Step {n}: {_h(t)}</div>" for n, t in errors]
    summary = [("Applications used", ", ".join(apps) or "-")]
    if cfg.get("contact"):
        summary.append(("Send replies to", cfg["contact"]))
    out.append("<h2>Summary and system</h2><div class='cols'><table class='kv'>"
               + "".join(f"<tr><td>{_h(k)}</td><td>{_h(v)}</td></tr>" for k, v in summary)
               + "".join(f"<tr><td>{_h(k)}</td><td>{_h(v)}</td></tr>" for k, v in list(env.items())[:len(env) // 2 + 1])
               + "</table><table class='kv'>"
               + "".join(f"<tr><td>{_h(k)}</td><td>{_h(v)}</td></tr>" for k, v in list(env.items())[len(env) // 2 + 1:])
               + "</table></div>")
    out.append("<h2>Steps</h2><div class='grid'>")
    for s in steps:
        cap = rep.clean_text(s.caption("technical"))
        if s.kind == "section":
            continue
        if s.kind == "note":
            lvl = s.level if s.level in ("warning", "tip") else "note"
            out.append(f"<div class='note {lvl}'><b>{lvl.title()}:</b> {_h(cap)}</div>")
            continue
        meta = " | ".join(x for x in (s.when, s.window and f"Window: {s.window}",
                                      s.app and f"App: {s.app}{' ' + s.app_version if s.app_version else ''}") if x)
        main, after = images.get(s.id, (None, None))
        card = [f"<div class='card{' has-dialog' if s.dialog_text.strip() else ''}'>"
                f"<div class='n'>Step {nums.get(s.id, 0)}</div><div class='cap'>{_h(cap)}</div>"
                f"<div class='m'>{_h(rep.clean_text(meta))}</div>"]
        if s.dialog_text.strip():
            card.append(f"<div class='err'>{_h(rep.clean_text(s.dialog_text))}</div>")
        if main is not None:
            card.append(f"{'<div class=lbl>Before</div>' if after is not None else ''}"
                        f"<img alt='Step {nums.get(s.id, 0)}' src='data:image/jpeg;base64,{_jpeg_b64(main, width, quality)}'>")
        if after is not None:
            card.append(f"<div class='lbl'>After</div><img alt='' src='data:image/jpeg;base64,{_jpeg_b64(after, width, quality)}'>")
        card.append("</div>")
        out.append("".join(card))
    out.append("</div>")
    if network:
        out.append(f"<details><summary>Network details (ipconfig /all)</summary><pre>{_h(network)}</pre></details>")
    out.append(f"<footer>Recorded locally with Telestep {VERSION}. Nothing was uploaded; the user chose to send this file."
               f"</footer></body></html>")
    return "".join(out)


def package(session, cfg, description="", duration="", progress=None, reporter=("", "")):
    """Write the support zip.  Returns (zip path, size in bytes, level used, fits the size limit)."""
    say = progress or (lambda _t: None)
    if session.environment:
        env_text = environment_text(session.environment, session.title)
    else:
        env_text = ""
    say("Preparing screenshots...")
    images = collect_images(session)
    network = network_info() if cfg.get("collect_network") else ""
    tpl = rep.Template(wording="technical", environment=False)
    txt = rep.steps_text(session, tpl)
    if description:
        txt = f"Problem described by the user:\n{description}\n\n" + txt
    if any(reporter):
        txt = "Reported by: " + " - ".join(x for x in reporter if x) + "\n\n" + txt
    host = "".join(c for c in (session.host or "PC") if c.isalnum() or c in "-_") or "PC"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    zpath = output_dir(cfg) / f"Telestep_{host}_{stamp}.zip"
    limit = cfg["max_mb"] * 1024 * 1024
    size, level, fits = 0, 0, False
    for level, (width, quality) in enumerate(QUALITY_LEVELS):
        say("Building the report..." if level == 0 else f"Report too large, shrinking images ({level})...")
        page = build_report_html(session, images, cfg, description, duration, width, quality, network, reporter)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("Telestep_report.html", page)
            z.writestr("steps.txt", txt)
            if env_text:
                z.writestr("environment.txt", env_text)
            if network:
                z.writestr("network.txt", network)
            if cfg.get("include_session"):
                session.save()
                for f in session.dir.rglob("*"):
                    if f.is_file() and f.name != "save_errors.log":
                        z.write(f, "session/" + f.relative_to(session.dir).as_posix())
        size = zpath.stat().st_size
        if size <= limit:
            fits = True
            break
    try:  # keep a local copy of the report for the Preview button
        (session.dir / "Telestep_report.html").write_text(page, encoding="utf-8")
    except OSError:
        pass
    return zpath, size, level, fits


def fmt_duration(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d} min"


def fmt_size(n):
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


# ----------------------------------------------------------------------------------------------- window
class SupportApp:
    INTRO = ("Having a problem? Click Record, repeat what goes wrong, then click Stop. "
             "You will get one ZIP file to send to IT.")
    PRIVACY = ("Telestep takes a screenshot at each click. Nothing is sent anywhere. Click Pause (or press F9) "
               "before showing passwords or private information.")

    def __init__(self, root, config=None, recorder_factory=None):
        self.root = root
        self.cfg = config if config is not None else load_config()
        self.make_recorder = recorder_factory or self._default_recorder
        self.rec = None
        self.state = "idle"  # idle | rec | paused | packaging | done
        self.started = 0.0
        self.result = None
        self.session = None
        self.work = None
        self.description = ""
        self.reporter = ("", "")
        self.results_q = queue.Queue()
        self._job = None

        root.title(TITLE)
        try:
            import telestep_help
            telestep_help.apply_icon(root)
        except Exception:
            pass
        root.attributes("-topmost", True)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<F1>", lambda e: self.open_help())
        s = ttk.Style(root)
        s.configure("Big.TButton", font=("Segoe UI", 12, "bold"), padding=8)
        s.configure("Title.TLabel", font=("Segoe UI", 14, "bold"))
        self.f = ttk.Frame(root, padding=14)
        self.f.pack(fill="both", expand=True)
        self.var_status = tk.StringVar()
        self.var_warn = tk.StringVar()
        self.lbl_title = ttk.Label(self.f, text="Telestep Support", style="Title.TLabel")
        self.lbl_intro = ttk.Label(self.f, text=self.INTRO, wraplength=360, justify="left")
        self.lbl_q = ttk.Label(self.f, text="What is the problem? (optional)")
        name, upn = windows_identity()
        self.var_name, self.var_contact = tk.StringVar(value=name), tk.StringVar(value=upn)
        self.lbl_name = ttk.Label(self.f, text="Your name")
        self.ent_name = ttk.Entry(self.f, textvariable=self.var_name)
        self.lbl_contact = ttk.Label(self.f, text="Phone or email (so IT can reach you)")
        self.ent_contact = ttk.Entry(self.f, textvariable=self.var_contact)
        self.txt = tk.Text(self.f, width=44, height=4, wrap="word", relief="solid", borderwidth=1, font=("Segoe UI", 10))
        self.btn_start = ttk.Button(self.f, text="●  Record", style="Big.TButton", command=self.start)
        self.lbl_priv = ttk.Label(self.f, text=self.PRIVACY, wraplength=360, justify="left", foreground="#666")
        self.lbl_status = ttk.Label(self.f, textvariable=self.var_status, font=("Segoe UI", 11, "bold"))
        self.lbl_warn = ttk.Label(self.f, textvariable=self.var_warn, wraplength=360, justify="left", foreground="#b26a00")
        self.row = ttk.Frame(self.f)
        self.btn_pause = ttk.Button(self.row, text="Pause", command=self.toggle_pause)
        self.btn_note = ttk.Button(self.row, text="Note", command=self.add_note)
        self.btn_stop = ttk.Button(self.row, text="■  Stop and package", style="Big.TButton", command=self.stop)
        self.btn_pause.pack(side="left")
        self.btn_note.pack(side="left", padx=6)
        self.btn_stop.pack(side="left", padx=(6, 0))
        self.lbl_done = ttk.Label(self.f, text="", wraplength=380, justify="left")
        self.row2 = ttk.Frame(self.f)
        self.btn_show = ttk.Button(self.row2, text="Show the file", command=self.show_file)
        self.btn_prev = ttk.Button(self.row2, text="Preview", command=self.preview)
        self.btn_again = ttk.Button(self.row2, text="Record again", command=self.reset)
        self.btn_close = ttk.Button(self.row2, text="Close", command=self.on_close)
        for b in (self.btn_show, self.btn_prev, self.btn_again, self.btn_close):
            b.pack(side="left", padx=(0, 6))
        self.layout("idle")
        self.poll()

    # ---- layout per state
    def layout(self, state):
        for wd in self.f.winfo_children():
            wd.grid_remove()
        g = lambda wd, **kw: wd.grid(sticky="w", **kw)
        if state == "idle":
            g(self.lbl_title, row=0, pady=(0, 6))
            g(self.lbl_intro, row=1, pady=(0, 8))
            g(self.lbl_q, row=2)
            self.txt.grid(row=3, sticky="ew", pady=(2, 10))
            r = 4
            if self.cfg.get("ask_contact", True):
                g(self.lbl_name, row=4)
                self.ent_name.grid(row=5, sticky="ew", pady=(2, 6))
                g(self.lbl_contact, row=6)
                self.ent_contact.grid(row=7, sticky="ew", pady=(2, 10))
                r = 8
            self.btn_start.grid(row=r, sticky="ew")
            g(self.lbl_priv, row=r + 1, pady=(10, 0))
            if self.var_warn.get():
                g(self.lbl_warn, row=r + 2, pady=(6, 0))
        elif state in ("rec", "paused", "packaging"):
            g(self.lbl_status, row=0, pady=(0, 6))
            self.row.grid(row=1, sticky="w")
            g(self.lbl_warn, row=2, pady=(6, 0))
            for b in (self.btn_pause, self.btn_note, self.btn_stop):
                b.state(["!disabled" if state != "packaging" else "disabled"])
        elif state == "done":
            g(self.lbl_title, row=0, pady=(0, 6))
            g(self.lbl_done, row=1, pady=(0, 10))
            self.row2.grid(row=2, sticky="w")
        self.state_layout = state
        self.root.update_idletasks()
        self.place()

    def place(self):
        try:
            self.root.update_idletasks()
            wd = self.root.winfo_reqwidth()
            sw = self.root.winfo_screenwidth()
            self.root.geometry(f"+{max(0, sw - wd - 30)}+30")
        except tk.TclError:
            pass

    # ---- recording
    def _default_recorder(self, outdir, title):
        cap = sr.CaptureOpts(mode=self.cfg["capture"], exclude_taskbar=bool(self.cfg["exclude_taskbar"]))
        opts = sr.RecordOpts(key_mode=self.cfg["key_mode"], max_width=1280, after_mode=self.cfg["after_mode"],
                             scroll=False, wording="technical")
        return sr.Recorder(outdir, cap, opts, title)

    def start(self):
        self.description = self.txt.get("1.0", "end").strip()
        self.reporter = (self.var_name.get().strip(), self.var_contact.get().strip()) if self.cfg.get("ask_contact", True) else ("", "")
        if self.cfg.get("require_contact") and not all(self.reporter):
            messagebox.showinfo(TITLE, "Please enter your name and a phone number or email so IT can reach you.", parent=self.root)
            return
        shutil.rmtree(temp_root(), ignore_errors=True)
        outdir = temp_root() / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            rec = self.make_recorder(outdir, self.cfg["title"])
            rec.ignore_titles = {TITLE, w.NOTE_TITLE}
            rect = w.window_screen_rect(self.root)
            rec.ignore_rects = [rect] if rect else []
            rec.start()
        except Exception as e:
            messagebox.showerror(TITLE, f"Could not start recording:\n{e}", parent=self.root)
            return
        self.rec = rec
        self.started = time.monotonic()
        self.var_warn.set("")
        w.exclude_from_capture(self.root, True)
        self.set_state("rec")
        failed = getattr(rec, "hotkeys_failed", [])
        if failed:
            self.var_warn.set("Hotkey(s) not available: " + ", ".join(failed) + ". Use the buttons instead.")

    def set_state(self, state):
        self.state = state
        self.layout(state)

    def toggle_pause(self):
        if self.rec:
            self.rec.toggle_pause()

    def add_note(self):
        rec = self.rec
        if not rec:
            return
        was = rec.paused
        rec.paused = True
        try:
            dlg = w.NoteDialog(self.root)
        finally:
            rec.paused = was
        if dlg.result:
            rec.add_note(dlg.result, dlg.level)

    def stop(self):
        rec, self.rec = self.rec, None
        if not rec:
            return
        duration = fmt_duration(time.monotonic() - self.started)
        self.set_state("packaging")
        self.var_status.set("Saving...")
        self.root.update_idletasks()
        try:
            sess = rec.stop()
        except Exception as e:
            messagebox.showerror(TITLE, f"Could not finish the recording:\n{e}", parent=self.root)
            self.reset()
            return
        self.session = sess
        if not sess.steps:
            messagebox.showinfo(TITLE, "Nothing was recorded - no clicks were captured. Try again.", parent=self.root)
            self.reset()
            return
        sess.title = self.cfg["title"] if not self.description else f"{self.cfg['title']}: {self.description.splitlines()[0][:80]}"
        self.var_status.set("Creating your ZIP file...")

        def job():
            try:
                self.results_q.put(("ok", package(sess, self.cfg, self.description, duration,
                                                  progress=lambda t: self.results_q.put(("progress", t)),
                                                  reporter=self.reporter)))
            except Exception as e:
                self.results_q.put(("error", f"{type(e).__name__}: {e}"))

        threading.Thread(target=job, daemon=True).start()

    def finished(self, res):
        zpath, size, level, fits = res
        self.result = zpath
        lines = [f"Done. Your file is on the {'Desktop' if str(self.cfg['output']).lower() == 'desktop' else 'chosen folder'}:",
                 f"{zpath.name}  ({fmt_size(size)})", "", "Send this ZIP file to IT."]
        if self.cfg.get("contact"):
            lines.append(f"Contact: {self.cfg['contact']}")
        if not fits:
            lines.append(f"\nNote: the file is larger than {self.cfg['max_mb']:g} MB; it may not fit in an email.")
        self.lbl_done.configure(text="\n".join(lines))
        self.set_state("done")

    def show_file(self):
        if self.result:
            try:
                subprocess.Popen(["explorer", f"/select,{self.result}"])
            except Exception:
                try:
                    os.startfile(str(self.result.parent))  # Windows only
                except Exception:
                    pass

    def preview(self):
        p = self.session.dir / "Telestep_report.html" if self.session else None
        if p and p.exists():
            try:
                os.startfile(str(p))  # Windows only
            except Exception:
                import webbrowser
                webbrowser.open(p.as_uri())

    def reset(self):
        self.rec = None
        self.session = None
        self.result = None
        shutil.rmtree(temp_root(), ignore_errors=True)
        self.txt.delete("1.0", "end")
        self.var_warn.set("")
        self.set_state("idle")

    def open_help(self):
        try:
            import telestep_help
            telestep_help.HelpWindow(self.root, "help")
        except Exception:
            pass

    # ---- periodic
    def poll(self):
        rec = self.rec
        if rec:
            rect = w.window_screen_rect(self.root)
            rec.ignore_rects = [rect] if rect else []
            while not rec.events.empty():
                ev = rec.events.get_nowait()
                if ev[0] == "warn":
                    self.var_warn.set(ev[1])
                elif ev[0] == "note":
                    self.add_note()
            if rec.stop_evt.is_set():
                self.stop()
            elif rec is self.rec:
                paused = rec.paused
                st = "paused" if paused else "rec"
                if st != self.state:
                    self.state = st
                self.btn_pause.configure(text="Resume" if paused else "Pause")
                el = fmt_duration(time.monotonic() - self.started)
                self.var_status.set(f"{'‖ Paused' if paused else '● Recording'}   {rec.session.count()} steps   {el}"
                                    f"   (F10 = stop)")
        while not self.results_q.empty():
            kind, val = self.results_q.get_nowait()
            if kind == "progress":
                self.var_status.set(val)
            elif kind == "ok":
                self.finished(val)
            elif kind == "error":
                messagebox.showerror(TITLE, f"Could not create the ZIP file:\n{val}\n\nYour recording is in:\n"
                                     f"{self.session.dir if self.session else temp_root()}", parent=self.root)
                self.set_state("idle")
        self._job = self.root.after(150, self.poll)

    def on_close(self):
        if self.rec:
            if not messagebox.askyesno(TITLE, "Recording is in progress. Stop and create the ZIP before closing?",
                                       parent=self.root):
                return
            self.stop()
            return
        if self.state == "packaging":
            return
        try:
            self.root.after_cancel(self._job)
        except Exception:
            pass
        shutil.rmtree(temp_root(), ignore_errors=True)  # the raw screenshots only ever live in the ZIP afterwards
        self.root.destroy()


def main():
    root = tk.Tk()
    SupportApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
