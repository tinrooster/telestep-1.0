"""
telestep_review.py - review / edit a recorded session, then export it.

  * delete, exclude (reversible), reorder steps; edit captions; add section headings and note /
    warning / tip callouts
  * black out (or soften / pixelate / ...) a region of one screenshot or of every screenshot
  * switch between friendly and technical wording, set header / footer / logo, pick formats, export

Open it from the toolbar (list icon), automatically after Stop, or:  python telestep_recorder.py --review <folder>
"""
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import telestep_core as core
import telestep_report as rep
import telestep_widgets as w
from telestep_model import Session, Step, new_id

KIND_LABEL = {"click": "Click", "dblclick": "Double-click", "drag": "Drag", "scroll": "Scroll", "shortcut": "Keys",
              "type": "Typing", "shot": "Screenshot", "dialog": "Dialog", "note": "Note", "section": "Section"}
LEVEL_LABEL = {"note": "Note", "warning": "Warning", "tip": "Tip"}
PREVIEW_W, PREVIEW_H = 640, 380


class ReviewWindow(tk.Toplevel):
    def __init__(self, master, session, formats=None, own_root=False):
        super().__init__(master)
        self.s = session
        self.own_root = own_root
        self.title(f"Telestep - Review: {session.title}")
        self.minsize(960, 640)
        self.geometry("1120x740")
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
        self.var_style = tk.StringVar(value=core.MASK_STYLES["soft"])
        self.var_all = tk.BooleanVar(value=False)
        self.var_level = tk.StringVar(value="Note")
        self.var_header = tk.StringVar(value=tpl.header)
        self.var_footer = tk.StringVar(value=tpl.footer)
        self.var_author = tk.StringVar(value=tpl.author)
        self.var_logo = tk.StringVar(value=tpl.logo)
        self.var_env = tk.BooleanVar(value=tpl.environment)
        fm = formats or {"md": True, "docx": True}
        self.var_fmt = {k: tk.BooleanVar(value=bool(fm.get(k, False))) for k in rep.FORMATS}
        self._build()
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Delete>", lambda e: self.delete_selected() if self._tree_focus() else None)
        self.bind("<Alt-Up>", lambda e: self.move(-1))
        self.bind("<Alt-Down>", lambda e: self.move(1))
        self.bind("<Control-s>", lambda e: self.save())

    # ------------------------------------------------------------------ layout
    def _build(self):
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
        ttk.Label(top, text="Wording").grid(row=0, column=2, padx=(12, 6))
        cb = ttk.Combobox(top, textvariable=self.var_wording, values=["Friendly", "Technical"], width=10,
                          state="readonly")
        cb.grid(row=0, column=3)
        cb.bind("<<ComboboxSelected>>", lambda e: self._wording_changed())

        pan = ttk.PanedWindow(root, orient="horizontal")
        pan.grid(row=1, column=0, sticky="nsew")

        # ---- left: step list ----
        left = ttk.Frame(pan)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=("n", "kind", "cap"), show="headings", selectmode="extended")
        for col, text, width, anchor in (("n", "#", 36, "e"), ("kind", "Type", 84, "w"), ("cap", "Caption", 330, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "cap"))
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("skip", foreground="#9aa0a6")
        self.tree.tag_configure("section", background="#e8eef7", font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("note", background="#eef6ff")
        self.tree.tag_configure("warning", background="#fff4e0")
        self.tree.tag_configure("tip", background="#eaf7ee")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        bar = ttk.Frame(left)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for text, cmd in (("Up", lambda: self.move(-1)), ("Down", lambda: self.move(1)),
                          ("Delete", self.delete_selected), ("Exclude / include", self.toggle_skip),
                          ("+ Section", self.add_section), ("+ Note", self.add_note)):
            ttk.Button(bar, text=text, command=cmd, width=len(text) + 2 if len(text) < 8 else 15).pack(
                side="left", padx=(0, 4))
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
        self.cv.bind("<Configure>", lambda e: self.show_preview())

        info = ttk.Frame(right)
        info.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.lbl_info = ttk.Label(info, text="", foreground="gray")
        self.lbl_info.pack(side="left")
        self.rb_before = ttk.Radiobutton(info, text="Before", value="before", variable=self.var_which,
                                         command=self.show_preview)
        self.rb_after = ttk.Radiobutton(info, text="After", value="after", variable=self.var_which,
                                        command=self.show_preview)
        self.rb_after.pack(side="right")
        self.rb_before.pack(side="right", padx=(0, 6))

        cap = ttk.LabelFrame(right, text="Caption (shown in the report)", padding=6)
        cap.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        cap.columnconfigure(0, weight=1)
        self.txt = tk.Text(cap, height=4, wrap="word", font=("Segoe UI", 10), undo=True)
        self.txt.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.txt.bind("<FocusOut>", lambda e: self.commit_caption())
        self.btn_reset = ttk.Button(cap, text="Reset to automatic wording", command=self.reset_caption)
        self.btn_reset.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.cmb_level = ttk.Combobox(cap, textvariable=self.var_level, values=list(LEVEL_LABEL.values()), width=9,
                                      state="readonly")
        self.cmb_level.grid(row=1, column=2, sticky="e", pady=(4, 0))
        self.cmb_level.bind("<<ComboboxSelected>>", lambda e: self._level_changed())

        mk = ttk.LabelFrame(right, text="Hide private information in the screenshot", padding=6)
        mk.grid(row=3, column=0, sticky="ew", pady=(6, 0))
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
        ttk.Label(out, text="Header").grid(row=0, column=0, sticky="w")
        ttk.Entry(out, textvariable=self.var_header).grid(row=0, column=1, sticky="ew", padx=(4, 12))
        ttk.Label(out, text="Footer").grid(row=0, column=2, sticky="w")
        ttk.Entry(out, textvariable=self.var_footer).grid(row=0, column=3, sticky="ew", padx=(4, 12))
        ttk.Label(out, text="Author").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(out, textvariable=self.var_author).grid(row=1, column=1, sticky="ew", padx=(4, 12), pady=(4, 0))
        ttk.Label(out, text="Logo").grid(row=1, column=2, sticky="w", pady=(4, 0))
        lg = ttk.Frame(out)
        lg.grid(row=1, column=3, sticky="ew", padx=(4, 12), pady=(4, 0))
        lg.columnconfigure(0, weight=1)
        ttk.Entry(lg, textvariable=self.var_logo).grid(row=0, column=0, sticky="ew")
        ttk.Button(lg, text="...", width=3, command=self.pick_logo).grid(row=0, column=1, padx=(4, 0))
        fm = ttk.Frame(out)
        fm.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        for k, label in rep.FORMATS.items():
            ttk.Checkbutton(fm, text=label, variable=self.var_fmt[k]).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(fm, text="Environment appendix", variable=self.var_env).pack(side="left", padx=(10, 0))
        ttk.Button(fm, text="Close", command=self.close).pack(side="right")
        ttk.Button(fm, text="Open folder", command=self.open_folder).pack(side="right", padx=4)
        ttk.Button(fm, text="Copy steps as text", command=self.copy_text).pack(side="right", padx=4)
        ttk.Button(fm, text="Export", command=self.export).pack(side="right", padx=4)

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
            kind += " (excluded)"
        return (n, kind, cap), tuple(tags)

    def refresh(self, select=None):
        keep = select if select is not None else list(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        nums = self.s.numbering()
        for st in self.s.steps:
            vals, tags = self._row(st, nums)
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
        self.commit_caption()
        sel = self.selected_steps()
        self._cur = sel[0] if len(sel) == 1 else None
        st = self._cur
        self.var_which.set("before")
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self._txt_wording = self.wording
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
        return rep.render_step_image(self.s, st, self.s.numbering().get(st.id))

    def show_preview(self):
        self.cv.delete("all")
        self._sel_rect = None
        self._drop_selbar()
        self._paint_mask_button(False)
        self.btn_clear.configure(state="disabled")
        st = self._cur
        img = self._current_image() if st else None
        cw, ch = max(self.cv.winfo_width(), 100), max(self.cv.winfo_height(), 100)
        if img is None:
            msg = "Select a single step to see its screenshot" if not st else "(no screenshot for this entry)"
            if st and st.kind in ("note", "section"):
                msg = "Text entry - edit the caption below"
            self.cv.create_text(cw // 2, ch // 2, text=msg, fill="#9aa0a6", font=("Segoe UI", 11))
            self.lbl_info.configure(text="" if not st else self._info(st))
            self._photo = None
            self._update_hint()
            return
        self._img_size = img.size
        self._scale = min(cw / img.width, ch / img.height, 1.0)
        size = (max(1, int(img.width * self._scale)), max(1, int(img.height * self._scale)))
        self._photo = ImageTk.PhotoImage(img.resize(size, Image.LANCZOS))
        self._off = ((cw - size[0]) // 2, (ch - size[1]) // 2)
        self.cv.create_image(self._off[0], self._off[1], image=self._photo, anchor="nw")
        self.lbl_info.configure(text=self._info(st))
        # hint banner (only on screen, never in the saved image)
        bx, by = self._off[0] + 8, self._off[1] + size[1] - 30
        t = self.cv.create_text(bx + 8, by + 11, anchor="w", fill="white", font=("Segoe UI", 9, "bold"), tags="hint",
                                text="To hide something: click and drag a box on the picture")
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
        self._sel_start = (e.x, e.y)
        if self._sel_rect:
            self.cv.delete(self._sel_rect)
        self.cv.delete("hint")
        self._drop_selbar()
        self._sel_rect = self.cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff3d00", width=2, dash=(4, 3),
                                                  fill="#ff3d00", stipple="gray25")

    def _sel_drag(self, e):
        if self._sel_rect and self._sel_start:
            self.cv.coords(self._sel_rect, self._sel_start[0], self._sel_start[1], e.x, e.y)

    def _sel_release(self, e):
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
            msg = f'Area selected. Pick a style, then click "Hide this area" - it will be applied to {scope}.'
        elif not self._cur or self._photo is None:
            msg = "Select a step with a screenshot, then drag a box on the picture to choose what to hide."
        else:
            msg = f"Drag a box on the picture to choose the area. It will be hidden on {scope}."
        ready = bool(self._sel_rect and self.btn_mask.cget("state") == "normal")
        self.lbl_hint.configure(foreground="#d84315" if ready else "gray")
        self.var_hint.set(msg + " Hiding permanently changes the saved screenshot(s).")

    def selection_in_image(self):
        """The dragged rectangle in image pixels (l, t, r, b), or None."""
        if not self._sel_rect:
            return None
        x0, y0, x1, y1 = self.cv.coords(self._sel_rect)
        ox, oy = self._off
        k = self._scale
        w, h = self._img_size
        l, r = sorted(((x0 - ox) / k, (x1 - ox) / k))
        t, b = sorted(((y0 - oy) / k, (y1 - oy) / k))
        l, t, r, b = max(0, l), max(0, t), min(w, r), min(h, b)
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
        self.show_preview()
        return count

    # ------------------------------------------------------------------ editing
    def commit_caption(self):
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
        if len(sel) != 1:
            return
        if self.s.move(sel[0], delta):
            self.s.save()
            self.refresh([sel[0].id])

    def delete_selected(self, confirm=True):
        sel = self.selected_steps()
        if not sel:
            return
        if confirm and not messagebox.askyesno(
                "Telestep", f"Delete {len(sel)} entr{'y' if len(sel) == 1 else 'ies'} and their screenshots?\n\n"
                "Tip: 'Exclude / include' hides a step from the report without deleting it.", parent=self):
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

    def _insert_index(self):
        sel = self.selected_steps()
        return self.s.steps.index(sel[0]) if sel else len(self.s.steps)

    def add_section(self, text=None):
        if text is None:
            text = self._ask_text("Section heading", "Heading for the steps that follow:")
        if not text:
            return None
        st = Step(new_id(), "section", friendly=text, tech=text)
        self.s.steps.insert(self._insert_index(), st)
        self.s.save()
        self.refresh([st.id])
        return st

    def add_note(self, text=None, level="note"):
        if text is None:
            dlg = w.NoteDialog(self)
            text, level = dlg.result, dlg.level
        if not text:
            return None
        st = Step(new_id(), "note", friendly=text, tech=text, level=level)
        self.s.steps.insert(self._insert_index(), st)
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
        return rep.Template(wording=self.wording, header=self.var_header.get().strip(),
                            footer=self.var_footer.get().strip(), logo=self.var_logo.get().strip(),
                            author=self.var_author.get().strip(), environment=self.var_env.get())

    def save(self):
        self.commit_caption()
        self._set_title()
        self.s.settings["template"] = self.template().to_dict()
        self.s.settings["wording"] = self.wording
        return self.s.save()

    def export(self, quiet=False):
        self.save()
        fmts = [k for k, v in self.var_fmt.items() if v.get()]
        if not fmts:
            messagebox.showinfo("Telestep", "Tick at least one format.", parent=self)
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
            (messagebox.showwarning if bad else messagebox.showinfo)(
                "Telestep", "\n".join(lines) + (f"\n\nDetails: {self.s.dir / 'save_errors.log'}" if bad else ""),
                parent=self)
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

    def close(self):
        self.save()
        self.destroy()
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
