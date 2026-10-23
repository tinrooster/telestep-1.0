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
               "help": "#0277bd"}


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
            self._dbg = open(self._dbg_path, "a", buffering=1, encoding="utf-8")
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
        self.var_keys = tk.StringVar(value=_inv(KEYS, d["key_mode"]))
        self.var_mstyle = tk.StringVar(value=core.MASK_STYLES.get(d["mask_style"], core.MASK_STYLES["solid"]))
        self.var_ocr = {k: tk.BooleanVar(value=d["ocr"].get(k, False)) for k in core.OCR_PATTERNS}
        self.var_ocr_labels = tk.BooleanVar(value=d["ocr_labels"])
        self.var_fmt = {k: tk.BooleanVar(value=d["formats"].get(k, False)) for k in rep.FORMATS}
        self.var_wording = tk.StringVar(value="Friendly" if d["wording"] == "friendly" else "Technical")
        t = d["template"]
        self.var_header, self.var_footer = tk.StringVar(value=t["header"]), tk.StringVar(value=t["footer"])
        self.var_author, self.var_logo = tk.StringVar(value=t["author"]), tk.StringVar(value=t["logo"])
        self.var_env = tk.BooleanVar(value=t["environment"])
        self.var_flash, self.var_sound = tk.BooleanVar(value=d["flash"]), tk.BooleanVar(value=d["sound"])
        self.var_tray, self.var_hidetray = tk.BooleanVar(value=d["tray"]), tk.BooleanVar(value=d["hide_in_tray"])
        self.var_closetray = tk.BooleanVar(value=d["close_to_tray"])
        self.var_overlay = tk.BooleanVar(value=d["overlays"])
        self.var_preview = tk.BooleanVar(value=True)  # outline while setting up (this session only)
        self.var_hide = tk.BooleanVar(value=d["hide_from_capture"])
        self.var_hk = {k: tk.StringVar(value=d["hotkeys"].get(k, cfg.DEFAULT_HOTKEYS[k])) for k in cfg.DEFAULT_HOTKEYS}
        self.var_cfg = tk.BooleanVar(value=False)
        self.var_scope = tk.StringVar(value="")
        self.var_status = tk.StringVar(value=self.idle_msg)
        self.var_toast = tk.StringVar(value="")

        ttk.Style().configure("Icon.TButton", padding=2)
        isz = round(20 * self.scale)
        self.icons = {k: (w.make_icon(k, c, isz), w.make_icon(k, "#b8b8b8", isz)) for k, c in ICON_COLORS.items()}

        self.tray = Tray(self)
        main = ttk.Frame(root, padding=(6, 4))
        main.grid(sticky="nsew")
        main.columnconfigure(0, weight=1)
        bar = ttk.Frame(main)
        bar.grid(row=0, column=0, sticky="ew")
        self.btn_rec = self._icon_btn(bar, "record", "Record (start a new session)", self.start)
        self.btn_pause = self._icon_btn(bar, "pause", "Pause / resume", self.toggle_pause)
        self.btn_stop = self._icon_btn(bar, "stop", "Stop and save", self.stop)
        self.btn_note = self._icon_btn(bar, "note", "Add a note, warning or tip", self.add_note)
        self.btn_shot = self._icon_btn(bar, "camera", "Take a screenshot now (no click needed)", self.shot)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=5, pady=2)
        ttk.Label(bar, textvariable=self.var_status, width=16, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self.btn_gear = ttk.Checkbutton(bar, style="Toolbutton", variable=self.var_cfg, command=self.toggle_config,
                                        takefocus=False)
        self._set_icon(self.btn_gear, "gear")
        w.Tip(self.btn_gear, "Settings")
        self.btn_gear.pack(side="right", padx=1)
        self.btn_folder = self._icon_btn(bar, "folder", "Show the recordings folder in File Explorer", self.open_folder, side="right")
        self.btn_review = self._icon_btn(bar, "review", "Review, edit and export a recording (pick from a list)", self.open_review,
                                         side="right")
        self.btn_help = self._icon_btn(bar, "help", "Help and About (F1)", self.open_help, side="right")
        self.lbl_toast = ttk.Label(main, textvariable=self.var_toast, foreground="#b45309",
                                   wraplength=int(360 * self.scale), justify="left")

        self.cfg = ttk.Frame(main, padding=(0, 8, 0, 0))
        ttk.Style(self.root).layout("Plain.TNotebook.Tab", [])  # our own, clearer tab strip is drawn instead
        self.nb = ttk.Notebook(self.cfg, style="Plain.TNotebook")
        self.nb.pack(fill="both", expand=True)
        self.tab_general, self.tab_capture = ttk.Frame(self.nb, padding=8), ttk.Frame(self.nb, padding=8)
        self.tab_privacy, self.tab_report = ttk.Frame(self.nb, padding=8), ttk.Frame(self.nb, padding=8)
        self.tab_options = ttk.Frame(self.nb, padding=8)
        for tab, name in ((self.tab_general, "General"), (self.tab_capture, "Capture"), (self.tab_privacy, "Privacy"),
                          (self.tab_report, "Report"), (self.tab_options, "Options")):
            tab.columnconfigure(1, weight=1)
            self.nb.add(tab, text=name)
        self._tab_general()
        self._tab_capture()
        self._tab_privacy()
        self._tab_report()
        self._tab_options()
        self._make_tabbar()
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._tab_changed())

        self.overlays = w.OverlayManager(self)
        self.refresh_screens()
        self.refresh_presets()
        self.refresh_masks()
        self.update_scope_label()
        self.set_state("idle")
        root.update_idletasks()
        self.place_toolbar()
        self.apply_capture_exclusion()
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
            ("Error / message boxes + admin-window warning", self.var_dialogs))]
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
        ocr = ttk.LabelFrame(t, text="Redact text automatically (OCR)", padding=6)
        ocr.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.ocr_checks = [ttk.Checkbutton(ocr, text=core.OCR_LABELS[k], variable=self.var_ocr[k],
                                           command=self.update_scope_label) for k in core.OCR_PATTERNS]
        for i, c in enumerate(self.ocr_checks):
            c.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
        ttk.Checkbutton(ocr, text="Label clicks on unnamed controls with nearby text (OCR)",
                        variable=self.var_ocr_labels).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.var_ocr_note = tk.StringVar(value="")
        ttk.Label(ocr, textvariable=self.var_ocr_note, foreground="gray", wraplength=int(330 * self.scale),
                  justify="left").grid(row=3, column=0, columnspan=2, sticky="w")
        self.lock_privacy = [self.cmb_keys, self.lst_masks, self.btn_madd, self.btn_mwin, self.btn_mdel, self.btn_mclr,
                             self.cmb_mstyle] + self.ocr_checks

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
        lg = ttk.Frame(t)
        lg.columnconfigure(0, weight=1)
        ttk.Entry(lg, textvariable=self.var_logo).grid(row=0, column=0, sticky="ew")
        ttk.Button(lg, text="...", width=3, command=self.pick_logo).grid(row=0, column=1, padx=(4, 0))
        self._grid(t, 5, "Logo", lg)
        self._grid(t, 6, "", ttk.Checkbutton(t, text="Add environment appendix (OS, displays, ...)",
                                             variable=self.var_env))
        ttk.Label(t, text="Friendly: Click the \"Save\" button    Technical: Left click on \"Save\" (Button)",
                  foreground="gray").grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

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
        hk = ttk.LabelFrame(t, text="Hotkeys - click a box, then press the keys (Esc cancels, Backspace resets)",
                            padding=6)
        hk.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        names = {"pause": "Pause / resume", "stop": "Stop and save", "note": "Add note", "shot": "Screenshot",
                 "undo": "Delete last step"}
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
        for tab in (self.tab_general, self.tab_capture, self.tab_privacy, self.tab_report, self.tab_options):
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
            "watch_dialogs": self.var_dialogs.get(), "masks": [m.to_dict() for m in self.masks],
            "mask_style": self.style_key(), "key_mode": KEYS[self.var_keys.get()],
            "ocr": {k: v.get() for k, v in self.var_ocr.items()}, "ocr_labels": self.var_ocr_labels.get(), "formats": {k: v.get() for k, v in self.var_fmt.items()},
            "review_after_stop": self.var_review.get(), "wording": self.wording(),
            "template": {"header": self.var_header.get().strip(), "footer": self.var_footer.get().strip(),
                         "logo": self.var_logo.get().strip(), "author": self.var_author.get().strip(),
                         "environment": self.var_env.get()},
            "hotkeys": {k: v.get().strip() for k, v in self.var_hk.items()}, "flash": self.var_flash.get(),
            "sound": self.var_sound.get(), "tray": self.var_tray.get(), "hide_in_tray": self.var_hidetray.get(),
            "close_to_tray": self.var_closetray.get(),
            "hide_from_capture": self.var_hide.get(), "overlays": self.var_overlay.get(),
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
                         (self.var_review, "review_after_stop"), (self.var_flash, "flash"), (self.var_sound, "sound"),
                         (self.var_overlay, "overlays"), (self.var_hide, "hide_from_capture")):
            var.set(d[key])
        self.var_keys.set(_inv(KEYS, d["key_mode"]))
        self.var_mstyle.set(core.MASK_STYLES.get(d["mask_style"], core.MASK_STYLES["solid"]))
        for k, v in self.var_ocr.items():
            v.set(d["ocr"].get(k, False))
        self.var_ocr_labels.set(d.get("ocr_labels", True))
        for k, v in self.var_fmt.items():
            v.set(d["formats"].get(k, False))
        self.var_wording.set("Friendly" if d["wording"] == "friendly" else "Technical")
        t = d["template"]
        self.var_header.set(t["header"])
        self.var_footer.set(t["footer"])
        self.var_author.set(t["author"])
        self.var_logo.set(t["logo"])
        self.var_env.set(t["environment"])
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
            if self.data.get("toolbar_pos") != list(pos) and self.root.state() == "normal":
                self.data["toolbar_pos"] = list(pos)
                cfg.save(self.data, self.settings_path)

    # ------------------------------------------------------------------ state
    def set_state(self, state):
        self.state = state
        idle = state == "idle"
        self._enable(self.btn_rec, idle)
        for b in (self.btn_pause, self.btn_stop, self.btn_note, self.btn_shot):
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
        self.tray.set_state(state)

    def toggle_config(self):
        if self.var_cfg.get():
            self.cfg.grid(row=2, column=0, sticky="ew")
            self.refresh_screens()
        else:
            self.cfg.grid_remove()
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
        if any(v.get() for v in self.var_ocr.values()):
            parts.append("OCR redaction")
        self.var_scope.set(" | ".join(parts))

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
            self.var_mstyle.set(core.MASK_STYLES.get(self.masks[sel[0]].style, core.MASK_STYLES["solid"]))

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
            shortcuts=self.var_shortcuts.get(), watch_dialogs=self.var_dialogs.get(),
            ocr_kinds=[k for k, v in self.var_ocr.items() if v.get()], ocr_style=self.style_key(),
            wording=self.wording(), ocr_labels=self.var_ocr_labels.get(), hotkeys=hk)

    def start(self):
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

    def formats(self):
        return [k for k, v in self.var_fmt.items() if v.get()]

    def stop(self):
        if not self.rec:
            return
        self.var_status.set("Saving...")
        self.root.update_idletasks()
        rec, self.rec = self.rec, None
        sess = rec.stop()
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

    def template(self):
        return rep.Template(wording=self.wording(), header=self.var_header.get().strip(),
                            footer=self.var_footer.get().strip(), logo=self.var_logo.get().strip(),
                            author=self.var_author.get().strip(), environment=self.var_env.get())

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
        if self.review is not None:
            try:
                self.review.destroy()
            except tk.TclError:
                pass
        self.review = telestep_review.ReviewWindow(self.root, session, formats={k: v.get() for k, v in self.var_fmt.items()})
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
        self.help_win = telestep_help.HelpWindow(self.root, start)
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
            elif ev[0] == "undone":
                self.toast(f"Deleted last step: {ev[1]}", 3)
            elif ev[0] == "warn":
                self.toast(ev[1], 12)
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
        if self._ocr_result is not None:
            self.var_ocr_note.set("Tesseract found - OCR features are active." if self._ocr_result
                                  else "Tesseract is not installed, so the OCR options do nothing yet (see README).")
            self._ocr_result = None
        self.toolbar_rect = w.window_screen_rect(self.root)
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
                self.var_status.set(f"● REC  {n} steps" if st == "rec" else f"‖ Paused  {n}")
        elif self.state == "idle":
            self.var_status.set(self.idle_msg)
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
    if support_requested():
        import telestep_support
        telestep_support.main()
        return
    root = tk.Tk()
    App(root, os.environ.get("TELESTEP_SETTINGS"))
    root.mainloop()


if __name__ == "__main__":
    main()
