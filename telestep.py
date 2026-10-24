#!/usr/bin/env python3
"""
telestep.py - Telestep toolbar (keep all telestep*.py files together).

Run:  python telestep.py          (pythonw telestep.py = no console window)
Tip:  run as administrator to record clicks inside admin (elevated) apps.

Mini-bar icons: Record, Pause/Resume, Stop, Note, Screenshot (no click needed), Review a session,
Open folder, and a gear for settings (tabs: General, Capture, Privacy, Report, Options).
Hotkeys while recording (change them in Options):
    F9 pause/resume   F10 stop   Ctrl+Shift+F7 note   Ctrl+Shift+F8 screenshot   Ctrl+Shift+F6 delete last step

Screen overlays (click-through, hidden from screenshots on Windows 10 2004+/11):
    coloured frame = captured area (red recording, amber paused, blue preview, white flash = shot taken)
    magenta shading = masked areas / hidden windows    gray shading = excluded taskbar
"""
import datetime as dt
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import telestep_audio as ta
import telestep_core as core
import telestep_report as rep
import telestep_recorder as sr
import telestep_settings as cfg
import telestep_widgets as w
from telestep_model import Session

TITLE = "Telestep"
AFTER = {"Screenshot at the click only": "off", "Also capture the result after the click": "pair",
         "Capture only the result after the click": "replace"}
KEYS = {"Mouse only - no keyboard hook at all": "none", "Count typed characters only": "count",
        "Record typed text (never passwords)": "text"}
ICON_COLORS = {"record": "#e53935", "pause": "#f59e0b", "resume": "#2e9e4f", "stop": "#b71c1c", "note": "#1e88e5",
               "camera": "#00897b", "review": "#5e35b1", "folder": "#8d6e63", "gear": "#546e7a",
               "help": "#0277bd", "minimize": "#546e7a", "mic_on": "#e53935", "mic_off": "#607d8b"}


def _inv(d, value):
    return next((k for k, v in d.items() if v == value), next(iter(d)))


class Tray:
    """Optional system-tray icon (needs `pip install pystray`).  Menu clicks are queued for the Tk thread."""

    def __init__(self, app):
        self.app, self.icon, self.ok = app, None, False
        try:
            import pystray  # noqa: F401  (a real import, so it also works inside the PyInstaller exe)
            self.ok = True
        except Exception:
            pass

    @staticmethod
    def _image(color=None):
        """The Telestep logo; `color` adds a state badge (red = recording, amber = paused) in the corner."""
        from PIL import Image, ImageDraw
        im = None
        try:
            import telestep_help
            p = telestep_help.logo_path(small=True)
            if p:
                im = Image.open(p).convert("RGBA").resize((64, 64))
        except Exception:
            im = None
        if im is None:  # logo file missing: fall back to a plain dot
            im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse([8, 8, 56, 56], fill=color or "#78909c")
            return im
        if color:
            d = ImageDraw.Draw(im)
            d.ellipse([30, 30, 64, 64], fill="white")
            d.ellipse([35, 35, 59, 59], fill=color)
        return im

    def start(self):
        if not self.ok or self.icon:
            return
        import pystray
        put = self.app.requests.put
        item = pystray.MenuItem
        app = self.app
        idle = lambda _i=None: app.state == "idle"
        busy = lambda _i=None: app.state != "idle"
        status = {"idle": "Telestep - not recording", "rec": "\u25cf RECORDING", "paused": "\u275a\u275a PAUSED"}
        menu = pystray.Menu(  # rebuilt from app.state each time the menu opens
            item(lambda _i: status.get(app.state, "Telestep"), None, enabled=False),
            item("Show toolbar", lambda: put("show"), default=True),
            pystray.Menu.SEPARATOR,
            item("Start recording", lambda: put("start"), visible=idle),
            item(lambda _i: "Resume" if app.state == "paused" else "Pause", lambda: put("pause"), visible=busy),
            item("Stop and save", lambda: put("stop"), visible=busy),
            item("Add note...", lambda: put("note"), visible=busy),
            item("Take screenshot now", lambda: put("shot"), visible=busy),
            pystray.Menu.SEPARATOR,
            item("Quit", lambda: put("quit")))
        self.icon = pystray.Icon("Telestep", self._image(), "Telestep", menu)
        try:
            self.icon.run_detached()
        except Exception:
            self.icon = None

    def set_state(self, state):
        if self.icon:
            try:
                self.icon.icon = self._image({"rec": "#e53935", "paused": "#f59e0b"}.get(state))
            except Exception:
                pass

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None


class App:
    def __init__(self, root, settings_path=None):
        self.root = root
        self.settings_path = settings_path
        self.data = cfg.load(settings_path)
        self.rec = None
        self._saving = None
        self._stop_result = None
        self.state = "idle"
        self.out_dir = None
        self.last_session = None
        self.review = None
        self.report_title = "Recorded steps"
        self.base = Path(self.data["base_dir"])
        self.screens, self.choices = [], {}
        self.region = tuple(self.data["region"]) if self.data["region"] else None
        self.masks = [core.Mask.from_dict(m) for m in self.data["masks"]]
        self.idle_msg = "Idle"
        self.toolbar_rect = None
        self.requests = queue.Queue()
        self.flash_until = 0.0
        self.toast_until = 0.0
        self._pos_seen, self._pos_changed = None, 0.0
        self._ocr_checked = False
        self._ocr_result = None
        self._last_poll = time.monotonic()
        self._dbg = None
        try:  # slow-spot diagnostics: stays empty (and is deleted on exit) unless the window freezes
            import faulthandler  # noqa: F401,F811
            self._dbg_path = Path(settings_path or cfg.settings_path()).with_name("telestep_debug.log")
            try:
                if self._dbg_path.stat().st_size > 2_000_000:  # keep it small: start over once it grows past 2 MB
                    self._dbg_path.replace(self._dbg_path.with_suffix(".old.log"))
            except OSError:
                pass
            self._dbg = open(self._dbg_path, "a", buffering=1, encoding="utf-8")
            import platform
            self._dbg.write(f"\n===== Telestep {core.VERSION} started {dt.datetime.now():%Y-%m-%d %H:%M:%S} | "
                            f"Windows {platform.version()} | Python {platform.python_version()} | "
                            f"{os.cpu_count()} CPU threads =====\n")
        except Exception:
            self._dbg = None
        self._poll_job = None

        core.SKIP_TITLES.add(w.OVERLAY_TITLE)
        root.title(TITLE)
        try:
            import telestep_help
            telestep_help.apply_icon(root)
        except Exception:
            pass
        root.attributes("-topmost", True)
        try:
            root.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<F1>", lambda e: self.open_help())
        root.bind("<Button-3>", self._bar_menu)
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self.bar_px = max(3, round(4 * self.scale))

        d = self.data
        self.var_title = tk.StringVar(value="")
        self.var_folder = tk.StringVar(value=str(self.base))
        self.var_preset = tk.StringVar(value="(none)")
        self.var_review = tk.BooleanVar(value=d["review_after_stop"])
        self.var_mode = tk.StringVar(value="Screen under click")
        self.var_taskbar = tk.BooleanVar(value=d["exclude_taskbar"])
        self.var_after = tk.StringVar(value=_inv(AFTER, d["after_mode"]))
        self.var_delay = tk.IntVar(value=d["after_delay_ms"])
        self.var_width = tk.IntVar(value=d["max_width"])
        self.var_dbl = tk.BooleanVar(value=d["dbl"])
        self.var_drag = tk.BooleanVar(value=d["drag"])
        self.var_scroll = tk.BooleanVar(value=d["scroll"])
        self.var_shortcuts = tk.BooleanVar(value=d["shortcuts"])
        self.var_dialogs = tk.BooleanVar(value=d["watch_dialogs"])
        self.var_narrate = tk.BooleanVar(value=d.get("narrate", False))
        self.var_mpath = tk.BooleanVar(value=d.get("mouse_path", False))
        self.var_audio_dev = tk.StringVar(value=d.get("audio_device", "") or ta.DEFAULT_NAME)
        ta.preferred = d.get("audio_device", "") or ""
        self.var_assign = tk.StringVar(value=d.get("audio_assign", "next"))
        self.var_keys = tk.StringVar(value=_inv(KEYS, d["key_mode"]))
        self.var_mstyle = tk.StringVar(value=core.MASK_STYLES[core.canon_style(d["mask_style"])])
        self.var_ocr = {k: tk.BooleanVar(value=d["ocr"].get(k, False)) for k in core.OCR_PATTERNS}
        self.var_ocr_labels = tk.BooleanVar(value=d["ocr_labels"])
        self.var_ocr_on = tk.BooleanVar(value=d.get("ocr_enabled", True))  # master switch: keeps the ticks below
        self.var_fmt = {k: tk.BooleanVar(value=d["formats"].get(k, False)) for k in rep.FORMATS}
        self.var_wording = tk.StringVar(value="Friendly" if d["wording"] == "friendly" else "Technical")
        t = d["template"]
        self.var_header, self.var_footer = tk.StringVar(value=t["header"]), tk.StringVar(value=t["footer"])
        self.var_author, self.var_logo = tk.StringVar(value=t["author"]), tk.StringVar(value=t["logo"])
        self.var_env = tk.BooleanVar(value=t["environment"])
        self.var_focus = tk.StringVar(value=core.FOCUS_MODES.get(t.get("focus", "off"), core.FOCUS_MODES["off"]))
        self.var_flash, self.var_sound = tk.BooleanVar(value=d["flash"]), tk.BooleanVar(value=d["sound"])
        self.var_tray, self.var_hidetray = tk.BooleanVar(value=d["tray"]), tk.BooleanVar(value=d["hide_in_tray"])
        self.var_closetray = tk.BooleanVar(value=d["close_to_tray"])
        self.var_overlay = tk.BooleanVar(value=d["overlays"])
        self.var_preview = tk.BooleanVar(value=True)  # outline while setting up (this session only)
        self.var_hide = tk.BooleanVar(value=d["hide_from_capture"])
        self.var_opacity = tk.IntVar(value=max(30, min(100, int(d.get("toolbar_opacity", 100)))))
        self.var_solid_hover = tk.BooleanVar(value=d.get("toolbar_solid_hover", True))
        self._adjusting_opacity = False
        self._hover = False
        self.var_compact = tk.BooleanVar(value=bool(d.get("compact_toolbar", False)))
        self.var_upd_check = tk.BooleanVar(value=bool(d.get("update_check", False)))
        self._compact_on, self._expanded = False, False  # icon mode shown / expanded under the pointer
        self._leave_t, self._cx0, self._cy0, self._drag = 0.0, None, None, None
        self._badges = {}
        self.var_hk = {k: tk.StringVar(value=d["hotkeys"].get(k, cfg.DEFAULT_HOTKEYS[k])) for k in cfg.DEFAULT_HOTKEYS}
        self.var_cfg = tk.BooleanVar(value=False)
        self.var_scope = tk.StringVar(value="")
        self.var_status = tk.StringVar(value=self.idle_msg)
        self.var_toast = tk.StringVar(value="")

        ttk.Style().configure("Icon.TButton", padding=2)
        isz = round(20 * self.scale)
        self.icons = {k: (w.make_icon(k, c, isz), w.make_icon(k, "#b8b8b8", isz)) for k, c in ICON_COLORS.items()}
        msz = round(26 * self.scale)  # the microphone indicator is bigger than the other icons, and ripples while open
        self.mic_frames = [w.make_icon("mic_pulse", "#e53935", msz, i / 8.0) for i in range(8)]
        self.mic_off_big = w.make_icon("mic_off", "#607d8b", msz)
        self._pulse_i = -1

        self.tray = Tray(self)
        main = self.main = ttk.Frame(root, padding=(6, 4))
        main.grid(sticky="nsew")
        main.columnconfigure(0, weight=1)
        bar = ttk.Frame(main)
        bar.grid(row=0, column=0, sticky="ew")
        self.btn_rec = self._icon_btn(bar, "record", "Record (start a new session)", self.start)
        self.btn_pause = self._icon_btn(bar, "pause", "Pause / resume", self.toggle_pause)
        self.btn_stop = self._icon_btn(bar, "stop", "Stop and save", self.stop)
        self.btn_note = self._icon_btn(bar, "note", "Add a note, warning or tip", self.add_note)
        self.btn_shot = self._icon_btn(bar, "camera", "Take a screenshot now (no click needed)", self.shot)
        self.btn_mic = self._icon_btn(bar, "mic_off", "Microphone: click to start / stop narrating (one voice clip per step)",
                                      self.toggle_mic)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=5, pady=2)
        ttk.Label(bar, textvariable=self.var_status, width=18, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self.btn_gear = ttk.Checkbutton(bar, style="Toolbutton", variable=self.var_cfg, command=self.toggle_config,
                                        takefocus=False)
        self._set_icon(self.btn_gear, "gear")
        w.Tip(self.btn_gear, "Settings")
        self.btn_gear.pack(side="right", padx=1)
        self.btn_folder = self._icon_btn(bar, "folder", "Show the recordings folder in File Explorer", self.open_folder, side="right")
        self.btn_review = self._icon_btn(bar, "review", "Review, edit and export a recording (pick from a list)", self.open_review,
                                         side="right")
        self.btn_help = self._icon_btn(bar, "help", "Help and About (F1)", self.open_help, side="right")
        self.btn_mini = self._icon_btn(bar, "minimize", "Minimize to an icon",
                                       self.enter_compact, side="right")
        self.lbl_toast = ttk.Label(main, textvariable=self.var_toast, foreground="#b45309",
                                   wraplength=int(360 * self.scale), justify="left")

        self.var_summary = tk.StringVar(value="")
        self.lbl_summary = ttk.Label(main, textvariable=self.var_summary, foreground="#4a5560", cursor="hand2",
                                     wraplength=int(340 * self.scale), justify="left")
        self.lbl_summary.bind("<Button-1>", lambda e: (self.var_cfg.set(True), self.toggle_config()))
        w.Tip(self.lbl_summary, "What the next recording will use. Click to change it in Settings.")

        self._build_compact()
        self.cfg = ttk.Frame(main, padding=(0, 8, 0, 0))
        ttk.Style(self.root).layout("Plain.TNotebook.Tab", [])  # our own, clearer tab strip is drawn instead
        self.nb = ttk.Notebook(self.cfg, style="Plain.TNotebook")
        self.nb.pack(fill="both", expand=True)
        self.tab_general, self.tab_capture = ttk.Frame(self.nb, padding=8), ttk.Frame(self.nb, padding=8)
        self.tab_privacy, self.tab_report = ttk.Frame(self.nb, padding=8), ttk.Frame(self.nb, padding=8)
        self.tab_options = ttk.Frame(self.nb, padding=8)
        self.tab_audio = ttk.Frame(self.nb, padding=8)
        for tab, name in ((self.tab_general, "General"), (self.tab_capture, "Capture"), (self.tab_audio, "Audio"),
                          (self.tab_privacy, "Privacy"), (self.tab_report, "Report"), (self.tab_options, "Options")):
            tab.columnconfigure(1, weight=1)
            self.nb.add(tab, text=name)
        self._tab_general()
        self._tab_capture()
        self._tab_audio()
        self._tab_privacy()
        self._tab_report()
        self._tab_options()
        self._make_tabbar()
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._tab_changed())

        for v in [self.var_title, self.var_review, self.var_taskbar, self.var_ocr_on, *self.var_fmt.values(),
                  *self.var_ocr.values()]:
            v.trace_add("write", lambda *a: self.update_summary())
        self.overlays = w.OverlayManager(self)
        self.refresh_screens()
        self.refresh_presets()
        self.refresh_masks()
        self.update_scope_label()
        self.set_state("idle")
        root.update_idletasks()
        self.place_toolbar()
        self.apply_capture_exclusion()
        self._apply_opacity()
        self._sync_mode()
        self.root.after(6000, self._maybe_check_updates)
        if self.var_tray.get():
            self.tray.start()
        self.poll()

    # ------------------------------------------------------------------ tabs
    def _grid(self, parent, row, label, widget, span=1, **kw):
        if label:
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        widget.grid(row=row, column=1 if label else 0, columnspan=span if label else span + 1, sticky="ew",
                    padx=(6, 0) if label else 0, pady=2, **kw)
        return widget

    def _tab_general(self):
        t = self.tab_general
        self.ent_title = self._grid(t, 0, "Title", ttk.Entry(t, textvariable=self.var_title, width=34))
        f = ttk.Frame(t)
        f.columnconfigure(0, weight=1)
        ttk.Entry(f, textvariable=self.var_folder, state="readonly").grid(row=0, column=0, sticky="ew")
        self.btn_browse = ttk.Button(f, text="Browse", width=8, command=self.browse)
        self.btn_browse.grid(row=0, column=1, padx=(4, 0))
        self._grid(t, 1, "Save to", f)
        p = ttk.Frame(t)
        p.columnconfigure(0, weight=1)
        self.cmb_preset = ttk.Combobox(p, textvariable=self.var_preset, state="readonly")
        self.cmb_preset.grid(row=0, column=0, sticky="ew")
        self.cmb_preset.bind("<<ComboboxSelected>>", lambda e: self.load_preset())
        self.btn_psave = ttk.Button(p, text="Save as...", width=10, command=self.save_preset)
        self.btn_psave.grid(row=0, column=1, padx=(4, 0))
        self.btn_pdel = ttk.Button(p, text="Delete", width=7, command=self.delete_preset)
        self.btn_pdel.grid(row=0, column=2, padx=(4, 0))
        self._grid(t, 2, "Preset", p)
        self._grid(t, 3, "", ttk.Checkbutton(t, text="Open the review editor after Stop (edit, then export)",
                                             variable=self.var_review), span=1)
        ttk.Label(t, text="Presets remember capture area, masks, privacy and report settings.",
                  foreground="gray").grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _tab_capture(self):
        t = self.tab_capture
        f = ttk.Frame(t)
        f.columnconfigure(0, weight=1)
        self.cmb_mode = ttk.Combobox(f, textvariable=self.var_mode, state="readonly", postcommand=self.refresh_screens)
        self.cmb_mode.grid(row=0, column=0, sticky="ew")
        self.cmb_mode.bind("<<ComboboxSelected>>", self.on_mode_change)
        self.btn_area = ttk.Button(f, text="Select area", width=11, command=self.select_area, state="disabled")
        self.btn_area.grid(row=0, column=1, padx=(4, 0))
        self._grid(t, 0, "Capture", f)
        self.chk_taskbar = self._grid(t, 1, "", ttk.Checkbutton(t, text="Exclude taskbar", variable=self.var_taskbar,
                                                                 command=lambda: (self.update_scope_label(),
                                                                                  self.update_overlays())))
        ttk.Label(t, textvariable=self.var_scope, wraplength=int(330 * self.scale), justify="left",
                  foreground="gray").grid(row=2, column=0, columnspan=2, sticky="w")
        self.cmb_after = self._grid(t, 3, "Screenshot", ttk.Combobox(t, textvariable=self.var_after, state="readonly",
                                                                      values=list(AFTER)))
        f2 = ttk.Frame(t)
        self.spn_delay = ttk.Spinbox(f2, from_=200, to=5000, increment=100, width=6, textvariable=self.var_delay)
        self.spn_delay.pack(side="left")
        ttk.Label(f2, text="ms after the click      image width").pack(side="left", padx=4)
        self.spn_width = ttk.Spinbox(f2, from_=800, to=3840, increment=100, width=6, textvariable=self.var_width)
        self.spn_width.pack(side="left")
        ttk.Label(f2, text="px").pack(side="left", padx=(2, 0))
        self._grid(t, 4, "Delay", f2)
        rec = ttk.LabelFrame(t, text="Also record", padding=4)
        rec.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.rec_checks = [ttk.Checkbutton(rec, text=txt, variable=var) for txt, var in (
            ("Double-clicks", self.var_dbl), ("Drags", self.var_drag), ("Scrolling", self.var_scroll),
            ("Keyboard shortcuts (Ctrl+S ...)", self.var_shortcuts),
            ("Error / message boxes + admin-window warning", self.var_dialogs),
            ("Mouse movement (for the narrated player)", self.var_mpath))]
        for i, c in enumerate(self.rec_checks):
            c.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
        ttk.Checkbutton(t, text="Show capture outline",
                        variable=self.var_preview, command=self.update_overlays).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.lock_capture = [self.cmb_mode, self.btn_area, self.chk_taskbar, self.cmb_after, self.spn_delay,
                             self.spn_width] + self.rec_checks

    def _tab_privacy(self):
        t = self.tab_privacy
        self.cmb_keys = self._grid(t, 0, "Keyboard", ttk.Combobox(t, textvariable=self.var_keys, state="readonly",
                                                                   values=list(KEYS)))
        box = ttk.LabelFrame(t, text="Hide in every screenshot", padding=6)
        box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        box.columnconfigure(0, weight=1)
        self.lst_masks = tk.Listbox(box, height=5, exportselection=False, activestyle="none")
        self.lst_masks.grid(row=0, column=0, columnspan=4, sticky="ew")
        self.lst_masks.bind("<<ListboxSelect>>", lambda e: self._mask_selected())
        self.btn_madd = ttk.Button(box, text="Add area", width=9, command=self.add_mask)
        self.btn_mwin = ttk.Button(box, text="Add window", width=11, command=self.add_window_mask)
        self.btn_mdel = ttk.Button(box, text="Remove", width=8, command=self.remove_mask)
        self.btn_mclr = ttk.Button(box, text="Clear", width=6, command=self.clear_masks)
        for i, b in enumerate((self.btn_madd, self.btn_mwin, self.btn_mdel, self.btn_mclr)):
            b.grid(row=1, column=i, pady=(4, 0), padx=(0 if i == 0 else 4, 0), sticky="w")
        self.cmb_mstyle = ttk.Combobox(box, textvariable=self.var_mstyle, state="readonly",
                                       values=list(core.MASK_STYLES.values()))
        self.cmb_mstyle.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.cmb_mstyle.bind("<<ComboboxSelected>>", lambda e: self._mask_style_changed())
        ttk.Label(box, text="Style applies to the selected mask (and to new ones). 'Add window' hides a window\n"
                            "wherever it moves. Faded is for de-emphasis only - it is still readable.",
                  foreground="gray", justify="left").grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))
        self.chk_ocr_on = ttk.Checkbutton(t, text="Use OCR (redact text, name unlabelled clicks)",
                                          variable=self.var_ocr_on, command=self._ocr_toggled)
        ocr = ttk.LabelFrame(t, labelwidget=self.chk_ocr_on, padding=6)
        ocr.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.ocr_checks = [ttk.Checkbutton(ocr, text=core.OCR_LABELS[k], variable=self.var_ocr[k],
                                           command=self.update_scope_label) for k in core.OCR_PATTERNS]
        for i, c in enumerate(self.ocr_checks):
            c.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
        r0 = (len(self.ocr_checks) + 1) // 2
        self.btn_secrets = ttk.Button(ocr, text="Hide common secrets", command=self.hide_common_secrets)
        self.btn_secrets.grid(row=r0, column=0, sticky="w", pady=(4, 0))
        w.Tip(self.btn_secrets, "One click: turns OCR on and ticks every kind above (needs Tesseract)")
        self.chk_ocr_labels = ttk.Checkbutton(ocr, text="Label clicks on unnamed controls with nearby text (OCR)",
                                              variable=self.var_ocr_labels)
        self.chk_ocr_labels.grid(row=r0 + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.var_ocr_note = tk.StringVar(value="")
        ttk.Label(ocr, textvariable=self.var_ocr_note, foreground="gray", wraplength=int(330 * self.scale),
                  justify="left").grid(row=r0 + 2, column=0, columnspan=2, sticky="w")
        ttk.Label(ocr, text="OCR is the slowest part of recording: it adds a few seconds per click, more with several "
                            "monitors or a slow computer. Steps are finished in the background, and the toolbar "
                            "counter shows how many are waiting.",
                  foreground="gray", wraplength=int(330 * self.scale), justify="left"
                  ).grid(row=r0 + 3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.lock_privacy = [self.cmb_keys, self.lst_masks, self.btn_madd, self.btn_mwin, self.btn_mdel, self.btn_mclr,
                             self.cmb_mstyle, self.chk_ocr_on, self.btn_secrets] + self.ocr_checks + [self.chk_ocr_labels]

    def _tab_report(self):
        t = self.tab_report
        f = ttk.Frame(t)
        for i, (k, label) in enumerate(rep.FORMATS.items()):
            ttk.Checkbutton(f, text=label, variable=self.var_fmt[k]).grid(row=i // 3, column=i % 3, sticky="w",
                                                                           padx=(0, 10))
        self._grid(t, 0, "Formats", f)
        self._grid(t, 1, "Wording", ttk.Combobox(t, textvariable=self.var_wording, state="readonly",
                                                 values=["Friendly", "Technical"], width=12))
        self._grid(t, 2, "Header", ttk.Entry(t, textvariable=self.var_header))
        self._grid(t, 3, "Footer", ttk.Entry(t, textvariable=self.var_footer))
        self._grid(t, 4, "Author", ttk.Entry(t, textvariable=self.var_author))
        self.cmb_focus = ttk.Combobox(t, textvariable=self.var_focus, state="readonly",
                                      values=list(core.FOCUS_MODES.values()))
        w.Tip(self.cmb_focus, "Blur the rest of the screen in the report pictures (the saved screenshots stay untouched)")
        lg = ttk.Frame(t)
        lg.columnconfigure(0, weight=1)
        ttk.Entry(lg, textvariable=self.var_logo).grid(row=0, column=0, sticky="ew")
        ttk.Button(lg, text="...", width=3, command=self.pick_logo).grid(row=0, column=1, padx=(4, 0))
        self._grid(t, 5, "Logo", lg)
        self._grid(t, 6, "", ttk.Checkbutton(t, text="Add environment appendix (OS, displays, ...)",
                                             variable=self.var_env))
        self._grid(t, 7, "Focus", self.cmb_focus)
        ttk.Label(t, text="Friendly: Click the \"Save\" button    Technical: Left click on \"Save\" (Button)",
                  foreground="gray").grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _tab_audio(self):
        t = self.tab_audio
        ttk.Label(t, text="Voice narration: click the microphone button on the toolbar while recording to talk "
                          "along with your steps. Each step keeps what you say before its click.",
                  wraplength=int(330 * self.scale), justify="left", foreground="#4a5560"
                  ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        dev = ttk.Frame(t)
        self.cmb_audio = ttk.Combobox(dev, textvariable=self.var_audio_dev, state="readonly", width=30)
        self.cmb_audio.pack(side="left", fill="x", expand=True)
        self.cmb_audio.bind("<<ComboboxSelected>>", lambda e: self._audio_device_changed())
        ttk.Button(dev, text="Refresh", command=self._audio_refresh, width=8).pack(side="left", padx=(4, 0))
        self._grid(t, 1, "Microphone", dev)
        test = ttk.Frame(t)
        self.btn_atest = ttk.Button(test, text="Test microphone", command=self._audio_test, width=17)
        self.btn_atest.pack(side="left")
        self.btn_aplay = ttk.Button(test, text="\u25b6 Play back", command=self._audio_play, width=12, state="disabled")
        self.btn_aplay.pack(side="left", padx=(6, 0))
        self._grid(t, 2, "Check", test)
        self.pb_level = ttk.Progressbar(t, maximum=100, length=200)
        self._grid(t, 3, "Level", self.pb_level)
        self.var_atest = tk.StringVar(value="Click Test, then speak: the bar should move.")
        ttk.Label(t, textvariable=self.var_atest, wraplength=int(330 * self.scale), justify="left"
                  ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 6))
        ttk.Checkbutton(t, text="Start every recording with the microphone on", variable=self.var_narrate
                        ).grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Label(t, text="(Normally it starts OFF; you switch it on with the toolbar button.)", foreground="gray"
                  ).grid(row=6, column=0, columnspan=2, sticky="w")
        asg = ttk.LabelFrame(t, text="Speech between two clicks goes with", padding=4)
        ttk.Radiobutton(asg, text="the next click (you say what you are about to do)", value="next",
                        variable=self.var_assign).pack(anchor="w")
        ttk.Radiobutton(asg, text="the previous click (you explain what just happened)", value="prev",
                        variable=self.var_assign).pack(anchor="w")
        asg.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        links = ttk.Frame(t)
        ttk.Button(links, text="Windows sound settings", command=lambda: self._open_ms("ms-settings:sound")
                   ).pack(side="left")
        ttk.Button(links, text="Microphone privacy", command=lambda: self._open_ms("ms-settings:privacy-microphone")
                   ).pack(side="left", padx=(6, 0))
        links.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(t, text="Voice is saved as-is: the hide tools and the privacy check do not cover it.",
                  foreground="gray", wraplength=int(330 * self.scale), justify="left"
                  ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._atest = None  # (Narrator, started_at, peak) while testing
        self._atest_file = None
        self._audio_refresh()

    def _audio_names(self):
        return [ta.DEFAULT_NAME] + [n for _i, n in ta.list_devices()]

    def _audio_refresh(self):
        names = self._audio_names()
        self.cmb_audio.configure(values=names)
        if self.var_audio_dev.get() not in names:
            self.var_audio_dev.set(ta.DEFAULT_NAME)  # the chosen microphone is not plugged in right now
        if not ta.available():
            self.var_atest.set("Voice recording needs Windows.")
            self.btn_atest.state(["disabled"])
        elif len(names) == 1:
            self.var_atest.set("Windows reports no microphone. Plug one in (or enable it in Windows sound settings), "
                               "then click Refresh.")

    def _audio_device_changed(self):
        name = self.var_audio_dev.get()
        ta.preferred = "" if name == ta.DEFAULT_NAME else name
        self.var_atest.set("Microphone changed. Click Test to check it.")

    def _open_ms(self, uri):
        try:
            os.startfile(uri)  # Windows only
        except Exception:
            self.toast("Open Windows Settings > System > Sound (or Privacy > Microphone).", 6)

    def _audio_test(self):
        if self._atest:
            self._audio_test_stop()
            return
        if self.rec:
            self.var_atest.set("Stop the recording first - the microphone is in use.")
            return
        n = ta.Narrator()
        ok, msg = n.start()
        if not ok:
            self.var_atest.set("Could not open the microphone: " + msg)
            return
        self._atest = [n, time.monotonic(), 0.0]
        self.btn_atest.configure(text="Stop test")
        self.btn_aplay.state(["disabled"])
        self.var_atest.set("Listening... speak now.")
        self._audio_tick()

    def _audio_tick(self):
        if not self._atest:
            return
        n, t0, peak = self._atest
        self.pb_level["value"] = int(n.level * 100)
        self._atest[2] = max(peak, n.level)
        if time.monotonic() - t0 > 12:
            self._audio_test_stop()
            return
        self.root.after(70, self._audio_tick)

    def _audio_test_stop(self):
        if not self._atest:
            return
        n, _t0, peak = self._atest
        self._atest = None
        import tempfile
        path = Path(tempfile.gettempdir()) / "telestep_mic_test.wav"
        saved = n.stop(path)
        self.pb_level["value"] = 0
        self.btn_atest.configure(text="Test microphone")
        if saved and peak >= 0.04:
            self._atest_file = path
            self.btn_aplay.state(["!disabled"])
            self.var_atest.set(f"Microphone works (loudest {int(peak * 100)}%). Play back to hear what it recorded.")
        elif saved:
            self.var_atest.set("The microphone opened but heard (almost) nothing. Check the device above, the "
                               "microphone's volume/mute in Windows sound settings, and Microphone privacy.")
        else:
            self.var_atest.set("The test recorded nothing: " + (n.error or "no audio"))

    def _audio_play(self):
        if self._atest_file and Path(self._atest_file).exists():
            ta.play(self._atest_file)

    def _tab_options(self):
        t = self.tab_options
        rows = [("Flash the frame when a screenshot is taken", self.var_flash),
                ("Play a click sound when a screenshot is taken", self.var_sound),
                ("Show screen overlays (capture area, taskbar, masks)", self.var_overlay),
                ("Hide toolbar and overlays from screenshots", self.var_hide)]
        for i, (txt, var) in enumerate(rows):
            cmd = self.update_overlays if var is self.var_overlay else (
                self.apply_capture_exclusion if var is self.var_hide else None)
            ttk.Checkbutton(t, text=txt, variable=var, command=cmd).grid(row=i, column=0, columnspan=2, sticky="w")
        tr = ttk.Frame(t)
        self.chk_tray = ttk.Checkbutton(tr, text="Tray icon", variable=self.var_tray, command=self.tray_toggled)
        self.chk_tray.grid(row=0, column=0, sticky="w")
        self.chk_hidetray = ttk.Checkbutton(tr, text="hide toolbar while recording", variable=self.var_hidetray)
        self.chk_hidetray.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.chk_closetray = ttk.Checkbutton(
            tr, text="close button sends it to the tray (Quit is in the tray menu)", variable=self.var_closetray)
        self.chk_closetray.grid(row=1, column=0, columnspan=3, sticky="w")
        if not self.tray.ok:
            self.chk_tray.state(["disabled"])
            self.chk_hidetray.state(["disabled"])
            self.chk_closetray.state(["disabled"])
            ttk.Label(tr, text="(pip install pystray)", foreground="gray").grid(row=0, column=2, sticky="w", padx=6)
        tr.grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(t, text="Minimize the toolbar to an icon", variable=self.var_compact,
                        command=self._sync_mode).grid(row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(t, text="Takes effect when Settings is collapsed.",
                  foreground="gray", wraplength=int(330 * self.scale), justify="left"
                  ).grid(row=9, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(t, text="Check for a newer version at startup (about once a week)",
                        variable=self.var_upd_check).grid(row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(t, text="Off by default. This is the only time Telestep uses the internet: one request to the project's "
                          "GitLab page, nothing about you or your recordings. It never downloads anything by itself.",
                  foreground="gray", wraplength=int(330 * self.scale), justify="left"
                  ).grid(row=11, column=0, columnspan=2, sticky="w")
        op = ttk.Frame(t)
        op.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(op, text="Toolbar opacity").grid(row=0, column=0, sticky="w")
        sc = ttk.Scale(op, from_=30, to=100, orient="horizontal", length=int(150 * self.scale),
                       command=self._opacity_dragged)
        sc.set(self.var_opacity.get())
        sc.grid(row=0, column=1, padx=8)
        sc.bind("<ButtonPress-1>", lambda e: setattr(self, "_adjusting_opacity", True), add="+")
        sc.bind("<ButtonRelease-1>", lambda e: (setattr(self, "_adjusting_opacity", False), self._apply_opacity()), add="+")
        self.scale_opacity = sc
        pct = ttk.Frame(op)
        pct.grid(row=0, column=2, sticky="w")
        ttk.Label(pct, textvariable=self.var_opacity).pack(side="left")
        ttk.Label(pct, text="%").pack(side="left")
        ttk.Checkbutton(op, text="Solid while the pointer is over it", variable=self.var_solid_hover,
                        command=self._apply_opacity).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Label(op, text="Applies when Settings is collapsed (the toolbar stays solid while Settings is open).",
                  foreground="gray", wraplength=int(330 * self.scale), justify="left"
                  ).grid(row=2, column=0, columnspan=3, sticky="w")
        hk = ttk.LabelFrame(t, text="Hotkeys - click a box, then press the keys (Esc cancels, Backspace resets)",
                            padding=6)
        hk.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        names = {"pause": "Pause / resume", "stop": "Stop and save", "note": "Add note", "shot": "Screenshot",
                 "undo": "Delete last step", "comment": "Comment on next step"}
        self.hk_entries = []
        for i, k in enumerate(cfg.DEFAULT_HOTKEYS):
            ttk.Label(hk, text=names[k]).grid(row=i // 2, column=(i % 2) * 2, sticky="w", pady=1)
            e = w.HotkeyEntry(hk, self.var_hk[k], cfg.DEFAULT_HOTKEYS[k], width=16,
                              validate=lambda spec, k=k: self._hotkey_conflict(k, spec, names))
            e.grid(row=i // 2, column=(i % 2) * 2 + 1, padx=(4, 12), pady=1)
            self.hk_entries.append(e)
        self.var_admin = tk.StringVar(value="Running as administrator: " + ("yes" if core.is_admin() else
                                     "no (clicks inside admin windows can't be recorded)"))
        ttk.Label(t, textvariable=self.var_admin, foreground="gray", wraplength=int(340 * self.scale),
                  justify="left").grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _hotkey_conflict(self, key, spec, names):
        for other, var in self.var_hk.items():
            if other != key and var.get().strip().lower() == spec:
                return f'Already used for "{names[other]}"'
        return None

    TAB_ACTIVE, TAB_IDLE, TAB_HOVER, TAB_ACCENT = "#ffffff", "#d5dae0", "#e6e9ed", "#1565c0"

    def _make_tabbar(self):
        """Separate, high-contrast tabs: the current one is white, bold, blue-underlined; the rest are grey."""
        self.tabbar = tk.Frame(self.cfg, bg="#b8bfc7", padx=0, pady=0)
        self.tabbar.pack(fill="x", before=self.nb, pady=(0, 0))
        self._tabs = []
        for tab in (self.tab_general, self.tab_capture, self.tab_audio, self.tab_privacy, self.tab_report,
                    self.tab_options):
            cell = tk.Frame(self.tabbar, bd=0)
            lbl = tk.Label(cell, text=self.nb.tab(tab, "text"), padx=10, pady=5, cursor="hand2")
            bar = tk.Frame(cell, height=3)
            lbl.pack(fill="x")
            bar.pack(fill="x")
            cell.pack(side="left", padx=(0, 3), pady=(3, 0))
            for wd in (cell, lbl, bar):
                wd.bind("<Button-1>", lambda e, t=tab: self.nb.select(t))
            lbl.bind("<Enter>", lambda e, t=tab: self._paint_tabs(hover=t))
            lbl.bind("<Leave>", lambda e: self._paint_tabs())
            self._tabs.append((tab, lbl, bar))
        mini = tk.Label(self.tabbar, text="\u25b2", bg="#b8bfc7", fg="#263238", padx=9, pady=4,
                        cursor="hand2", font=("Segoe UI", 10))
        mini.pack(side="right", padx=(0, 4), pady=(3, 0))
        mini.bind("<Button-1>", lambda e: self._collapse_settings())
        mini.bind("<Enter>", lambda e: mini.configure(bg="#e6e9ed"))
        mini.bind("<Leave>", lambda e: mini.configure(bg="#b8bfc7"))
        w.Tip(mini, "Collapse to the mini toolbar")
        self._paint_tabs()

    def _collapse_settings(self):
        self.var_cfg.set(False)
        self.toggle_config()

    def _paint_tabs(self, hover=None):
        cur = self.nb.select()
        for tab, lbl, bar in self._tabs:
            on = str(tab) == str(cur)
            bg = self.TAB_ACTIVE if on else (self.TAB_HOVER if tab is hover else self.TAB_IDLE)
            lbl.configure(bg=bg, fg="#0d47a1" if on else "#4a5560",
                          font=("Segoe UI", 9, "bold" if on else "normal"))
            bar.configure(bg=self.TAB_ACCENT if on else bg)

    def _tab_changed(self):
        self._paint_tabs()
        if not self._ocr_checked and self.nb.select() == str(self.tab_privacy):
            self._ocr_checked = True
            self.var_ocr_note.set("Checking for Tesseract...")

            def probe():  # can be slow the first time (antivirus scans tesseract.exe): never on the UI thread
                self._ocr_result = bool(core.ocr_available())
            threading.Thread(target=probe, daemon=True).start()

    # ------------------------------------------------------------------ widget helpers
    def _set_icon(self, widget, kind):
        on, off = self.icons[kind]
        widget.configure(image=(str(on), "disabled", str(off)))

    def _icon_btn(self, parent, kind, tip, cmd, side="left"):
        b = ttk.Button(parent, style="Icon.TButton", command=cmd, takefocus=False)
        self._set_icon(b, kind)
        w.Tip(b, tip)
        b.pack(side=side, padx=1)
        return b

    @staticmethod
    def _enable(widget, on):
        if isinstance(widget, tk.Listbox):
            widget.configure(state="normal" if on else "disabled")
        else:
            widget.state(["!disabled"] if on else ["disabled"])

    def apply_capture_exclusion(self):
        """Best effort: ask Windows to leave the toolbar and overlays out of screen captures."""
        w.exclude_from_capture(self.root, self.var_hide.get())
        self.overlays.apply_affinity()

    # ------------------------------------------------------------------ icon (compact) toolbar
    def _build_compact(self):
        """A tiny always-on-top badge that grows into Record / Pause / Stop while the pointer is on it."""
        self.cframe = ttk.Frame(self.root, padding=2, relief="solid", borderwidth=1)
        self.c_icon = ttk.Label(self.cframe, cursor="fleur")
        self.c_icon.grid(row=0, column=0, padx=2, pady=2)
        self.c_ctl = ttk.Frame(self.cframe)
        self.cbtn_rec = self._icon_btn(self.c_ctl, "record", "Record (start a new session)", self.start)
        self.cbtn_pause = self._icon_btn(self.c_ctl, "pause", "Pause / resume", self.toggle_pause)
        self.cbtn_stop = self._icon_btn(self.c_ctl, "stop", "Stop and save", self.stop)
        # the microphone indicator stays visible on the collapsed badge while recording: click it to switch
        self.c_rec = ttk.Label(self.cframe, cursor="hand2")  # stays visible while recording: red dot / amber pause
        self.c_rec.bind("<Button-1>", lambda e: self.toggle_pause())
        w.Tip(self.c_rec, "Recording. Click to pause / resume.")
        self.c_mic = ttk.Label(self.cframe, cursor="hand2")
        self.c_mic.bind("<Button-1>", lambda e: self.toggle_mic())
        w.Tip(self.c_mic, "Microphone: red = recording your voice. Click to switch on / off.")
        ttk.Separator(self.c_ctl, orient="vertical").pack(side="left", fill="y", padx=3, pady=2)
        self.cbtn_settings = self._icon_btn(self.c_ctl, "gear", "Settings", self.show_settings)
        for wd in (self.cframe, self.c_icon):  # drag the badge to move it
            wd.bind("<ButtonPress-1>", self._c_press)
            wd.bind("<B1-Motion>", self._c_drag)

    def _badge(self, state):
        """Idle: the Telestep icon.  Recording: a red tile with a white dot.  Paused: an amber tile with a pause sign."""
        if state not in self._badges:
            from PIL import Image, ImageDraw, ImageTk
            size = round(26 * self.scale)
            S = size * 4
            if state in ("rec", "paused"):
                img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                d.rounded_rectangle([0, 0, S - 1, S - 1], radius=S * 0.22,
                                    fill=(229, 57, 53, 255) if state == "rec" else (245, 158, 11, 255))
                if state == "rec":
                    d.ellipse([S * .28, S * .28, S * .72, S * .72], fill=(255, 255, 255, 255))
                else:
                    for x0 in (.30, .55):
                        d.rounded_rectangle([S * x0, S * .26, S * (x0 + .15), S * .74], radius=S * .03,
                                            fill=(255, 255, 255, 255))
                base = img.resize((size, size), Image.LANCZOS)
            else:
                try:
                    import telestep_help
                    base = Image.open(telestep_help.logo_path(small=True)).convert("RGBA").resize((size, size), Image.LANCZOS)
                except Exception:
                    base = Image.new("RGBA", (size, size), (30, 90, 168, 255))
            self._badges[state] = ImageTk.PhotoImage(base)
        return self._badges[state]

    def _compact_refresh(self):
        self.c_icon.configure(image=self._badge("idle"))  # the app logo always stays
        idle = self.state == "idle"
        if not idle:
            img = self._badge(self.state)
            self.c_rec.configure(image=img)
            self.c_rec.image = img
        if idle:  # the Record button only exists while it can be used
            if not self.cbtn_rec.winfo_ismapped():
                self.cbtn_rec.pack(side="left", padx=1, before=self.cbtn_pause)
        else:
            self.cbtn_rec.pack_forget()
        self._enable(self.cbtn_rec, idle)
        self._enable(self.cbtn_pause, not idle)
        self._enable(self.cbtn_stop, not idle)
        self._mic_key = None
        self._show_mic(bool(self.rec and self.rec.mic_on and not self.rec.paused))
        self._set_icon(self.cbtn_pause, "resume" if self.state == "paused" else "pause")

    def enter_compact(self):
        if self.var_cfg.get():  # Settings must be collapsed first
            self.var_cfg.set(False)
            self.toggle_config()
        self.var_compact.set(True)
        self._sync_mode()

    def show_settings(self):
        """Open Settings from the icon bar: the full toolbar shows while Settings is open, and the icon comes back
        when it is collapsed (the icon-mode choice itself is not changed)."""
        self.var_cfg.set(True)
        self.toggle_config()

    def leave_compact(self):
        self.var_compact.set(False)
        self._sync_mode()

    def _monitor_at(self, x, y):
        for m in self.screens[1:]:
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                return m
        return None

    def _sync_mode(self):
        """Show the icon toolbar (compact) or the full one.  Settings open always means the full toolbar."""
        want = bool(self.var_compact.get() and not self.var_cfg.get())
        if want == self._compact_on:
            return
        if self._compact_on and self._cx0 is not None:
            x, y = self._cx0, self._cy0  # where the icon sat, not where the expanded bar was pushed to
        else:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        visible = self.root.state() == "normal"
        if visible:
            self.root.withdraw()  # Windows only applies a style change like this to a hidden window
        self._expanded = False
        if want:
            self.main.grid_remove()
            self.c_ctl.grid_remove()
            self.cframe.grid(row=0, column=0, sticky="nsew")
            self.root.overrideredirect(True)
        else:
            self.cframe.grid_remove()
            self.main.grid(row=0, column=0, sticky="nsew")
            self.root.overrideredirect(False)
        self._compact_on = want
        self.root.update_idletasks()
        m = self._monitor_at(x, y)
        if m and not want:  # keep the full toolbar on screen
            x = max(m["left"], min(x, m["left"] + m["width"] - self.root.winfo_reqwidth() - 2))
        self.root.geometry(f"+{int(x)}+{int(y)}")
        self._cx0, self._cy0 = int(x), int(y)
        if visible:
            self.root.deiconify()
        try:
            self.root.attributes("-topmost", True)
            if not want:
                self.root.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        self.apply_capture_exclusion()  # the window may have been re-created: re-apply what Windows forgot
        self._apply_opacity()
        self._compact_refresh()
        self.root.update_idletasks()
        self._toolbar_moved()

    def _expand_compact(self, on):
        if not self._compact_on or on == self._expanded:
            return
        self._expanded = on
        if on:
            self.c_ctl.grid(row=0, column=3, padx=(2, 0))
        else:
            self.c_ctl.grid_remove()
        self.root.update_idletasks()
        x, y = self._cx0, self._cy0
        if on:
            m = self._monitor_at(x, y)
            if m:  # near the right edge it grows leftwards instead of off the screen
                x = min(x, m["left"] + m["width"] - self.root.winfo_reqwidth() - 2)
        self.root.geometry(f"+{int(x)}+{int(y)}")
        self.root.update_idletasks()
        self._toolbar_moved()

    def _toolbar_moved(self):
        """The window's rectangle changed: clicks on it must stay out of the recording straight away."""
        self.toolbar_rect = w.window_screen_rect(self.root)
        if self.rec:
            self.rec.ignore_rects = [self.toolbar_rect] if self.toolbar_rect else []

    def _c_press(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _c_drag(self, e):
        if not self._drag:
            return
        x, y = e.x_root - self._drag[0], e.y_root - self._drag[1]
        self.root.geometry(f"+{int(x)}+{int(y)}")
        self._cx0, self._cy0 = int(x), int(y)

    def _compact_hover(self, hover):
        """Expand while the pointer is on the badge; shrink back a moment after it leaves."""
        if not self._compact_on:
            return
        if hover:
            self._leave_t = 0.0
            self._expand_compact(True)
        elif self._expanded:
            now = time.monotonic()
            if not self._leave_t:
                self._leave_t = now
            elif now - self._leave_t > 0.6:
                self._leave_t = 0.0
                self._expand_compact(False)

    def _opacity_dragged(self, value):
        self.var_opacity.set(int(round(float(value) / 5.0) * 5))  # steps of 5%
        self._apply_opacity()

    def _apply_opacity(self):
        """Toolbar see-through level.  Applies only while Settings is collapsed; with Settings open the toolbar is
        solid (the slider shows the level while it is being dragged).  The pointer on it also makes it solid
        when that option is on."""
        if self._adjusting_opacity:
            solid = False  # dragging the slider: show the chosen level
        else:  # only the collapsed toolbar is see-through; with Settings open it is solid
            solid = self.var_cfg.get() or (self._hover and self.var_solid_hover.get())
        try:
            self.root.attributes("-alpha", 1.0 if solid else self.var_opacity.get() / 100.0)
        except tk.TclError:
            pass

    def ask(self, kind, msg):
        return getattr(messagebox, kind)(TITLE, msg, parent=self.root)

    def over_toolbar(self, pos):
        r = self.toolbar_rect
        return bool(pos and r and r[0] <= pos[0] < r[2] and r[1] <= pos[1] < r[3])

    def toast(self, text, seconds=6.0):
        self.var_toast.set(text)
        self.toast_until = time.monotonic() + seconds
        self.lbl_toast.grid(row=1, column=0, sticky="ew", pady=(4, 0))

    def flash_active(self):
        return time.monotonic() < self.flash_until

    # ------------------------------------------------------------------ settings <-> widgets
    def gather(self):
        d = cfg.merge(cfg.DEFAULTS, {})
        mode, monitor = self.current_mode()
        d.update({
            "base_dir": str(self.base), "capture_mode": mode, "monitor": monitor,
            "region": list(self.region) if self.region else None, "exclude_taskbar": self.var_taskbar.get(),
            "after_mode": AFTER[self.var_after.get()], "after_delay_ms": self._int(self.var_delay, 700),
            "max_width": self._int(self.var_width, 1600), "dbl": self.var_dbl.get(), "drag": self.var_drag.get(),
            "scroll": self.var_scroll.get(), "shortcuts": self.var_shortcuts.get(),
            "watch_dialogs": self.var_dialogs.get(), "narrate": self.var_narrate.get(), "mouse_path": self.var_mpath.get(), "audio_assign": self.var_assign.get(),
            "audio_device": "" if self.var_audio_dev.get() == ta.DEFAULT_NAME else self.var_audio_dev.get(), "masks": [m.to_dict() for m in self.masks],
            "mask_style": self.style_key(), "key_mode": KEYS[self.var_keys.get()],
            "ocr": {k: v.get() for k, v in self.var_ocr.items()}, "ocr_labels": self.var_ocr_labels.get(), "ocr_enabled": self.var_ocr_on.get(), "formats": {k: v.get() for k, v in self.var_fmt.items()},
            "review_after_stop": self.var_review.get(), "wording": self.wording(),
            "template": {"header": self.var_header.get().strip(), "footer": self.var_footer.get().strip(),
                         "logo": self.var_logo.get().strip(), "author": self.var_author.get().strip(),
                         "environment": self.var_env.get(), "focus": self.focus_key()},
            "hotkeys": {k: v.get().strip() for k, v in self.var_hk.items()}, "flash": self.var_flash.get(),
            "update_check": self.var_upd_check.get(), "update_last": self.data.get("update_last", ""),
            "sound": self.var_sound.get(), "tray": self.var_tray.get(), "hide_in_tray": self.var_hidetray.get(),
            "close_to_tray": self.var_closetray.get(),
            "hide_from_capture": self.var_hide.get(), "overlays": self.var_overlay.get(),
            "toolbar_opacity": self.var_opacity.get(), "compact_toolbar": self.var_compact.get(), "toolbar_solid_hover": self.var_solid_hover.get(),
            "toolbar_pos": self.data.get("toolbar_pos"), "presets": self.data.get("presets", {}),
        })
        return d

    @staticmethod
    def _int(var, default):
        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return default

    def wording(self):
        return "friendly" if self.var_wording.get() == "Friendly" else "technical"

    def style_key(self):
        return _inv(core.MASK_STYLES, self.var_mstyle.get())

    def apply(self, d):
        """Load a (preset) settings dict into the widgets."""
        d = cfg.merge(cfg.merge(cfg.DEFAULTS, {}), d)
        self.region = tuple(d["region"]) if d["region"] else None
        self.masks = [core.Mask.from_dict(m) for m in d["masks"]]
        self.refresh_screens()
        mode, monitor = d["capture_mode"], d["monitor"]
        self.var_mode.set(next((k for k, v in self.choices.items() if v == (mode, monitor)), "Screen under click"))
        self.var_taskbar.set(d["exclude_taskbar"])
        self.var_after.set(_inv(AFTER, d["after_mode"]))
        self.var_delay.set(d["after_delay_ms"])
        self.var_width.set(d["max_width"])
        for var, key in ((self.var_dbl, "dbl"), (self.var_drag, "drag"), (self.var_scroll, "scroll"),
                         (self.var_shortcuts, "shortcuts"), (self.var_dialogs, "watch_dialogs"),
                         (self.var_narrate, "narrate"), (self.var_assign, "audio_assign"), (self.var_mpath, "mouse_path"),
                         (self.var_review, "review_after_stop"), (self.var_flash, "flash"), (self.var_sound, "sound"),
                         (self.var_overlay, "overlays"), (self.var_hide, "hide_from_capture")):
            var.set(d[key])
        self.var_opacity.set(max(30, min(100, int(d.get("toolbar_opacity", 100)))))
        self.var_solid_hover.set(d.get("toolbar_solid_hover", True))
        self.var_compact.set(bool(d.get("compact_toolbar", False)))
        if hasattr(self, "scale_opacity"):
            self.scale_opacity.set(self.var_opacity.get())
            self._apply_opacity()
        if hasattr(self, "cframe"):
            self._sync_mode()
        self.var_keys.set(_inv(KEYS, d["key_mode"]))
        self.var_mstyle.set(core.MASK_STYLES[core.canon_style(d["mask_style"])])
        for k, v in self.var_ocr.items():
            v.set(d["ocr"].get(k, False))
        self.var_ocr_labels.set(d.get("ocr_labels", True))
        self.var_ocr_on.set(d.get("ocr_enabled", True))
        if hasattr(self, "chk_ocr_labels"):
            self._ocr_sync()
        for k, v in self.var_fmt.items():
            v.set(d["formats"].get(k, False))
        self.var_wording.set("Friendly" if d["wording"] == "friendly" else "Technical")
        t = d["template"]
        self.var_header.set(t["header"])
        self.var_footer.set(t["footer"])
        self.var_author.set(t["author"])
        self.var_logo.set(t["logo"])
        self.var_env.set(t["environment"])
        self.var_focus.set(core.FOCUS_MODES.get(t.get("focus", "off"), core.FOCUS_MODES["off"]))
        for k, v in self.var_hk.items():
            v.set(d["hotkeys"].get(k, cfg.DEFAULT_HOTKEYS[k]))
        self._enable(self.btn_area, self.state == "idle" and self.current_mode()[0] == "region")
        self.refresh_masks()
        self.update_scope_label()
        self.apply_capture_exclusion()
        self.update_overlays()

    def persist(self):
        self.data = self.gather()
        cfg.save(self.data, self.settings_path)

    # ---- presets ----
    def refresh_presets(self):
        names = sorted(self.data["presets"])
        self.cmb_preset["values"] = ["(none)"] + names
        if self.var_preset.get() not in ["(none)"] + names:
            self.var_preset.set("(none)")

    def load_preset(self):
        name = self.var_preset.get()
        if name in self.data["presets"]:
            self.apply(self.data["presets"][name])

    def save_preset(self, name=None):
        name = name or simpledialog.askstring(TITLE, "Preset name:", parent=self.root)
        name = (name or "").strip()
        if not name or name == "(none)":
            return
        self.data["presets"][name] = cfg.preset_of(self.gather())
        self.var_preset.set(name)
        self.refresh_presets()
        self.persist()

    def delete_preset(self):
        name = self.var_preset.get()
        if name in self.data["presets"]:
            del self.data["presets"][name]
            self.var_preset.set("(none)")
            self.refresh_presets()
            self.persist()

    # ------------------------------------------------------------------ toolbar position
    def place_toolbar(self):
        pos = self.data.get("toolbar_pos")
        rw = self.root.winfo_reqwidth()
        if pos and self.screens:
            x, y = pos
            if any(m["left"] - rw + 60 <= x <= m["left"] + m["width"] - 60 and m["top"] <= y <= m["top"] + m["height"] - 40
                   for m in self.screens[1:]):
                self.root.geometry(f"+{int(x)}+{int(y)}")
                return
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"+{max(0, (sw - rw) // 2)}+8")

    def _track_position(self):
        pos = (self.root.winfo_x(), self.root.winfo_y())
        if pos != self._pos_seen:
            self._pos_seen, self._pos_changed = pos, time.monotonic()
        elif self._pos_changed and time.monotonic() - self._pos_changed > 1.0:
            self._pos_changed = 0.0
            if (self.data.get("toolbar_pos") != list(pos) and self.root.state() == "normal"
                    and not self._expanded):  # an expanded icon may have been pushed off its spot
                self.data["toolbar_pos"] = list(pos)
                cfg.save(self.data, self.settings_path)

    # ------------------------------------------------------------------ state
    def set_state(self, state):
        self.state = state
        idle = state == "idle"
        self._enable(self.btn_rec, idle)
        for b in (self.btn_pause, self.btn_stop, self.btn_note, self.btn_shot, self.btn_mic):
            self._enable(b, not idle)
        self._set_icon(self.btn_pause, "resume" if state == "paused" else "pause")
        self.ent_title.config(state="normal" if idle else "disabled")
        for wd in (self.btn_browse, self.cmb_preset, self.btn_psave, self.btn_pdel) + tuple(self.hk_entries):
            if isinstance(wd, w.HotkeyEntry):
                wd.config(state="readonly" if idle else "disabled")
            elif isinstance(wd, ttk.Entry):
                wd.config(state="normal" if idle else "disabled")
            else:
                self._enable(wd, idle)
        for wd in self.lock_capture + self.lock_privacy:
            if isinstance(wd, ttk.Combobox):
                wd.config(state="readonly" if idle else "disabled")
            elif isinstance(wd, tk.Listbox):
                wd.config(state="normal" if idle else "disabled")
            else:
                self._enable(wd, idle)
        self._enable(self.btn_area, idle and self.current_mode()[0] == "region")
        self._ocr_sync()
        if hasattr(self, "c_icon"):
            self._compact_refresh()
        self.tray.set_state(state)
        self.update_summary()

    def _ocr_sync(self):
        """The OCR ticks are only usable while idle and the master switch is on; the ticks themselves are kept."""
        on = self.state == "idle" and self.var_ocr_on.get()
        for wd in self.ocr_checks + [self.chk_ocr_labels]:
            self._enable(wd, on)

    def hide_common_secrets(self):
        """One click: OCR on and every pattern ticked (IPs, MACs, keys, e-mail, card and ID numbers)."""
        self.var_ocr_on.set(True)
        for k in core.COMMON_SECRETS:
            if k in self.var_ocr:
                self.var_ocr[k].set(True)
        self._ocr_sync()
        self.update_scope_label()
        if core.ocr_status() is False:  # the cached answer: asking Tesseract again can freeze the window for seconds
            messagebox.showinfo("Telestep", "Everything is ticked, but OCR needs the Tesseract program and "
                                "pytesseract, which are not installed here.\n\nSee INSTALL.md > Optional extras.",
                                parent=self.root)

    def _ocr_toggled(self):
        self._ocr_sync()
        self.update_scope_label()

    def toggle_config(self):
        if self.var_cfg.get():
            self.cfg.grid(row=2, column=0, sticky="ew")
            self.refresh_screens()
        else:
            self.cfg.grid_remove()
        self._sync_mode()
        self._apply_opacity()
        self.update_summary()
        self.root.update_idletasks()
        self.update_overlays()

    # ------------------------------------------------------------------ capture area / masks
    def refresh_screens(self):
        """Rebuild the capture dropdown (monitors can be plugged/unplugged)."""
        self.screens = w.list_screens()
        self.choices = {"Screen under click": ("screen", 1), "All screens": ("all", 1)}
        for i, m in enumerate(self.screens[1:], 1):
            self.choices[f"Screen {i} ({m['width']}x{m['height']} at {m['left']},{m['top']})"] = ("monitor", i)
        self.choices["Window under click"] = ("window", 1)
        self.choices["Custom area"] = ("region", 1)
        self.cmb_mode["values"] = list(self.choices)
        if self.var_mode.get() not in self.choices:
            self.var_mode.set("Screen under click")

    def current_mode(self):
        return self.choices.get(self.var_mode.get(), ("screen", 1))

    def capture_opts(self):
        mode, monitor = self.current_mode()
        return sr.CaptureOpts(mode, monitor, self.region, self.var_taskbar.get(), list(self.masks))

    def scope_text(self):
        """Short description of the capture area (shown in the overlay tag)."""
        mode, _ = self.current_mode()
        if mode == "region" and self.region:
            l, t, r, b = self.region
            return f"Custom area {r - l}x{b - t}"
        text = self.var_mode.get().split(" (")[0]
        if self.var_taskbar.get():
            text += " - no taskbar"
        return text

    def update_scope_label(self):
        mode, _ = self.current_mode()
        parts = [self.var_mode.get()]
        if mode == "region":
            if self.region:
                l, t, r, b = self.region
                parts[0] = f"Custom area {r - l}x{b - t} at {l},{t}"
            else:
                parts[0] = "Custom area (none selected)"
        if self.var_taskbar.get():
            parts.append("taskbar excluded")
        if self.masks:
            parts.append(f"{len(self.masks)} mask{'s' if len(self.masks) != 1 else ''}")
        if self.var_ocr_on.get() and any(v.get() for v in self.var_ocr.values()):
            parts.append("OCR redaction")
        self.var_scope.set(" | ".join(parts))
        self.update_summary()

    def update_summary(self):
        """One quiet line under the toolbar: what Record is about to start with (hidden while Settings is open)."""
        if not hasattr(self, "lbl_summary"):
            return
        show = self.state == "idle" and not self.var_cfg.get() and not self._saving
        if not show:
            self.lbl_summary.grid_remove()
            return
        mode, _ = self.current_mode()
        area = self.var_mode.get().split(" (")[0]
        if mode == "region":
            area = "Custom area" + ("" if self.region else " (none yet)")
        bits = [self.var_title.get().strip() or "Untitled", area]
        if self.var_taskbar.get():
            bits[-1] += ", no taskbar"
        priv = [f"{len(self.masks)} mask{'s' if len(self.masks) != 1 else ''}"] if self.masks else []
        if self.var_ocr_on.get() and any(v.get() for v in self.var_ocr.values()):
            priv.append("OCR redaction")
        bits.append("Privacy: " + ", ".join(priv) if priv else "No redaction")
        fmts = [k.upper() for k in self.formats()]
        bits.append("Review, then export" if self.var_review.get() else ("Saves " + "/".join(fmts) if fmts else "Saves no files"))
        self.var_summary.set("  ·  ".join(bits))
        self.lbl_summary.grid(row=3, column=0, sticky="ew", pady=(4, 0))

    def on_mode_change(self, _event=None):
        self._enable(self.btn_area, self.current_mode()[0] == "region")
        self.update_scope_label()
        self.update_overlays()
        if self.current_mode()[0] == "region" and not self.region:
            self.root.after(50, self.select_area)  # prompt right away the first time

    def select_area(self):
        r = w.pick_area(self.root, self.screens)
        if r:
            self.region = r
        self.update_scope_label()

    def refresh_masks(self):
        sel = self.lst_masks.curselection()
        self.lst_masks.configure(state="normal")
        self.lst_masks.delete(0, "end")
        for m in self.masks:
            self.lst_masks.insert("end", m.describe())
        if sel and sel[0] < len(self.masks):
            self.lst_masks.selection_set(sel[0])
        if self.state != "idle":
            self.lst_masks.configure(state="disabled")

    def add_mask(self, rect=None):
        r = rect or w.pick_area(self.root, self.screens)
        if r:
            self.masks.append(core.Mask(rect=tuple(r), style=self.style_key()))
        self.refresh_masks()
        self.update_scope_label()

    def add_window_mask(self, title=None):
        title = title or w.WindowPicker(self.root).result
        if title:
            self.masks.append(core.Mask(title=title, style=self.style_key()))
        self.refresh_masks()
        self.update_scope_label()

    def add_rule(self, d):
        """A hide area saved from the review window: the same part of windows with this title is hidden from now on."""
        self.masks.append(core.Mask.from_dict(d))
        self.refresh_masks()
        self.update_scope_label()
        self.persist()

    def remove_mask(self):
        sel = self.lst_masks.curselection()
        if sel and sel[0] < len(self.masks):
            del self.masks[sel[0]]
        self.refresh_masks()
        self.update_scope_label()

    def clear_masks(self):
        self.masks = []
        self.refresh_masks()
        self.update_scope_label()

    def _mask_selected(self):
        sel = self.lst_masks.curselection()
        if sel and sel[0] < len(self.masks):
            self.var_mstyle.set(core.MASK_STYLES[core.canon_style(self.masks[sel[0]].style)])

    def _mask_style_changed(self):
        sel = self.lst_masks.curselection()
        if sel and sel[0] < len(self.masks):
            self.masks[sel[0]].style = self.style_key()
            self.refresh_masks()

    def pick_logo(self):
        f = filedialog.askopenfilename(parent=self.root, title="Logo",
                                       filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if f:
            self.var_logo.set(f)

    # ------------------------------------------------------------------ actions
    def record_opts(self):
        hk = {}
        for k, v in self.var_hk.items():
            spec = v.get().strip().lower()
            try:
                core.parse_hotkey(spec)
                hk[k] = spec
            except ValueError:
                hk[k] = cfg.DEFAULT_HOTKEYS[k]
                v.set(hk[k])
        return sr.RecordOpts(
            key_mode=KEYS[self.var_keys.get()], max_width=self._int(self.var_width, 1600),
            after_mode=AFTER[self.var_after.get()], after_delay_ms=self._int(self.var_delay, 700),
            dbl=self.var_dbl.get(), drag=self.var_drag.get(), scroll=self.var_scroll.get(),
            shortcuts=self.var_shortcuts.get(), watch_dialogs=self.var_dialogs.get(), narrate=self.var_narrate.get(), audio_assign=self.var_assign.get(),
            mouse_path=self.var_mpath.get(),
            ocr_kinds=[k for k, v in self.var_ocr.items() if v.get()] if self.var_ocr_on.get() else [], ocr_style=self.style_key(),
            wording=self.wording(), ocr_labels=self.var_ocr_labels.get() and self.var_ocr_on.get(), hotkeys=hk)

    def start(self):
        if self._saving:
            return
        mode, _ = self.current_mode()
        if mode == "region" and not self.region:
            self.ask("showerror", "Choose a custom area first (Settings > Capture > Select area).")
            return
        self.report_title = self.var_title.get().strip() or "Recorded steps"
        self.out_dir = self.base / core.session_dir_name(self.var_title.get())  # <datestamp>_<project>
        try:
            self.rec = sr.Recorder(self.out_dir, self.capture_opts(), self.record_opts(), self.report_title)
            self.rec.ignore_titles = {TITLE, w.NOTE_TITLE, w.PICK_TITLE, w.WINPICK_TITLE}
            self.toolbar_rect = w.window_screen_rect(self.root)
            self.rec.ignore_rects = [self.toolbar_rect] if self.toolbar_rect else []
            self.rec.slow_log = self._dlog
            o = self.record_opts()
            self._rec_t0 = time.monotonic()
            self._dlog(f"----- Recording \"{self.report_title}\" started {dt.datetime.now():%Y-%m-%d %H:%M:%S} -----\n"
                       f"      folder: {self.out_dir}\n"
                       f"      capture: {self.var_mode.get()} | {max(len(w.list_screens()) - 1, 1)} screen(s) | "
                       f"redaction: {', '.join(o.ocr_kinds) or 'off'} | label OCR: {'on' if o.ocr_labels else 'off'} | "
                       f"max width {o.max_width}px | focus: {self.focus_key()}")
            self.rec.start()
        except Exception as e:
            self.rec = None
            self.ask("showerror", f"Could not start recording:\n{e}")
            return
        failed = getattr(self.rec, "hotkeys_failed", [])
        if failed:
            self.toast("Hotkey(s) already used by another program: " + ", ".join(failed))
        self.persist()
        self.var_cfg.set(False)  # collapse settings; the overlays show what is captured
        self.toggle_config()
        self.set_state("rec")
        if self.var_tray.get() and self.var_hidetray.get() and self.tray.icon:
            self.root.withdraw()

    def toggle_pause(self):
        if self.rec:
            self.rec.toggle_pause()

    def toggle_mic(self):
        """Narration on/off: the first click opens the microphone, later clicks mute and unmute it."""
        if self.rec:
            if not self.rec.set_mic(not self.rec.mic_on):
                return  # the reason arrives as a toast
            self.toast("Microphone ON - talk while you work; each step keeps what you say before its click."
                       if self.rec.mic_on else "Microphone off.", 4)
            self._show_mic(self.rec.mic_on and not self.rec.paused)

    def _show_mic(self, on):
        """`on` = the microphone is really listening (switched on and not paused)."""
        recording = self.state != "idle"
        key = (bool(on), recording)
        if key == getattr(self, "_mic_key", None):
            return
        self._mic_key = key
        self._pulse_i = -1
        if on:
            self._pulse_mic()
        else:
            self._set_icon(self.btn_mic, "mic_off")
            self.c_mic.configure(image=self.mic_off_big)
            self.c_mic.image = self.mic_off_big
        if recording:
            self.c_rec.grid(row=0, column=1, padx=(2, 0), pady=2)
            self.c_mic.grid(row=0, column=2, padx=(2, 2), pady=2)
        else:
            self.c_rec.grid_remove()
            self.c_mic.grid_remove()

    def _pulse_mic(self):
        """While the microphone is open its icon ripples, so it can never be mistaken for 'off'."""
        if not (getattr(self, "_mic_key", None) and self._mic_key[0]):
            return
        i = int(time.monotonic() * 8) % len(self.mic_frames)
        if i == self._pulse_i:
            return
        self._pulse_i = i
        fr = self.mic_frames[i]
        self.btn_mic.configure(image=(str(fr), "disabled", str(self.icons["mic_off"][1])))
        self.c_mic.configure(image=fr)
        self.c_mic.image = fr

    def shot(self, from_menu=False):
        if self.rec:
            self.rec.manual_shot(from_menu=from_menu)

    def add_note(self):
        if not self.rec:
            return
        rec = self.rec
        was_paused = rec.paused
        rec.paused = True  # don't record clicks made while the note box is open
        self.root.deiconify()
        try:
            dlg = w.NoteDialog(self.root)
        finally:
            rec.paused = was_paused
        if dlg.result:
            rec.add_note(dlg.result, dlg.level)

    def _maybe_check_updates(self):
        """Once a week, only if switched on: ask GitLab for the newest release (background thread, never installs)."""
        import datetime as _dt
        if not self.var_upd_check.get():
            return
        try:
            last = _dt.date.fromisoformat(self.data.get("update_last") or "2000-01-01")
        except ValueError:
            last = _dt.date(2000, 1, 1)
        if (_dt.date.today() - last).days < 7:
            return
        import telestep_update

        def work():
            self._upd_result = telestep_update.check(core.VERSION)

        threading.Thread(target=work, daemon=True).start()
        self.data["update_last"] = _dt.date.today().isoformat()
        self.persist()

    def add_comment(self):
        """A one-line remark attached to the next step you record (shown under its caption)."""
        if not self.rec:
            return
        rec = self.rec
        was_paused = rec.paused
        rec.paused = True
        self.root.deiconify()
        try:
            dlg = w.NoteDialog(self.root, comment=True)
        finally:
            rec.paused = was_paused
        if dlg.result:
            rec.add_comment(dlg.result)
            self.toast("Comment saved - it goes with your next step.", 3)

    def formats(self):
        return [k for k, v in self.var_fmt.items() if v.get()]

    def stop(self):
        if not self.rec or self._saving:
            return
        rec, self.rec = self.rec, None
        self._saving = rec
        self._stop_result = None
        self.var_status.set("Saving...")
        self.root.update_idletasks()

        def work():  # the recorder finishes its queued steps here, so the window stays responsive
            try:
                self._stop_result = rec.stop()
            except Exception as e:
                self._stop_result = e
        threading.Thread(target=work, daemon=True).start()
        self._wait_save()

    def _wait_save(self):
        rec = self._saving
        if self._stop_result is None:
            n = rec.pending()
            self.var_status.set(f"Saving... {n} step{'s' if n != 1 else ''} left" if n else "Saving...")
            self.root.after(200, self._wait_save)
            return
        res, self._saving = self._stop_result, None
        if isinstance(res, Exception):
            self.set_state("idle")
            self.root.deiconify()
            self.ask("showerror", f"Saving failed:\n{res}\n\nThe screenshots so far are in the session folder.")
            return
        self._finish_stop(res)

    def _finish_stop(self, sess):
        self._dlog(f"----- Recording \"{getattr(sess, 'title', '')}\" saved: {sess.count()} steps, "
                   f"{time.monotonic() - getattr(self, '_rec_t0', time.monotonic()):.0f}s from start to saved -----")
        self.last_session = sess
        self.set_state("idle")
        self.root.deiconify()
        self.var_folder.set(str(self.base))
        if not sess.steps:
            self.idle_msg = "No steps recorded"
            return
        self.persist()
        if self.var_review.get():
            self.idle_msg = f"{sess.count()} steps - review"
            self.open_review(sess)
            return
        tpl = self.template()
        results = rep.export(sess, tpl, self.formats())
        bad = {k: v for k, v in results.items() if v.startswith("FAILED")}
        if bad:
            self.ask("showerror", "Some outputs failed:\n" + "\n".join(f"{k}: {v}" for k, v in bad.items())
                     + f"\n\nThe screenshots and session.json are safe in the session folder.\nDetails: {sess.dir / 'save_errors.log'}")
        self.idle_msg = f"Saved {sess.count()} steps" if not bad else "Saved with errors"

    def _dlog(self, msg):
        try:
            if self._dbg:
                self._dbg.write(f"[{dt.datetime.now():%H:%M:%S}] {msg}\n")
                self._dbg.flush()
        except Exception:
            pass

    def template(self):
        return rep.Template(wording=self.wording(), header=self.var_header.get().strip(),
                            footer=self.var_footer.get().strip(), logo=self.var_logo.get().strip(),
                            author=self.var_author.get().strip(), environment=self.var_env.get(),
                            focus=self.focus_key())

    def focus_key(self):
        return next((k for k, v in core.FOCUS_MODES.items() if v == self.var_focus.get()), "off")

    def _seed_template(self, session):
        """A recording nobody has exported yet has no report settings of its own: start from the toolbar's."""
        if not session.settings.get("template"):
            session.settings["template"] = self.template().to_dict()
            session.settings.setdefault("wording", self.wording())

    def open_review(self, session=None):
        if not isinstance(session, Session):
            d = w.SessionPicker(self.root, self.base).result  # Telestep's own list, newest first
            if not d:
                return
            try:
                session = Session.load(d)
            except Exception as e:
                self.ask("showerror", f"Could not open that folder:\n{e}")
                return
            session.settings.setdefault("wording", self.wording())
        import telestep_review
        self._seed_template(session)
        if self.review is not None:
            try:
                self.review.destroy()
            except tk.TclError:
                pass
        self.review = telestep_review.ReviewWindow(self.root, session, formats={k: v.get() for k, v in self.var_fmt.items()},
                                                   on_rule=self.add_rule)
        self.out_dir = session.dir
        return self.review

    def _bar_menu(self, e):
        """Right-click anywhere on the toolbar: the common actions."""
        m = tk.Menu(self.root, tearoff=0)
        rec = self.rec
        if rec:
            m.add_command(label="Resume" if rec.paused else "Pause", accelerator=self.var_hk["pause"].get(),
                          command=self.toggle_pause)
            m.add_command(label="Stop and save", accelerator=self.var_hk["stop"].get(), command=self.stop)
            m.add_separator()
            m.add_command(label="Add note...", accelerator=self.var_hk["note"].get(), command=self.add_note)
            m.add_command(label="Comment on next step...", accelerator=self.var_hk["comment"].get(),
                          command=self.add_comment)
            m.add_command(label="Take screenshot now", accelerator=self.var_hk["shot"].get(),
                          command=lambda: self.shot(from_menu=True))
        else:
            m.add_command(label="Start recording", command=self.start)
            m.add_separator()
            m.add_command(label="Open a saved recording...", command=self.open_review)
            if self.last_session:
                m.add_command(label="Review the last recording", command=lambda: self.open_review(self.last_session))
        m.add_command(label="Show recordings folder in File Explorer", command=self.open_folder)
        m.add_separator()
        m.add_command(label="Full toolbar" if self._compact_on else "Minimize to an icon",
                      command=self.leave_compact if self._compact_on else self.enter_compact)
        m.add_command(label="Hide settings" if self.var_cfg.get() else "Show settings",
                      command=lambda: (self.var_cfg.set(not self.var_cfg.get()), self.toggle_config()))
        m.add_command(label="Help", accelerator="F1", command=self.open_help)
        m.add_command(label="About", command=lambda: self.open_help("about"))
        m.add_separator()
        if self.tray.icon:
            m.add_command(label="Hide to tray", command=self.root.withdraw)
        m.add_command(label="Quit", command=lambda: self.on_close(force=True))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def open_help(self, start="help"):
        import telestep_help
        if getattr(self, "help_win", None) is not None:
            try:
                self.help_win.destroy()
            except tk.TclError:
                pass
        self.help_win = telestep_help.HelpWindow(self.root, start, getattr(self, "_dbg_path", None))
        return self.help_win

    def browse(self):
        d = filedialog.askdirectory(parent=self.root, title=TITLE, initialdir=str(self.base))
        if d:
            self.base = Path(d)
            self.var_folder.set(str(self.base))

    def open_folder(self):
        target = self.out_dir if self.out_dir and self.out_dir.exists() else self.base
        target.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(target))  # Windows only
        except Exception as e:
            self.ask("showerror", f"Could not open folder:\n{e}")

    def tray_toggled(self):
        if self.var_tray.get():
            self.tray.start()
            if not self.tray.icon:
                self.toast("Could not create the tray icon. Check the hidden-icons (^) area of the taskbar, "
                           "or that pystray is installed.", 8)
        else:
            self.tray.stop()

    # ------------------------------------------------------------------ periodic sync
    def _setting_up(self):
        """Preview outline only when Settings is open on Capture/Privacy AND Telestep itself has the focus."""
        try:
            return bool(self.var_cfg.get() and self.var_preview.get()
                        and self.root.state() == "normal"
                        and self.nb.select() in (str(self.tab_capture), str(self.tab_privacy))
                        and self._app_active())
        except tk.TclError:
            return False

    def _app_active(self):
        active = core.own_process_active()
        return (self.root.focus_displayof() is not None) if active is None else active

    def update_overlays(self):
        if not self.var_overlay.get():
            self.overlays.hide()
        elif self.rec:
            self.overlays.update("paused" if self.rec.paused else "rec")
        elif self._setting_up():
            self.overlays.update("preview")  # only while the user is actively setting up
        else:
            self.overlays.hide()

    def _handle_events(self):
        rec = self.rec
        while rec and not rec.events.empty():
            ev = rec.events.get_nowait()
            if ev[0] == "captured":
                if self.var_flash.get():
                    self.flash_until = time.monotonic() + 0.18
                if self.var_sound.get():
                    try:
                        import winsound
                        threading.Thread(target=winsound.Beep, args=(1400, 25), daemon=True).start()
                    except Exception:
                        pass
            elif ev[0] == "note":
                self.add_note()
            elif ev[0] == "comment":
                self.add_comment()
            elif ev[0] == "undone":
                self.toast(f"Deleted last step: {ev[1]}", 3)
            elif ev[0] == "warn":
                self.toast(ev[1], 12)
            elif ev[0] == "mic":
                self._show_mic(bool(ev[1] and self.rec and not self.rec.paused))
            elif ev[0] == "backlog":
                msg = {"warn": f"Telestep is catching up ({ev[2]} clicks waiting). Pause a moment between clicks.",
                       "hold": f"Too many clicks waiting ({ev[2]}): new clicks are NOT being recorded until Telestep "
                               "catches up. Wait for the counter to drop.",
                       "resumed": "Caught up - recording again."}[ev[1]]
                self._dlog(f"backlog {ev[1]} ({ev[2]} queued)")
                self.toast(msg, 15 if ev[1] == "hold" else 8)
        while not self.requests.empty():
            req = self.requests.get_nowait()
            if req == "quit":
                self.on_close(force=True)
                return
            if req == "show":
                self.root.deiconify()
                self.root.lift()
            elif req == "start" and not self.rec:
                self.start()
            elif req == "pause":
                self.toggle_pause()
            elif req == "stop":
                self.stop()
            elif req == "note":
                self.add_note()
            elif req == "shot":
                self.shot(from_menu=True)

    def poll(self):
        """Keep the UI in sync with the recorder (hotkeys included) and refresh overlays."""
        now = time.monotonic()
        gap = now - self._last_poll
        self._last_poll = now
        if self._dbg:
            try:
                import faulthandler  # if nothing runs for 3 s, dump where the UI thread is stuck (repeats)
                faulthandler.dump_traceback_later(3.0, repeat=True, file=self._dbg)
                if 1.5 < gap < 120:
                    tab = self.nb.tab(self.nb.select(), "text") if self.var_cfg.get() else "-"
                    self._dbg.write(f"[{dt.datetime.now():%H:%M:%S}] window was unresponsive for {gap:.1f}s "
                                    f"(settings tab: {tab}, state: {self.state})\n")
            except Exception:
                pass
        if getattr(self, "_upd_result", None) is not None:
            r, self._upd_result = self._upd_result, None
            self._dlog(f"update check: {r.get('status')} {r.get('version', '')} {r.get('error', '')}".strip())
            if r.get("status") == "newer":
                self.toast(f"Telestep {r['version'].lstrip('v')} is available. Help > About > Check for updates "
                           "opens the download page.", 15)
        if self._ocr_result is not None:
            self.var_ocr_note.set("Tesseract found - OCR features are active." if self._ocr_result
                                  else "Tesseract is not installed, so the OCR options do nothing yet (see README).")
            self._ocr_result = None
        self.toolbar_rect = w.window_screen_rect(self.root)
        if self.var_opacity.get() < 100 or self._compact_on:
            hover = self.over_toolbar(core.cursor_pos())
            if hover != self._hover:
                self._hover = hover
                self._apply_opacity()
            self._compact_hover(hover)
        rec = self.rec
        self._handle_events()
        rec = self.rec
        if rec:
            rec.ignore_rects = [self.toolbar_rect] if self.toolbar_rect else []
            if rec.stop_evt.is_set():  # stop hotkey
                self.stop()
            else:
                st = "paused" if rec.paused else "rec"
                if st != self.state:
                    self.set_state(st)
                n = rec.session.count()
                q = rec.pending()  # clicks captured but still being processed (they join the count shortly)
                tail = f" +{q}" if q else ""
                if rec.holding:
                    self.var_status.set(f"⏳ Catching up +{q}")
                else:
                    self.var_status.set(f"● REC  {n}{tail} steps" if st == "rec" else f"‖ Paused  {n}{tail}")
                self._show_mic(rec.mic_on and not rec.paused)
                self._pulse_mic()
        elif self.state == "idle":
            self.var_status.set(self.idle_msg)
            self._show_mic(False)
        if self.var_toast.get() and time.monotonic() > self.toast_until:
            self.var_toast.set("")
            self.lbl_toast.grid_remove()
        self._track_position()
        t0 = time.monotonic()
        self.update_overlays()
        if self._dbg and time.monotonic() - t0 > 0.4:
            self._dbg.write(f"[{dt.datetime.now():%H:%M:%S}] overlay update took {time.monotonic() - t0:.1f}s\n")
        self._poll_job = self.root.after(120, self.poll)

    def on_close(self, force=False):
        if not force and self.var_tray.get() and self.var_closetray.get() and self.tray.icon:
            self.root.withdraw()  # keep running in the tray; "Show toolbar" / double-click the icon brings it back
            return
        if self.rec:
            if not self.ask("askyesno", "Recording is in progress. Stop and save before closing?"):
                return
            self.stop()
        self.persist()
        self.tray.stop()
        self.overlays.hide()
        try:
            self.root.after_cancel(self._poll_job)
        except Exception:
            pass
        if self._dbg:
            try:
                import faulthandler
                faulthandler.cancel_dump_traceback_later()
                self._dbg.close()
                if self._dbg_path.stat().st_size == 0:
                    self._dbg_path.unlink()
            except Exception:
                pass
        self.root.destroy()


def support_requested(argv=None, exe=None):
    """Support mode (one-button recorder that produces a ZIP for IT): --support, or an exe named *Support*.exe."""
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if "--support" in argv:
        return True
    name = exe if exe is not None else (sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
    return "support" in Path(name).stem.lower()


def main():
    import sys
    support = support_requested()
    multi = "--allow-multiple" in sys.argv[1:] or os.environ.get("TELESTEP_MULTI")
    if not multi and not core.single_instance("Telestep_Support" if support else "Telestep"):
        core.tell_already_running("Telestep Support" if support else TITLE)
        return
    if support:
        import telestep_support
        telestep_support.main()
        return
    root = tk.Tk()
    App(root, os.environ.get("TELESTEP_SETTINGS"))
    root.mainloop()


if __name__ == "__main__":
    main()
