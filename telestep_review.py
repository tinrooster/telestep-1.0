"""
telestep_review.py - review / edit a recorded session, then export it.

  * delete, exclude (reversible), reorder steps; edit captions; add section headings and note /
    warning / tip callouts
  * black out (or soften / pixelate / ...) a region of one screenshot or of every screenshot
  * switch between friendly and technical wording, set header / footer / logo, pick formats, export

Open it from the toolbar (list icon), automatically after Stop, or:  python telestep_recorder.py --review <folder>
"""
import dataclasses
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import telestep_core as core
import telestep_privacy as priv
from telestep_marks import MarkMixin
import telestep_report as rep
import telestep_widgets as w
from telestep_model import Session, Step, new_id

KIND_LABEL = {"click": "Click", "dblclick": "Double-click", "drag": "Drag", "scroll": "Scroll", "shortcut": "Keys",
              "type": "Typing", "shot": "Screenshot", "dialog": "Dialog", "note": "Note", "section": "Section"}
LEVEL_LABEL = {"note": "Note", "warning": "Warning", "tip": "Tip"}
PREVIEW_W, PREVIEW_H = 640, 340


class ReviewWindow(tk.Toplevel, MarkMixin):
    def __init__(self, master, session, formats=None, own_root=False, support=False, on_done=None, on_cancel=None,
                 on_rule=None):
        """`support=True` is the cut-down 'check before sending' version used by Support mode: no report options,
        a 'Looks good - create the ZIP' button (calls `on_done`) and Back (calls `on_cancel`)."""
        super().__init__(master)
        self.s = session
        self.own_root = own_root
        self.support, self.on_done, self.on_cancel = support, on_done, on_cancel
        self.on_rule = on_rule  # callable(mask dict): remember a hide area for future recordings (main app)
        self.title("Check your recording before it is sent" if support else f"Telestep - Review: {session.title}")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.minsize(min(960, sw - 40), min(640, sh - 80))
        self.geometry(f"{min(1120, sw - 40)}x{min(740, sh - 80)}")
        self.exported = {}
        self._photo = None
        self._cur = None  # selected step
        self._txt_wording = "friendly"  # wording the caption box was loaded with
        self._sel_rect = None  # canvas rect id
        self._sel_start = None
        self._scale, self._off = 1.0, (0, 0)
        self._img_size = (1, 1)
        tpl = rep.Template.from_settings(session.settings)
        self.tpl = tpl
        self.var_title = tk.StringVar(value=session.title)
        self.var_wording = tk.StringVar(value="Friendly" if tpl.wording == "friendly" else "Technical")
        self.var_which = tk.StringVar(value="before")
        self.var_view = tk.StringVar(value="whole")   # whole | close (close-up around the click)
        self.var_zoom = tk.StringVar(value="100%")
        self.var_focus = tk.StringVar(value=core.FOCUS_MODES.get(tpl.focus, core.FOCUS_MODES["off"]))
        self._crop = (0, 0, 1, 1)                      # part of the screenshot on screen (image pixels)
        self.var_style = tk.StringVar(value=core.MASK_STYLES["pixelate_fine"])
        self.var_all = tk.BooleanVar(value=False)
        self.var_level = tk.StringVar(value="Note")
        self.var_header = tk.StringVar(value=tpl.header)
        self.var_footer = tk.StringVar(value=tpl.footer)
        self.var_author = tk.StringVar(value=tpl.author)
        self.var_logo = tk.StringVar(value=tpl.logo)
        self.var_env = tk.BooleanVar(value=tpl.environment)
        self.var_verified = tk.StringVar(value=tpl.verified)
        self.var_check = tk.BooleanVar(value=bool(session.settings.get("privacy_check", True)))
        self.var_comment = tk.StringVar()
        self._init_marks()  # mark-up tools (telestep_marks.py): sets var_tool, selection state ...
        self.var_docstyle = tk.StringVar(value=rep.STYLES.get(tpl.style, rep.STYLES["report"]))
        self._edits = 0  # bumps when pictures are changed (masks) so "unexported changes" is noticed
        self._exported_sig = None
        fm = formats or {"md": True, "docx": True}
        self.var_fmt = {k: tk.BooleanVar(value=bool(fm.get(k, False))) for k in rep.FORMATS}
        self._build()
        self.refresh()
        self._style_changed()
        self.update_idletasks()  # open big enough that every control (the picture included) is visible
        rw, rh = self.winfo_reqwidth(), self.winfo_reqheight()
        self.minsize(min(rw, sw - 40, 960), min(rh, sh - 80, 640))
        self.geometry(f"{min(max(rw, 1120), sw - 40)}x{min(max(rh, 740), sh - 80)}")
        self._opened_sig = self._state_sig()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Return>", self._return_key)
        self.bind("<Control-Return>", lambda e: self.export())
        self.bind("<Delete>", lambda e: self.delete_selected() if self._tree_focus() else None)  # canvas has its own
        self.bind("<Alt-Up>", lambda e: self.move(-1))
        self.bind("<Alt-Down>", lambda e: self.move(1))
        self.bind("<Control-s>", lambda e: self.save())

    # ------------------------------------------------------------------ layout
    def _build(self):
        if not self.support:
            # packed first, at the bottom, so it can never be squeezed out when the window is small
            self.actionbar = ttk.Frame(self, padding=(8, 6, 8, 8))
            self.actionbar.pack(side="bottom", fill="x")
        root = ttk.Frame(self, padding=6)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        top = ttk.Frame(root)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Title").grid(row=0, column=0, padx=(0, 6))
        ent = ttk.Entry(top, textvariable=self.var_title)
        ent.grid(row=0, column=1, sticky="ew")
        ent.bind("<FocusOut>", lambda e: self._set_title())
        self._wording_widgets = [ttk.Label(top, text="Wording")]
        self._wording_widgets[0].grid(row=0, column=2, padx=(12, 6))
        cb = ttk.Combobox(top, textvariable=self.var_wording, values=["Friendly", "Technical"], width=10,
                          state="readonly")
        cb.grid(row=0, column=3)
        cb.bind("<<ComboboxSelected>>", lambda e: self._wording_changed())
        self._wording_widgets.append(cb)

        pan = ttk.PanedWindow(root, orient="horizontal")
        pan.grid(row=1, column=0, sticky="nsew")

        # ---- left: step list ----
        left = ttk.Frame(pan)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Style(self).configure("Review.Treeview", rowheight=30)  # air between the entries
        self.tree = ttk.Treeview(left, columns=("use", "n", "kind", "cap"), show="headings", selectmode="extended",
                                 style="Review.Treeview")
        for col, text, width, anchor in (("use", "In report", 62, "center"), ("n", "#", 36, "e"),
                                         ("kind", "Type", 84, "w"), ("cap", "Caption", 300, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "cap"))
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("stripe", background="#f1f5fa")  # every other plain step
        self.tree.tag_configure("skip", foreground="#9aa0a6", background="#f3f3f3")
        self.tree.tag_configure("section", background="#e8eef7", font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("note", background="#eef6ff")
        self.tree.tag_configure("warning", background="#fff4e0")
        self.tree.tag_configure("tip", background="#eaf7ee")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<Button-3>", self._tree_menu)
        self.tree.bind("<Button-1>", self._tree_click, add="+")
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])
        bar = ttk.Frame(left)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for text, cmd in (("Up", lambda: self.move(-1)), ("Down", lambda: self.move(1)),
                          ("Delete", self.delete_selected), ("Leave out", self.toggle_skip),
                          ("+ Section", self.add_section), ("+ Note", self.add_note)):
            b = ttk.Button(bar, text=text, command=cmd, width=len(text) + 2 if len(text) < 8 else 11)
            b.pack(side="left", padx=(0, 4))
            if text == "Leave out":
                self.btn_skip = b
        self.mb_more = ttk.Menubutton(bar, text="More", width=7)
        self.mb_more.pack(side="left")
        self.mb_more.configure(menu=self._more_menu(self.mb_more))
        ttk.Label(left, text="\u2611 = in the report    \u2610 = left out (greyed). Click the box, or use the button, to switch.",
                  foreground="gray").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        pan.add(left, weight=1)

        # ---- right: preview + editors ----
        right = ttk.Frame(pan, padding=(8, 0, 0, 0))
        right.columnconfigure(0, weight=1)
        self.cv = tk.Canvas(right, width=PREVIEW_W, height=PREVIEW_H, bg="#262a30", highlightthickness=0,
                            cursor="crosshair")
        self.cv.grid(row=0, column=0, sticky="nsew")
        right.rowconfigure(0, weight=1)
        self.cv.bind("<ButtonPress-1>", self._sel_press)
        self.cv.bind("<B1-Motion>", self._sel_drag)
        self.cv.bind("<ButtonRelease-1>", self._sel_release)
        self.cv.bind("<Button-3>", self._cv_menu)
        self.cv.bind("<Double-Button-1>", self._on_double_click)
        self.cv.bind("<Delete>", lambda e: self.delete_mark())
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self.cv.bind(f"<{key}>", lambda e, dx=dx, dy=dy: self.nudge(dx, dy))
            self.cv.bind(f"<Shift-{key}>", lambda e, dx=dx, dy=dy: self.nudge(dx * 10, dy * 10))
        self.cv.bind("<Configure>", lambda e: self.show_preview())

        self._build_marktools(right, 1)  # right under the picture, where people look for annotation tools
        vbar = ttk.Frame(right)
        vbar.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(vbar, text="View:").pack(side="left")
        ttk.Radiobutton(vbar, text="Whole screenshot", value="whole", variable=self.var_view,
                        command=self._view_changed).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(vbar, text="Close-up of the click", value="close", variable=self.var_view,
                        command=self._view_changed).pack(side="left", padx=(10, 0))
        self.cmb_zoom = ttk.Combobox(vbar, textvariable=self.var_zoom, values=["100%", "150%", "200%"], width=5,
                                     state="readonly")
        self.cmb_zoom.pack(side="left", padx=(6, 0))
        self.cmb_zoom.bind("<<ComboboxSelected>>", lambda e: self.show_preview())
        self.cmb_focus = ttk.Combobox(vbar, textvariable=self.var_focus, values=list(core.FOCUS_MODES.values()),
                                      state="readonly", width=30)
        self.cmb_focus.pack(side="right")
        self.cmb_focus.bind("<<ComboboxSelected>>", lambda e: self.show_preview())
        ttk.Label(vbar, text="Focus:").pack(side="right", padx=(0, 4))
        info = ttk.Frame(right)
        info.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        self.lbl_info = ttk.Label(info, text="", foreground="gray")
        self.lbl_info.pack(side="left")
        self.rb_before = ttk.Radiobutton(info, text="Before", value="before", variable=self.var_which,
                                         command=self.show_preview)
        self.rb_after = ttk.Radiobutton(info, text="After", value="after", variable=self.var_which,
                                        command=self.show_preview)
        self.rb_after.pack(side="right")
        self.rb_before.pack(side="right", padx=(0, 6))

        cap = ttk.LabelFrame(right, text="Caption (shown in the report)", padding=6)
        cap.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        cap.columnconfigure(0, weight=0)
        self.txt = tk.Text(cap, height=2, wrap="word", font=("Segoe UI", 10), undo=True)
        self.txt.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.txt.bind("<FocusOut>", lambda e: self.commit_caption())
        self.btn_reset = ttk.Button(cap, text="Reset to automatic wording", command=self.reset_caption)
        self.btn_reset.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.cmb_level = ttk.Combobox(cap, textvariable=self.var_level, values=list(LEVEL_LABEL.values()), width=9,
                                      state="readonly")
        self.cmb_level.grid(row=1, column=2, sticky="e", pady=(4, 0))
        self.cmb_level.bind("<<ComboboxSelected>>", lambda e: self._level_changed())

        cm = ttk.Frame(cap)  # shares the row with the level box, which only notes use (notes have no comment)
        cm.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(4, 0))
        cm.columnconfigure(1, weight=1)
        ttk.Label(cm, text="Comment").grid(row=0, column=0, padx=(0, 6))
        self.ent_comment = ttk.Entry(cm, textvariable=self.var_comment)
        self.ent_comment.grid(row=0, column=1, sticky="ew")
        self.ent_comment.bind("<FocusOut>", lambda e: self._commit_comment())
        self.ent_comment.bind("<Return>", lambda e: (self._commit_comment(), "break")[1])
        cap.columnconfigure(1, weight=1)

        mk = ttk.LabelFrame(right, text="Hide private information in the screenshot", padding=6)
        mk.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        self.btn_mask = tk.Button(mk, text="Hide this area", command=self.apply_mask, state="disabled", relief="flat",
                                  font=("Segoe UI", 10, "bold"), padx=12, pady=3, cursor="hand2")
        self.btn_mask.grid(row=0, column=0, sticky="w")
        ttk.Combobox(mk, textvariable=self.var_style, values=[core.MASK_STYLES[k] for k in core.HIDING_STYLES],
                     state="readonly", width=22).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Checkbutton(mk, text="Same area on every screenshot", variable=self.var_all,
                        command=self._update_hint).grid(row=0, column=2, padx=8)
        self.btn_clear = ttk.Button(mk, text="Clear", width=6, command=self.clear_selection, state="disabled")
        self.btn_clear.grid(row=0, column=3)
        mk.columnconfigure(1, weight=1)
        self.var_hint = tk.StringVar()
        self.lbl_hint = ttk.Label(mk, textvariable=self.var_hint, foreground="gray", wraplength=620, justify="left")
        self.lbl_hint.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self._selbar = None
        self._paint_mask_button(False)
        pan.add(right, weight=3)

        # ---- bottom: report options ----
        out = ttk.LabelFrame(root, text="Report", padding=6)
        out.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        out.columnconfigure(1, weight=1)
        out.columnconfigure(3, weight=1)
        ttk.Label(out, text="Style").grid(row=0, column=0, sticky="w")
        self.cmb_docstyle = ttk.Combobox(out, textvariable=self.var_docstyle, values=list(rep.STYLES.values()),
                                         state="readonly")
        self.cmb_docstyle.grid(row=0, column=1, sticky="ew", padx=(4, 12))
        self.cmb_docstyle.bind("<<ComboboxSelected>>", lambda e: self._style_changed())
        self.tip_style = w.Tip(self.cmb_docstyle, "")  # what the chosen style contains (updated in _style_changed)
        ttk.Label(out, text="Logo").grid(row=0, column=2, sticky="w")
        lg = ttk.Frame(out)
        lg.grid(row=0, column=3, sticky="ew", padx=(4, 12))
        lg.columnconfigure(0, weight=1)
        ttk.Entry(lg, textvariable=self.var_logo).grid(row=0, column=0, sticky="ew")
        ttk.Button(lg, text="...", width=3, command=self.pick_logo).grid(row=0, column=1, padx=(4, 0))
        ttk.Label(out, text="Header").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(out, textvariable=self.var_header).grid(row=1, column=1, sticky="ew", padx=(4, 12), pady=(4, 0))
        ttk.Label(out, text="Footer").grid(row=1, column=2, sticky="w", pady=(4, 0))
        ttk.Entry(out, textvariable=self.var_footer).grid(row=1, column=3, sticky="ew", padx=(4, 12), pady=(4, 0))
        ttk.Label(out, text="Author").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(out, textvariable=self.var_author).grid(row=2, column=1, sticky="ew", padx=(4, 12), pady=(4, 0))
        ttk.Label(out, text="Last verified").grid(row=2, column=2, sticky="w", pady=(4, 0))
        ver = ttk.Entry(out, textvariable=self.var_verified)
        ver.grid(row=2, column=3, sticky="ew", padx=(4, 12), pady=(4, 0))
        w.Tip(ver, "Used by the Runbook checklist. Leave empty to use the day you export.")
        fm = ttk.Frame(out)
        fm.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(fm, text="Save as:").pack(side="left", padx=(0, 8))
        for k, label in rep.FORMATS.items():
            ttk.Checkbutton(fm, text=label, variable=self.var_fmt[k]).pack(side="left", padx=(0, 8))
        self.chk_env = ttk.Checkbutton(fm, text="Environment appendix", variable=self.var_env)
        self.chk_env.pack(side="left", padx=(6, 0))
        if self.support:
            self._support_layout(root, out)
        else:
            self._build_actionbar()

    def _build_actionbar(self):
        bar = self.actionbar
        ttk.Separator(self).pack(side="bottom", fill="x", after=bar)
        bar.columnconfigure(0, weight=1)
        self.lbl_where = ttk.Label(bar, text=f"Files are saved in:  {self.s.dir}", foreground="gray")
        self.lbl_where.grid(row=0, column=0, sticky="w")
        self.chk_privacy = ttk.Checkbutton(bar, text="Check for private information on export", variable=self.var_check)
        self.chk_privacy.grid(row=0, column=1, padx=(10, 0))
        ttk.Button(bar, text="Close", command=self.close).grid(row=0, column=5, padx=(6, 0))
        ttk.Button(bar, text="Open folder", command=self.open_folder).grid(row=0, column=4, padx=(6, 0))
        ttk.Button(bar, text="Copy steps as text", command=self.copy_text).grid(row=0, column=3, padx=(6, 0))
        self.btn_export = tk.Button(bar, text="Export", command=self.export, bg="#1565c0", fg="white", relief="flat",
                                    activebackground="#0d47a1", activeforeground="white", cursor="hand2",
                                    font=("Segoe UI", 11, "bold"), padx=22, pady=4, default="active")
        self.btn_export.grid(row=0, column=2, padx=(10, 0))

    def _style_changed(self):
        """Documentation styles leave out timestamps, window/app details, dialog dumps and the environment."""
        docs = self.style_key != "report"
        if docs:
            if not getattr(self, "_env_before", None):
                self._env_before = [self.var_env.get()]
            self.var_env.set(False)
            self.chk_env.state(["disabled"])
        else:
            if getattr(self, "_env_before", None):
                self.var_env.set(self._env_before[0])
                self._env_before = None
            self.chk_env.state(["!disabled"])
        self.tip_style.text = {
            "report": "Everything: times, window and app details, dialog text and the environment appendix.",
            "docs": "Steps and pictures only - ready to edit into a user guide.",
            "onesheet": "Steps and small pictures side by side, aiming for one page."}[self.style_key]

    @property
    def focus_key(self):
        return next((k for k, v in core.FOCUS_MODES.items() if v == self.var_focus.get()), "off")

    @property
    def style_key(self):
        return next((k for k, v in rep.STYLES.items() if v == self.var_docstyle.get()), "report")

    def _return_key(self, e):
        try:
            cls = self.focus_get().winfo_class()
        except (KeyError, AttributeError):
            cls = ""
        if cls in ("Text", "TEntry", "Entry", "TCombobox", "TButton", "Button", "TCheckbutton", "TRadiobutton",
                   "TSpinbox"):
            return None  # Enter belongs to the control that has the focus
        self.export()
        return "break"

    def _support_layout(self, root, out):
        """Replace the report options with a plain 'check, then send' bar."""
        out.grid_remove()
        for wd in self._wording_widgets:
            wd.grid_remove()
        bar = ttk.Frame(root, padding=(0, 8, 0, 0))
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, text="Look through the steps. Hide anything private (drag a box on the picture, then click "
                            "\"Hide this area\"), or select a step and click Delete to leave it out.",
                  wraplength=700, justify="left").grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="Back", command=self.close).grid(row=0, column=1, padx=(8, 0))
        tk.Button(bar, text="Looks good - create the ZIP", command=self.finish, bg="#2e7d32", fg="white", relief="flat",
                  activebackground="#1b5e20", activeforeground="white", font=("Segoe UI", 11, "bold"), padx=14, pady=5,
                  cursor="hand2").grid(row=0, column=2, padx=(8, 0))

    def finish(self):
        """Support mode: the user is happy with the recording."""
        self.save()
        self.destroy()
        if self.on_done:
            self.on_done()

    def _tree_focus(self):
        return self.focus_get() is self.tree

    # ------------------------------------------------------------------ list
    @property
    def wording(self):
        return "friendly" if self.var_wording.get() == "Friendly" else "technical"

    def _row(self, st, nums):
        n = nums.get(st.id, "")
        cap = st.caption(self.wording).replace("\n", " ")
        kind = KIND_LABEL.get(st.kind, st.kind)
        tags = []
        if st.kind == "section":
            tags.append("section")
        elif st.kind == "note":
            tags.append(st.level if st.level in LEVEL_LABEL else "note")
            kind = LEVEL_LABEL.get(st.level, "Note")
        if st.skip:
            tags.append("skip")
        return ("\u2610" if st.skip else "\u2611", n, kind, cap), tuple(tags)

    def refresh(self, select=None):
        keep = select if select is not None else list(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        nums = self.s.numbering()
        for i, st in enumerate(self.s.steps):
            vals, tags = self._row(st, nums)
            if not tags and i % 2:  # notes, sections and left-out steps keep their own colours
                tags = ("stripe",)
            self.tree.insert("", "end", iid=st.id, values=vals, tags=tags)
        keep = [k for k in (keep if isinstance(keep, (list, tuple)) else [keep]) if k and self.tree.exists(k)]
        if keep:
            self.tree.selection_set(keep)
            self.tree.see(keep[0])
        else:
            self.on_select()

    def selected_steps(self):
        return [st for st in (self.s.find(i) for i in self.tree.selection()) if st]

    def select_index(self, idx):
        kids = self.tree.get_children()
        if 0 <= idx < len(kids):
            self.tree.selection_set(kids[idx])
            self.tree.see(kids[idx])

    def on_select(self):
        self._commit_editor()
        self._msel = None
        self._drop_markbar()
        self.commit_caption()
        sel = self.selected_steps()
        self._cur = sel[0] if len(sel) == 1 else None
        st = self._cur
        self.var_which.set("before")
        self._update_skip_button()
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self._txt_wording = self.wording
        self.var_comment.set(st.comment if st and st.numbered else "")
        self.ent_comment.configure(state="normal" if st and st.numbered else "disabled")
        if st:
            self.txt.insert("1.0", st.caption(self.wording))
            self.btn_reset.configure(state="normal" if st.kind not in ("note", "section") else "disabled")
            if st.kind == "note":
                self.var_level.set(LEVEL_LABEL.get(st.level, "Note"))
                self.cmb_level.grid()
            else:
                self.cmb_level.grid_remove()
            self.rb_after.state(["!disabled"] if st.raw_after else ["disabled"])
            self.rb_before.state(["!disabled"] if st.raw_after else ["disabled"])
        else:
            self.txt.configure(state="disabled")
            self.cmb_level.grid_remove()
        self.show_preview()

    # ------------------------------------------------------------------ preview + masking
    def _current_image(self):
        st = self._cur
        if not st:
            return None
        if self.var_which.get() == "after" and st.raw_after and (self.s.dir / st.raw_after).exists():
            return Image.open(self.s.dir / st.raw_after).convert("RGB")
        return rep.render_step_image(self.s, st, self.s.numbering().get(st.id), self.focus_key)

    def show_preview(self):
        if self._editor:  # a resize or redraw while typing: keep what was typed
            self._commit_editor()
            return
        self.cv.delete("all")
        self._sel_rect = None
        self._drop_selbar()
        self._paint_mask_button(False)
        self.btn_clear.configure(state="disabled")
        st = self._cur
        img = self._current_image() if st else None
        cw, ch = max(self.cv.winfo_width(), 100), max(self.cv.winfo_height(), 100)
        if self.cv.winfo_height() > 1 and self.cv.winfo_height() < 130:
            self.cv.create_text(cw // 2, ch // 2, fill="#ffcc80", font=("Segoe UI", 10, "bold"), justify="center",
                                text="The picture area is too small.\nMake this window taller (or maximize it).")
            self._photo = None
            self._msel = None
            self._drop_markbar()
            self._update_hint()
            return
        if img is None:
            msg = "Select a single step to see its screenshot" if not st else "(no screenshot for this entry)"
            if st and st.kind in ("note", "section"):
                msg = "Text entry - edit the caption below"
            self.cv.create_text(cw // 2, ch // 2, text=msg, fill="#9aa0a6", font=("Segoe UI", 11))
            self.lbl_info.configure(text="" if not st else self._info(st))
            self._photo = None
            self._msel = None
            self._drop_markbar()
            self._update_hint()
            return
        self._img_size = img.size
        W, H = img.size
        pt = (st.marker or {}).get("pt")
        close = self.var_view.get() == "close" and pt
        self.cmb_zoom.state(["!disabled"] if pt else ["disabled"])
        if close:
            k = {"100%": 1.0, "150%": 1.5, "200%": 2.0}.get(self.var_zoom.get(), 1.0)
            vw, vh = min(W, int(cw / k)), min(H, int(ch / k))
            x0 = int(min(max(0, pt[0] - vw / 2), W - vw))
            y0 = int(min(max(0, pt[1] - vh / 2), H - vh))
            self._crop = (x0, y0, x0 + vw, y0 + vh)
            shown, self._scale = img.crop(self._crop), min(k, cw / vw, ch / vh)
        else:
            self._crop, shown = (0, 0, W, H), img
            self._scale = min(cw / W, ch / H, 1.0)
        size = (max(1, int(shown.width * self._scale)), max(1, int(shown.height * self._scale)))
        self._photo = ImageTk.PhotoImage(shown.resize(size, Image.LANCZOS))
        self._off = ((cw - size[0]) // 2, (ch - size[1]) // 2)
        self.cv.create_image(self._off[0], self._off[1], image=self._photo, anchor="nw")
        if st.skip:  # on-screen only: this step will not be in the report
            t = self.cv.create_text(self._off[0] + 14, self._off[1] + 12, anchor="nw", fill="white",
                                    font=("Segoe UI", 10, "bold"), text="LEFT OUT OF THE REPORT")
            x0_, y0_, x1_, y1_ = self.cv.bbox(t)
            r_ = self.cv.create_rectangle(x0_ - 6, y0_ - 3, x1_ + 6, y1_ + 3, fill="#b71c1c", outline="")
            self.cv.tag_lower(r_, t)
        self.lbl_info.configure(text=self._info(st))
        self._draw_mark_overlay()
        # hint banner (only on screen, never in the saved image); the docked mark bar takes its place
        if self._mbar is not None and self._msel is not None:
            self._update_hint()
            return
        bx, by = self._off[0] + 8, self._off[1] + size[1] - 30
        t = self.cv.create_text(bx + 8, by + 11, anchor="w", fill="white", font=("Segoe UI", 9, "bold"), tags="hint",
                                text=self.banner_text())
        x0, y0, x1, y1 = self.cv.bbox(t)
        r = self.cv.create_rectangle(x0 - 8, y0 - 4, x1 + 8, y1 + 4, fill="#37474f", outline="", tags="hint")
        self.cv.tag_lower(r, t)
        self._update_hint()

    def _info(self, st):
        bits = [st.when, st.window, f"{st.app} {st.app_version}".strip()]
        return "  |  ".join(b for b in bits if b)[:110]

    def _sel_press(self, e):
        if not self._cur or self._photo is None:
            return
        if self.var_tool.get() != "hide":
            return self._mark_press(e)
        self._sel_start = (e.x, e.y)
        if self._sel_rect:
            self.cv.delete(self._sel_rect)
        self.cv.delete("hint")
        self._drop_selbar()
        self._sel_rect = self.cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff3d00", width=2, dash=(4, 3),
                                                  fill="#ff3d00", stipple="gray25")

    def _sel_drag(self, e):
        if self.var_tool.get() != "hide":
            return self._mark_drag(e)
        if self._sel_rect and self._sel_start:
            self.cv.coords(self._sel_rect, self._sel_start[0], self._sel_start[1], e.x, e.y)

    def _sel_release(self, e):
        if self.var_tool.get() != "hide":
            return self._mark_release(e)
        if not self._sel_rect or not self._sel_start:
            return
        x0, y0, x1, y1 = self.cv.coords(self._sel_rect)
        ok = abs(x1 - x0) >= 6 and abs(y1 - y0) >= 6
        self._paint_mask_button(ok)
        self.btn_clear.configure(state="normal")
        self._sel_start = None
        if ok:
            self._show_selbar()
        else:
            self._drop_selbar()
        self._update_hint()

    # ------------------------------------------------------------------ extra step edits
    def _more_menu(self, parent):
        m = tk.Menu(parent, tearoff=0)
        m.add_command(label="Merge selected steps into one", command=self.merge_selected)
        m.add_command(label="Duplicate step", command=self.duplicate_selected)
        m.add_separator()
        m.add_command(label="Move to top", command=lambda: self.move(-10_000))
        m.add_command(label="Move to bottom", command=lambda: self.move(10_000))
        return m

    def merge_selected(self):
        sel = [st for st in self.selected_steps() if st.numbered]
        if len(sel) < 2:
            messagebox.showinfo("Telestep", "Select two or more steps (Ctrl+click or Shift+click), then merge them.",
                                parent=self)
            return
        if not messagebox.askyesno(
                "Telestep", f"Merge {len(sel)} steps into one?\n\nThe first screenshot is kept, the last one becomes the "
                "'after' picture, and the captions are joined. The other steps are removed.", parent=self):
            return
        head = self.s.merge(sel)
        if head:
            self.s.save()
            self._edits += 1
            self.refresh([head.id])

    def duplicate_selected(self):
        sel = self.selected_steps()
        if len(sel) != 1 or sel[0].kind == "section":
            return
        twin = self.s.duplicate(sel[0])
        self.s.save()
        self._edits += 1
        self.refresh([twin.id])

    # ------------------------------------------------------------------ right-click menus
    @staticmethod
    def _popup(menu, e):
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _focus_caption(self):
        self.txt.focus_set()
        self.txt.mark_set("insert", "end-1c")

    def _copy_caption(self):
        st = self._cur
        if st:
            self.clipboard_clear()
            self.clipboard_append(st.caption(self.wording))

    def _tree_menu(self, e):
        """Right-click on the step list: act on the step under the pointer (or on the current selection)."""
        row = self.tree.identify_row(e.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
            self.tree.focus(row)
            self.update_idletasks()
        sel = self.selected_steps()
        one = len(sel) == 1
        st = sel[0] if one else None
        on = lambda c: "normal" if c else "disabled"
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Edit caption", command=self._focus_caption, state=on(one))
        m.add_command(label="Copy caption", command=self._copy_caption, state=on(one))
        m.add_command(label="Reset caption to automatic wording", command=self.reset_caption,
                      state=on(one and st.kind not in ("note", "section") and bool(st.custom)))
        m.add_separator()
        m.add_command(label="Move up", accelerator="Alt+Up", command=lambda: self.move(-1), state=on(sel))
        m.add_command(label="Move down", accelerator="Alt+Down", command=lambda: self.move(1), state=on(sel))
        m.add_command(label="Move to top", command=lambda: self.move(-10_000), state=on(sel))
        m.add_command(label="Move to bottom", command=lambda: self.move(10_000), state=on(sel))
        m.add_separator()
        m.add_command(label="Merge selected steps", command=self.merge_selected,
                      state=on(len([x for x in sel if x.numbered]) > 1))
        m.add_command(label="Duplicate step", command=self.duplicate_selected, state=on(one and st.kind != "section"))
        m.add_separator()
        all_skipped = bool(sel) and all(s.skip for s in sel)
        m.add_command(label="Put back in report" if all_skipped else "Leave out of report", command=self.toggle_skip,
                      state=on(sel))
        m.add_command(label="Delete" + (f" {len(sel)} steps" if len(sel) > 1 else ""), accelerator="Del",
                      command=self.delete_selected, state=on(sel))
        m.add_separator()
        ins = tk.Menu(m, tearoff=0)
        for label, fn in (("Section heading above", lambda: self.add_section()),
                          ("Section heading below", lambda: self.add_section(below=True)),
                          ("Note / warning / tip above", lambda: self.add_note()),
                          ("Note / warning / tip below", lambda: self.add_note(below=True))):
            ins.add_command(label=label, command=fn)
        m.add_cascade(label="Insert", menu=ins)
        m.add_separator()
        m.add_command(label="Select all", accelerator="Ctrl+A",
                      command=lambda: self.tree.selection_set(self.tree.get_children()))
        self._popup(m, e)

    def _marker_rect(self, st):
        """The clicked control's outline in screenshot pixels (l, t, r, b), or None."""
        r = (st.marker or {}).get("rect") if st else None
        if not r or len(r) != 4 or self._photo is None:
            return None
        w, h = self._img_size
        l, t, rr, b = max(0, r[0]), max(0, r[1]), min(w, r[2]), min(h, r[3])
        return (l, t, rr, b) if rr - l >= 4 and b - t >= 4 else None

    def _select_image_rect(self, l, t, r, b):
        """Select an area given in screenshot pixels, exactly as if it had been dragged on the picture."""
        cl, ct, cr, cb = self._crop
        if self.var_view.get() == "close" and not (cl <= l and ct <= t and r <= cr and b <= cb):
            self.var_view.set("whole")  # the control isn't inside the close-up: show everything
            self.show_preview()
            cl, ct = self._crop[:2]
        k, (ox, oy) = self._scale, self._off
        l, r, t, b = l - cl, r - cl, t - ct, b - ct
        self.cv.delete("hint")
        self._drop_selbar()
        if self._sel_rect:
            self.cv.delete(self._sel_rect)
        self._sel_rect = self.cv.create_rectangle(ox + l * k, oy + t * k, ox + r * k, oy + b * k, outline="#ff3d00",
                                                  width=2, dash=(4, 3), fill="#ff3d00", stipple="gray25")
        self._paint_mask_button(True)
        self.btn_clear.configure(state="normal")
        self._show_selbar()
        self._update_hint()

    def _hide_with(self, key):
        self.var_style.set(core.MASK_STYLES[key])
        self.apply_mask()

    def _hide_everywhere(self):
        self.var_all.set(True)
        try:
            self.apply_mask()
        finally:
            self.var_all.set(False)
            self._update_hint()

    def _hide_and_remember(self):
        """Hide the selection here, and save it as a rule: the same part of any window with this title is hidden in
        future recordings (stored as fractions of the window, so it survives resizing)."""
        st, rect = self._cur, self.selection_in_image()
        win = (st.marker or {}).get("win") if st else None
        if not (st and rect and win and self.on_rule):
            return
        from tkinter import simpledialog
        title = simpledialog.askstring("Future recordings", "Hide this area in future recordings of windows whose "
                                       "title contains:", initialvalue=st.window[:80], parent=self)
        if not title or not title.strip():
            return
        wl, wt, wr, wb = win
        ww, wh = max(1.0, wr - wl), max(1.0, wb - wt)
        clip = lambda v: round(max(0.0, min(1.0, v)), 4)
        frac = (clip((rect[0] - wl) / ww), clip((rect[1] - wt) / wh), clip((rect[2] - wl) / ww), clip((rect[3] - wt) / wh))
        if frac[2] - frac[0] < 0.005 or frac[3] - frac[1] < 0.005:
            messagebox.showinfo("Telestep", "That area is outside the window, so it can't be remembered.", parent=self)
            return
        style = next((k for k, v in core.MASK_STYLES.items() if v == self.var_style.get()), "solid")
        self.apply_mask(confirm=False)
        self.on_rule(core.Mask(title=title.strip(), style=style, frac=frac, label="").to_dict())
        messagebox.showinfo("Telestep", f"Saved. In future recordings that part of any window titled "
                            f"\"{title.strip()}\" will be hidden (see Settings > Privacy).", parent=self)

    def _cv_menu(self, e):
        """Right-click on the picture: hide things, switch Before/After, exclude or delete the step."""
        st = self._cur
        has_img = bool(st) and self._photo is not None
        sel_ok = bool(self._sel_rect) and self.btn_mask.cget("state") == "normal"
        rect = self._marker_rect(st) if has_img else None
        on = lambda c: "normal" if c else "disabled"
        m = tk.Menu(self, tearoff=0)
        if has_img:
            self._mark_menu(m, e)
        if has_img and not sel_ok and not rect:
            m.add_command(label="Drag a box on the picture to select an area to hide", state="disabled")
        m.add_command(label="Select the clicked control (to hide it)",
                      command=lambda: self._select_image_rect(*rect), state=on(rect))
        sub = tk.Menu(m, tearoff=0)
        for k in core.HIDING_STYLES:
            sub.add_command(label=core.MASK_STYLES[k], command=lambda k=k: self._hide_with(k))
        m.add_cascade(label="Hide selected area as", menu=sub, state=on(sel_ok))
        m.add_command(label="Hide selected area on every screenshot...", command=self._hide_everywhere, state=on(sel_ok))
        can_rule = bool(self.on_rule and sel_ok and st and st.window and (st.marker or {}).get("win"))
        m.add_command(label="Hide selected area now and in future recordings of this window...",
                      command=self._hide_and_remember, state=on(can_rule))
        m.add_command(label="Clear selection", command=self.clear_selection, state=on(self._sel_rect))
        m.add_separator()
        has_after = bool(st and st.raw_after and (self.s.dir / st.raw_after).exists())
        m.add_radiobutton(label="Show the 'before' screenshot", variable=self.var_which, value="before",
                          command=self.show_preview, state=on(has_after))
        m.add_radiobutton(label="Show the 'after' screenshot", variable=self.var_which, value="after",
                          command=self.show_preview, state=on(has_after))
        m.add_separator()
        m.add_command(label="Put back in report" if st and st.skip else "Leave out of report", command=self.toggle_skip,
                      state=on(st))
        m.add_command(label="Delete this step", command=self.delete_selected, state=on(st))
        self._popup(m, e)

    def _paint_mask_button(self, ready):
        """Orange and obvious while an area is selected, flat grey otherwise."""
        if ready:
            self.btn_mask.configure(state="normal", bg="#e64a19", fg="white", activebackground="#bf360c",
                                    activeforeground="white")
        else:
            self.btn_mask.configure(state="disabled", bg="#d9d9d9", fg="#8a8a8a", disabledforeground="#8a8a8a")

    def _drop_selbar(self):
        if self._selbar is not None:
            try:
                self._selbar.destroy()
            except tk.TclError:
                pass
            self._selbar = None

    def _show_selbar(self):
        """Floating 'Hide this area / Cancel' buttons right beside the selection box."""
        self._drop_selbar()
        if not self._sel_rect:
            return
        x0, y0, x1, y1 = self.cv.coords(self._sel_rect)
        bar = tk.Frame(self.cv, bg="#263238", padx=4, pady=4, highlightthickness=1, highlightbackground="#ff3d00")
        tk.Button(bar, text="Hide this area", command=self.apply_mask, bg="#e64a19", fg="white", relief="flat",
                  activebackground="#bf360c", activeforeground="white", font=("Segoe UI", 10, "bold"), padx=10,
                  cursor="hand2").pack(side="left")
        tk.Button(bar, text="Cancel", command=self.clear_selection, bg="#546e7a", fg="white", relief="flat",
                  activebackground="#37474f", activeforeground="white", font=("Segoe UI", 10), padx=8,
                  cursor="hand2").pack(side="left", padx=(4, 0))
        self._selbar = bar
        cw, ch = self.cv.winfo_width(), self.cv.winfo_height()
        left, bottom, top = min(x0, x1), max(y0, y1), min(y0, y1)
        bar.update_idletasks()
        bw, bh = bar.winfo_reqwidth(), bar.winfo_reqheight()
        y = bottom + 6 if bottom + 6 + bh <= ch else max(2, top - bh - 6)
        x = min(max(2, left), max(2, cw - bw - 2))
        self.cv.create_window(x, y, window=bar, anchor="nw", tags="selbar")

    def clear_selection(self):
        if self._sel_rect:
            self.cv.delete(self._sel_rect)
        self._sel_rect = None
        self._sel_start = None
        self._drop_selbar()
        self._paint_mask_button(False)
        self.btn_clear.configure(state="disabled")
        self._update_hint()

    def _update_hint(self):
        """Tell the user what the hide tool will do, and to which screenshots."""
        if not hasattr(self, "var_hint"):
            return
        n = sum(1 for s in self.s.steps if s.raw)
        scope = f"ALL {n} screenshots" if self.var_all.get() else "this screenshot only"
        if self._sel_rect and self.btn_mask.cget("state") == "normal":
            msg = f'Area selected. Pick a style, then click "Hide this area" ({scope}).'
        elif not self._cur or self._photo is None:
            msg = "Select a step with a screenshot, then drag a box on the picture."
        else:
            msg = f"Drag a box on the picture to choose an area to hide ({scope})."
        ready = bool(self._sel_rect and self.btn_mask.cget("state") == "normal")
        self.lbl_hint.configure(foreground="#d84315" if ready else "gray")
        self.var_hint.set(msg + " Hiding is permanent.")

    def selection_in_image(self):
        """The dragged rectangle in image pixels (l, t, r, b), or None."""
        if not self._sel_rect:
            return None
        x0, y0, x1, y1 = self.cv.coords(self._sel_rect)
        ox, oy = self._off
        k = self._scale
        cl, ct, cr, cb = self._crop
        l, r = sorted((cl + (x0 - ox) / k, cl + (x1 - ox) / k))
        t, b = sorted((ct + (y0 - oy) / k, ct + (y1 - oy) / k))
        l, t, r, b = max(cl, l), max(ct, t), min(cr, r), min(cb, b)
        return (l, t, r, b) if r - l >= 2 and b - t >= 2 else None

    def apply_mask(self, confirm=True):
        rect = self.selection_in_image()
        st = self._cur
        if not rect or not st:
            return 0
        style = next((k for k, v in core.MASK_STYLES.items() if v == self.var_style.get()), "soft")
        W, H = self._img_size
        targets = [s for s in self.s.steps if s.raw] if self.var_all.get() else [st]
        if self.var_all.get() and confirm and not messagebox.askyesno(
                "Telestep", f"Apply to {len(targets)} screenshot(s)? This can't be undone.", parent=self):
            return 0
        count = 0
        for s in targets:
            for rel in (s.raw, s.raw_after):
                p = self.s.dir / rel if rel else None
                if not p or not p.exists():
                    continue
                with Image.open(p) as im0:
                    im = im0.convert("RGB")
                fx, fy = im.width / W, im.height / H
                core.apply_mask(im, (rect[0] * fx, rect[1] * fy, rect[2] * fx, rect[3] * fy), style, "Hidden")
                im.save(p, "JPEG", quality=92)
                count += 1
        if count:
            self._edits += 1
        self.show_preview()
        return count

    # ------------------------------------------------------------------ editing
    def _commit_comment(self):
        st = self._cur
        if not st or not st.numbered:
            return
        text = self.var_comment.get().strip()
        if text != (st.comment or ""):
            st.comment = text
            self.s.save()

    def commit_caption(self):
        self._commit_comment()
        st = self._cur
        if not st or str(self.txt.cget("state")) == "disabled":
            return
        text = self.txt.get("1.0", "end").strip()
        old = st.caption(self._txt_wording)
        if text == old:
            return
        if st.kind in ("note", "section"):
            st.friendly = st.tech = text
            st.custom = ""
        else:
            auto = st.tech if self._txt_wording == "technical" and st.tech else (st.friendly or st.tech)
            st.custom = "" if text == auto else text
        self.s.save()
        vals, tags = self._row(st, self.s.numbering())
        if self.tree.exists(st.id):
            if not tags and self.s.steps.index(st) % 2:
                tags = ("stripe",)
            self.tree.item(st.id, values=vals, tags=tags)

    def reset_caption(self):
        st = self._cur
        if st and st.kind not in ("note", "section"):
            st.custom = ""
            self.s.save()
            self.txt.delete("1.0", "end")  # reload the box first so the reset isn't "committed" back
            self.txt.insert("1.0", st.caption(self.wording))
            self._txt_wording = self.wording
            self.refresh([st.id])

    def _level_changed(self):
        st = self._cur
        if st and st.kind == "note":
            st.level = next(k for k, v in LEVEL_LABEL.items() if v == self.var_level.get())
            self.s.save()
            self.refresh([st.id])

    def _wording_changed(self):
        self.commit_caption()
        self.refresh()
        self.on_select()

    def _set_title(self):
        t = self.var_title.get().strip() or "Recorded steps"
        if t != self.s.title:
            self.s.title = t
            self.s.save()
            self.title(f"Telestep - Review: {t}")

    def move(self, delta):
        sel = self.selected_steps()
        if not sel:
            return
        if self.s.move_block(sel, delta):
            self.s.save()
            self._edits += 1
            self.refresh([st.id for st in sel])

    def delete_selected(self, confirm=True):
        sel = self.selected_steps()
        if not sel:
            return
        if confirm and not messagebox.askyesno(
                "Telestep", f"Delete {len(sel)} entr{'y' if len(sel) == 1 else 'ies'} and their screenshots?\n\n"
                "Tip: 'Leave out' keeps a step but drops it from the report (you can put it back).", parent=self):
            return
        kids = list(self.tree.get_children())
        idx = kids.index(sel[0].id) if sel[0].id in kids else 0
        for st in sel:
            self.s.delete(st)
        self.s.save()
        self._cur = None
        self.refresh([])
        self.select_index(min(idx, len(self.s.steps) - 1))

    def toggle_skip(self):
        sel = self.selected_steps()
        for st in sel:
            st.skip = not st.skip
        if sel:
            self.s.save()
            self.refresh([st.id for st in sel])
            self._update_skip_button()
            self.show_preview()

    def _update_skip_button(self):
        sel = self.selected_steps()
        out = bool(sel) and all(s.skip for s in sel)
        self.btn_skip.configure(text="Put back" if out else "Leave out", state="normal" if sel else "disabled")

    def _tree_click(self, e):
        """Clicking the tick box in the 'In report' column switches that step in or out of the report."""
        if self.tree.identify_region(e.x, e.y) != "cell" or self.tree.identify_column(e.x) != "#1":
            return None
        iid = self.tree.identify_row(e.y)
        st = self.s.find(iid) if iid else None
        if not st:
            return None
        st.skip = not st.skip
        self.s.save()
        self.refresh([iid])
        self._update_skip_button()
        self.show_preview()
        return "break"

    def _view_changed(self):
        self.show_preview()

    def _insert_index(self, below=False):
        sel = self.selected_steps()
        if not sel:
            return len(self.s.steps)
        return self.s.steps.index(sel[-1] if below else sel[0]) + (1 if below else 0)

    def add_section(self, text=None, below=False):
        if text is None:
            text = self._ask_text("Section heading", "Heading for the steps that follow:")
        if not text:
            return None
        st = Step(new_id(), "section", friendly=text, tech=text)
        self.s.steps.insert(self._insert_index(below), st)
        self.s.save()
        self.refresh([st.id])
        return st

    def add_note(self, text=None, level="note", below=False):
        if text is None:
            dlg = w.NoteDialog(self)
            text, level = dlg.result, dlg.level
        if not text:
            return None
        st = Step(new_id(), "note", friendly=text, tech=text, level=level)
        self.s.steps.insert(self._insert_index(below), st)
        self.s.save()
        self.refresh([st.id])
        return st

    def _ask_text(self, title, prompt):
        from tkinter import simpledialog
        return (simpledialog.askstring(title, prompt, parent=self) or "").strip()

    # ------------------------------------------------------------------ output
    def pick_logo(self):
        f = filedialog.askopenfilename(parent=self, title="Logo", filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if f:
            self.var_logo.set(f)

    def template(self):
        return dataclasses.replace(
            self.tpl, wording=self.wording, header=self.var_header.get().strip(),
            footer=self.var_footer.get().strip(), logo=self.var_logo.get().strip(),
            author=self.var_author.get().strip(), style=self.style_key, focus=self.focus_key,
            verified=self.var_verified.get().strip(),
            environment=(self._env_before[0] if getattr(self, "_env_before", None) else self.var_env.get()))

    def _state_sig(self):
        steps = [(st.id, st.kind, st.skip, st.custom, st.friendly, st.tech, st.level, st.comment, repr(st.marks))
                 for st in self.s.steps]
        fm = tuple(k for k, v in self.var_fmt.items() if v.get())
        return repr((self.template().to_dict(), steps, self.var_title.get(), fm, self._edits))

    def _has_outputs(self):
        return any((self.s.dir / f).exists() for f in rep.OUTPUT_FILES.values())

    def save(self):
        self.commit_caption()
        self._set_title()
        self.s.settings["template"] = self.template().to_dict()
        self.s.settings["wording"] = self.wording
        self.s.settings["privacy_check"] = bool(self.var_check.get())
        return self.s.save()

    def export(self, quiet=False):
        self.save()
        fmts = [k for k, v in self.var_fmt.items() if v.get()]
        if not fmts:
            messagebox.showinfo("Telestep", "Tick at least one format.", parent=self)
            return {}
        if self.var_check.get() and not self.support:
            go_on, changed = priv.check_before_export(self, self.s, "solid", self.s.numbering())
            if changed:
                self._edits += 1
                self.refresh()
                self.on_select()
            if not go_on:
                return {}
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.exported = rep.export(self.s, self.template(), fmts)
        finally:
            self.config(cursor="")
        if not quiet:
            lines = [f"{rep.FORMATS.get(k, k)}: " + ("saved" if not v.startswith("FAILED") else v)
                     for k, v in self.exported.items()]
            bad = any(v.startswith("FAILED") for v in self.exported.values())
            if bad:
                messagebox.showwarning("Telestep", "\n".join(lines) + f"\n\nDetails: {self.s.dir / 'save_errors.log'}",
                                       parent=self)
            elif messagebox.askyesno("Telestep", "\n".join(lines) + f"\n\nSaved in:\n{self.s.dir}\n\nOpen the folder now?",
                                     parent=self):
                self.open_folder()
        if not any(str(v).startswith("FAILED") for v in self.exported.values()):
            self._exported_sig = self._state_sig()
        return self.exported

    def copy_text(self):
        self.save()
        txt = rep.steps_text(self.s, self.template())
        self.clipboard_clear()
        self.clipboard_append(txt)

    def open_folder(self):
        try:
            os.startfile(str(self.s.dir))  # Windows only
        except Exception as e:
            messagebox.showerror("Telestep", f"Could not open folder:\n{e}", parent=self)

    def _unexported(self):
        if self.support or not any(not st.skip for st in self.s.steps):
            return False
        sig = self._state_sig()
        if sig == self._exported_sig:
            return False
        return sig != self._opened_sig or not self._has_outputs()  # untouched + already has files: just looking

    def close(self):
        if self._unexported():
            ans = messagebox.askyesnocancel(
                "Telestep",
                "This recording hasn't been exported yet, so there is no report file to find.\n\n"
                "Yes  -  export now, then close\nNo  -  close without exporting (your edits stay saved in the "
                "recording folder)\nCancel  -  keep editing", parent=self)
            if ans is None:
                return
            if ans:
                res = self.export()
                if not res or any(str(v).startswith("FAILED") for v in res.values()):
                    return
        self.save()
        self.destroy()
        if self.support:
            if self.on_cancel:
                self.on_cancel()
            return
        if self.own_root:
            self.master.destroy()


def review_main(folder):
    root = tk.Tk()
    root.withdraw()
    try:
        sess = Session.load(Path(folder))
    except Exception as e:
        messagebox.showerror("Telestep", f"Could not open session:\n{e}")
        root.destroy()
        return
    win = ReviewWindow(root, sess, own_root=True)
    win.lift()
    root.mainloop()
