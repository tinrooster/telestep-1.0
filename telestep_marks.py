"""
telestep_marks.py - mark-up tools of the review window (boxes, arrows, text, numbered call-outs), as a mixin.

Marks are stored per step in `Step.marks` (image pixels, see telestep_core.draw_marks) and drawn over the picture at
export time; the saved screenshot is never changed.

  * Tools row under the picture: Hide area | Select / move | Box | Arrow | Text | Number | Undo | Clear
  * Any mark tool grabs an existing mark that is clicked (drag = move; handles on boxes and arrow ends resize)
  * Text is typed straight onto the picture (drag a box first to set its width). Enter finishes, Shift+Enter starts
    a new line, Esc cancels. Double-click a text mark to edit it again.
  * A small bar floats beside the selected mark: colour, opacity, size, and for text the font, bold and background
  * Right-click the picture for the same things; Delete removes the selected mark, arrow keys nudge it
"""
import copy
import tkinter as tk
from tkinter import messagebox, ttk

import telestep_core as core

TOOLS = (("hide", "Hide area"), ("select", "Select / move"), ("box", "Box"), ("arrow", "Arrow"), ("text", "Text"),
         ("num", "Number"))
BANNER = {"hide": "To hide something: click and drag a box on the picture",
          "select": "Click a mark to select it, drag to move it. Right-click for more",
          "box": "Drag to draw a box",
          "arrow": "Drag to draw an arrow",
          "text": "Click (or drag a box) and type. Enter finishes, Shift+Enter = new line",
          "num": "Click to place a number"}
ONE_SHOT = " - then the tool switches back to Select / move"
DEFAULT_PROPS = {"c": "#1565c0", "a": 1.0, "z": 1.0, "f": "Sans", "b": True, "bg": "box"}
HANDLE = 5  # half-size of a resize handle, in screen pixels


def _dist_seg(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    n = dx * dx + dy * dy
    t = 0 if n == 0 else max(0, min(1, ((px - x0) * dx + (py - y0) * dy) / n))
    return ((px - (x0 + t * dx)) ** 2 + (py - (y0 + t * dy)) ** 2) ** 0.5


class MarkMixin:
    """Needs the host window to provide: cv, _scale, _off, _crop, _img_size, _photo, _cur, s (session), var_which,
    var_tool, show_preview(), clear_selection(), _ask_text(), _edits."""

    # ------------------------------------------------------------------ set-up
    def _init_marks(self):
        self.var_tool = tk.StringVar(value="hide")
        self.var_keep = tk.BooleanVar(value=False)  # keep the drawing tool after placing a mark
        self._mp = dict(DEFAULT_PROPS)  # properties given to the next new mark
        self._msel = None  # index of the selected mark in the current step
        self._mdrag = None  # active drag: {"mode", "start", "orig", "part"}
        self._ghost = []
        self._editor = None  # inline text editor: {"w", "win", "idx", "mark", "origin"}
        self._mbar = None  # floating property bar (frame) and the mark type it was built for
        self._mbar_for = None
        self._render_job = None

    def _build_marktools(self, parent, row):
        tb = ttk.Frame(parent)
        tb.grid(row=row, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(tb, text="Tools:").pack(side="left", padx=(0, 4))
        for val, lab in TOOLS:  # real raised buttons (sunken + blue when active) so they read as click targets
            tk.Radiobutton(tb, text=lab, value=val, variable=self.var_tool, indicatoron=False, relief="raised", bd=2,
                           padx=9, pady=1, selectcolor="#bbdefb", activebackground="#e3f2fd", cursor="hand2",
                           takefocus=False, command=self._tool_changed).pack(side="left", padx=(0, 3))
        ttk.Button(tb, text="Clear marks", command=self.clear_marks).pack(side="right")
        ttk.Button(tb, text="Undo mark", command=self.undo_mark).pack(side="right", padx=(0, 4))
        ttk.Checkbutton(tb, text="Keep tool", variable=self.var_keep, command=self.show_preview).pack(side="right", padx=(0, 10))
        self._marktb = tb
        return tb

    def _mark_toolbars(self):
        return [self._marktb] if getattr(self, "_marktb", None) else []

    # ------------------------------------------------------------------ coordinates
    def _to_image(self, x, y):
        cl, ct, _cr, _cb = self._crop
        k, (ox, oy) = self._scale, self._off
        return cl + (x - ox) / k, ct + (y - oy) / k

    def _to_canvas(self, ix, iy):
        cl, ct, _cr, _cb = self._crop
        k, (ox, oy) = self._scale, self._off
        return ox + (ix - cl) * k, oy + (iy - ct) * k

    def _marks(self):
        st = self._cur
        return st.marks if st and st.marks else []

    def _marks_ok(self):
        st = self._cur
        if not st or self._photo is None or not st.raw:
            return False
        if self.var_which.get() == "after":
            messagebox.showinfo("Telestep", "Marks go on the 'before' picture. Switch to Before first.", parent=self)
            return False
        return True

    # ------------------------------------------------------------------ tool changes
    def _tool_changed(self):
        self._commit_editor()
        self.clear_selection()
        if self.var_tool.get() == "hide":
            self._msel = None
        self.cv.configure(cursor="crosshair" if self.var_tool.get() == "hide" else "arrow")
        self.show_preview()  # the hint banner must change at once, not on the next drag

    def banner_text(self):
        t = self.var_tool.get()
        text = BANNER.get(t, "")
        if t in ("box", "arrow", "text", "num"):
            text += (" - choose Select / move when you are done" if self.var_keep.get() else ONE_SHOT)
        return text

    def _finish_create(self):
        """One-shot tools: after a mark is placed go back to Select / move, so the next click or drag moves it
        instead of adding another (tick 'Keep tool' to place several in a row)."""
        if self.var_tool.get() in ("box", "arrow", "text", "num") and not self.var_keep.get():
            self.var_tool.set("select")
            self._tool_changed()

    # ------------------------------------------------------------------ hit testing
    def _mark_hit(self, x, y, tol):
        """(index, part) of the topmost mark at an image point.  part: 'move' | 'a'..'d' (box corners) | 'p0' | 'p1'."""
        marks = self._marks()
        size = self._img_size
        order = list(range(len(marks)))[::-1]
        if self._msel is not None and self._msel < len(marks):  # the selected mark's handles win
            order.remove(self._msel)
            order.insert(0, self._msel)
        for i in order:
            m = marks[i]
            p = [float(v) for v in m.get("p", [])]
            t = m.get("t")
            sel = i == self._msel
            if t == "box" and len(p) == 4:
                l, tp, r, b = min(p[0], p[2]), min(p[1], p[3]), max(p[0], p[2]), max(p[1], p[3])
                if sel:
                    for part, (cx, cy) in (("a", (l, tp)), ("b", (r, tp)), ("c", (l, b)), ("d", (r, b))):
                        if abs(x - cx) <= tol * 1.4 and abs(y - cy) <= tol * 1.4:
                            return i, part
                edge = min(abs(x - l), abs(x - r), abs(y - tp), abs(y - b))
                inside = l - tol <= x <= r + tol and tp - tol <= y <= b + tol
                if inside and (edge <= tol or sel and l <= x <= r and tp <= y <= b):
                    return i, "move"
            elif t == "arrow" and len(p) == 4:
                for part, (cx, cy) in (("p0", (p[0], p[1])), ("p1", (p[2], p[3]))):
                    if abs(x - cx) <= tol * 1.4 and abs(y - cy) <= tol * 1.4 and (sel or part == "p1"):
                        return i, part
                if _dist_seg(x, y, p[0], p[1], p[2], p[3]) <= tol * 1.2:
                    return i, "move"
            else:
                bb = core.mark_bounds(m, size)
                if bb and t == "text" and sel:  # width handles on the left and right edges
                    midy = (bb[1] + bb[3]) / 2
                    for part, hx in (("r", bb[2]), ("l", bb[0])):
                        if abs(x - hx) <= tol * 1.4 and abs(y - midy) <= max(tol * 1.4, (bb[3] - bb[1]) / 2):
                            return i, part
                if bb and bb[0] - tol * 0.5 <= x <= bb[2] + tol * 0.5 and bb[1] - tol * 0.5 <= y <= bb[3] + tol * 0.5:
                    return i, "move"
        return None

    # ------------------------------------------------------------------ canvas events (called by the review window)
    def _mark_press(self, e):
        if self._editor:
            self._commit_editor()
            return
        if not self._marks_ok():
            return
        self.cv.focus_set()
        tool = self.var_tool.get()
        x, y = self._to_image(e.x, e.y)
        tol = 8 / max(self._scale, 0.1)
        hit = self._mark_hit(x, y, tol)
        if hit is not None:
            self._select(hit[0])
            self._mdrag = {"mode": hit[1], "start": (e.x, e.y), "orig": copy.deepcopy(self._marks()[hit[0]]),
                           "moved": False}
            return
        if tool == "select":
            self._select(None)
            return
        self._select(None)
        if tool == "num":
            n = 1 + sum(1 for m in self._marks() if m.get("t") == "num")
            self._add_mark({"t": "num", "p": [round(x, 1), round(y, 1)], "n": n, **self._new_props()})
            self._finish_create()
            return
        self._mdrag = {"mode": "new", "start": (e.x, e.y), "orig": None, "moved": False}
        if tool == "arrow":
            self._ghost = [self.cv.create_line(e.x, e.y, e.x, e.y, fill="#1565c0", width=3, arrow="last")]
        else:  # box, or the width of a text box
            self._ghost = [self.cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#1565c0", width=2,
                                                    dash=(4, 3) if tool == "text" else ())]

    def _mark_drag(self, e):
        d = self._mdrag
        if not d:
            return
        sx, sy = d["start"]
        if abs(e.x - sx) + abs(e.y - sy) > 3:
            d["moved"] = True
        if d["mode"] == "new":
            if self._ghost:
                self.cv.coords(self._ghost[0], sx, sy, e.x, e.y)
            return
        if not d["moved"]:
            return
        mark = self._applied(d, e)
        self._drop_ghost()
        self._ghost = self._ghost_for(mark)

    def _mark_release(self, e):
        d, self._mdrag = self._mdrag, None
        if not d:
            return
        self._drop_ghost()
        tool = self.var_tool.get()
        if d["mode"] == "new":
            sx, sy = d["start"]
            x0, y0 = self._to_image(sx, sy)
            x1, y1 = self._to_image(e.x, e.y)
            W, H = self._img_size
            clip = lambda v, m: round(max(0.0, min(float(m), v)), 1)
            moved = abs(x1 - x0) + abs(y1 - y0) >= 8 / max(self._scale, 0.1)
            if tool == "text":
                if moved:
                    self._edit_text(None, [clip(min(x0, x1), W), clip(min(y0, y1), H), clip(max(x0, x1), W),
                                           clip(max(y0, y1), H)])
                else:
                    self._edit_text(None, [clip(x0, W), clip(y0, H)])
            elif moved and tool in ("box", "arrow"):
                self._add_mark({"t": tool, "p": [clip(x0, W), clip(y0, H), clip(x1, W), clip(y1, H)],
                                **self._new_props()})
                self._finish_create()
            return
        if d["moved"]:
            marks = list(self._cur.marks)
            marks[self._msel] = self._applied(d, e)
            self._cur.marks = marks
            self._marks_changed()
        else:
            self.show_preview()  # a plain click just selects

    def _on_double_click(self, e):
        """Double-click a text mark to edit it."""
        if not self._cur or self.var_tool.get() == "hide" or self._photo is None:
            return
        x, y = self._to_image(e.x, e.y)
        hit = self._mark_hit(x, y, 8 / max(self._scale, 0.1))
        if hit is not None and self._marks()[hit[0]].get("t") == "text":
            self._mdrag = None
            self._select(hit[0])
            self._edit_text(hit[0])

    def _applied(self, d, e):
        """The dragged mark as it would be if released at the pointer position `e`."""
        sx, sy = d["start"]
        k = max(self._scale, 0.01)
        dx, dy = (e.x - sx) / k, (e.y - sy) / k
        m = copy.deepcopy(d["orig"])
        p = [float(v) for v in m["p"]]
        part = d["mode"]
        W, H = self._img_size
        if part == "move":
            p = [v + (dx if i % 2 == 0 else dy) for i, v in enumerate(p)]
        elif m["t"] == "text" and part in ("l", "r"):
            bb = core.mark_bounds(m, self._img_size)
            left, right = bb[0], bb[2]
            if part == "r":
                right = max(left + 60, right + dx)
            else:
                left = min(right - 60, left + dx)
            p = [left, bb[1], right, bb[1] + 1]
        elif m["t"] == "arrow" and part in ("p0", "p1"):
            i = 0 if part == "p0" else 2
            p[i], p[i + 1] = p[i] + dx, p[i + 1] + dy
        elif m["t"] == "box":
            l, t, r, b = min(p[0], p[2]), min(p[1], p[3]), max(p[0], p[2]), max(p[1], p[3])
            if part in ("a", "c"):
                l += dx
            else:
                r += dx
            if part in ("a", "b"):
                t += dy
            else:
                b += dy
            p = [l, t, r, b]
        m["p"] = [round(max(-20.0, min(W + 20.0, v)) if i % 2 == 0 else max(-20.0, min(H + 20.0, v)), 1)
                  for i, v in enumerate(p)]
        return m

    def _ghost_for(self, m):
        out = []
        if m.get("t") == "arrow":
            p = m["p"]
            (x0, y0), (x1, y1) = self._to_canvas(p[0], p[1]), self._to_canvas(p[2], p[3])
            out.append(self.cv.create_line(x0, y0, x1, y1, fill="#1565c0", width=3, arrow="last", dash=(4, 3)))
        else:
            bb = core.mark_bounds(m, self._img_size)
            if bb:
                x0, y0 = self._to_canvas(bb[0], bb[1])
                x1, y1 = self._to_canvas(bb[2], bb[3])
                out.append(self.cv.create_rectangle(x0, y0, x1, y1, outline="#1565c0", width=2, dash=(4, 3)))
        return out

    def _drop_ghost(self):
        for g in self._ghost:
            try:
                self.cv.delete(g)
            except tk.TclError:
                pass
        self._ghost = []

    # ------------------------------------------------------------------ changing marks
    def _new_props(self):
        return {k: self._mp[k] for k in ("c", "a", "z")}

    def _add_mark(self, mark, select=True):
        st = self._cur
        st.marks = list(st.marks or []) + [mark]
        self._msel = len(st.marks) - 1 if select else None
        self._marks_changed()

    def _marks_changed(self):
        self.s.save()
        self._edits += 1
        self.show_preview()

    def _select(self, idx):
        if idx != self._msel:
            self._msel = idx
            self._drop_markbar()
        self.show_preview()

    def _renumber(self):
        n = 0
        for m in self._marks():
            if m.get("t") == "num":
                n += 1
                m["n"] = n

    def delete_mark(self, idx=None):
        idx = self._msel if idx is None else idx
        st = self._cur
        if st is None or idx is None or not st.marks or idx >= len(st.marks):
            return
        del st.marks[idx]
        if not st.marks:
            st.marks = None
        self._renumber()
        self._msel = None
        self._drop_markbar()
        self._marks_changed()

    def undo_mark(self):
        st = self._cur
        if st and st.marks:
            self.delete_mark(len(st.marks) - 1)

    def clear_marks(self):
        st = self._cur
        if st and st.marks and messagebox.askyesno("Telestep", "Remove all marks from this picture?", parent=self):
            st.marks = None
            self._msel = None
            self._drop_markbar()
            self._marks_changed()

    def duplicate_mark(self):
        st = self._cur
        if st is None or self._msel is None:
            return
        m = copy.deepcopy(st.marks[self._msel])
        m["p"] = [v + 24 for v in m["p"]]
        if m.get("t") == "num":
            m["n"] = 1 + sum(1 for x in st.marks if x.get("t") == "num")
        self._add_mark(m)

    def reorder_mark(self, to_front=True):
        st = self._cur
        if st is None or self._msel is None:
            return
        m = st.marks.pop(self._msel)
        st.marks.insert(len(st.marks) if to_front else 0, m)
        self._msel = len(st.marks) - 1 if to_front else 0
        self._marks_changed()

    def nudge(self, dx, dy):
        st = self._cur
        if st is None or self._msel is None or self._editor:
            return "break"
        m = st.marks[self._msel]
        m["p"] = [round(v + (dx if i % 2 == 0 else dy), 1) for i, v in enumerate(m["p"])]
        self._marks_changed()
        return "break"

    # ------------------------------------------------------------------ drawing the selection (screen only)
    def _draw_mark_overlay(self):
        """Handles + frame around the selected mark and its floating property bar.  Called at the end of show_preview."""
        self._drop_ghost()
        marks = self._marks()
        if self._msel is None or self._msel >= len(marks) or self.var_which.get() == "after":
            self._drop_markbar()
            return
        m = marks[self._msel]
        bb = core.mark_bounds(m, self._img_size)
        if not bb:
            return
        x0, y0 = self._to_canvas(bb[0], bb[1])
        x1, y1 = self._to_canvas(bb[2], bb[3])
        self.cv.create_rectangle(x0, y0, x1, y1, outline="#00b0ff", width=1, dash=(3, 3), tags="mhandle")
        pts = []
        p = m["p"]
        if m["t"] == "arrow":
            pts = [self._to_canvas(p[0], p[1]), self._to_canvas(p[2], p[3])]
        elif m["t"] == "box":
            l, t, r, b = min(p[0], p[2]), min(p[1], p[3]), max(p[0], p[2]), max(p[1], p[3])
            pts = [self._to_canvas(l, t), self._to_canvas(r, t), self._to_canvas(l, b), self._to_canvas(r, b)]
        elif m["t"] == "text":  # drag the side handles to change the width; the text re-wraps
            my = (bb[1] + bb[3]) / 2
            pts = [self._to_canvas(bb[0], my), self._to_canvas(bb[2], my)]
        for cx, cy in pts:
            self.cv.create_rectangle(cx - HANDLE, cy - HANDLE, cx + HANDLE, cy + HANDLE, fill="white",
                                     outline="#0277bd", width=2, tags="mhandle")
        self._show_markbar(m, (x0, y0, x1, y1))

    # ------------------------------------------------------------------ floating property bar
    def _drop_markbar(self):
        if self._mbar is not None:
            try:
                self._mbar.destroy()
            except tk.TclError:
                pass
        self._mbar, self._mbar_for = None, None

    def _show_markbar(self, m, bounds):
        kind = m["t"]
        if self._mbar is None or self._mbar_for != (self._msel, kind):
            self._drop_markbar()
            self._mbar = self._build_markbar(m)
            self._mbar_for = (self._msel, kind)
        else:
            self._sync_markbar(m)
        bar = self._mbar
        cw, ch = self.cv.winfo_width(), self.cv.winfo_height()
        self.cv.create_window(cw // 2, ch - 6, window=bar, anchor="s", tags="mbar")  # docked: never in the way of the mark

    def _build_markbar(self, m):
        bg = "#eceff1"
        bar = tk.Frame(self.cv, bg=bg, padx=5, pady=4, highlightthickness=1, highlightbackground="#1565c0")
        self._mb = {}
        row = tk.Frame(bar, bg=bg)
        row.pack(anchor="w")
        # colours
        for name, hx in core.MARK_COLORS:
            b = tk.Button(row, bg=hx, width=2, relief="flat", bd=0, highlightthickness=2, highlightbackground=bg,
                          activebackground=hx, cursor="hand2", takefocus=False,
                          command=lambda hx=hx: self._set_prop("c", hx))
            b.pack(side="left", padx=1)
            self._mb["c:" + hx] = b
        # opacity
        tk.Label(row, text="Opacity", bg=bg, font=("Segoe UI", 9)).pack(side="left", padx=(10, 2))
        self._mb["a"] = tk.Scale(row, from_=20, to=100, orient="horizontal", length=90, showvalue=False, bg=bg,
                                 highlightthickness=0, bd=0, sliderlength=14, takefocus=False, command=self._opacity_moved)
        self._mb["a"].pack(side="left")
        self._mb["alab"] = tk.Label(row, text="100%", bg=bg, width=4, font=("Segoe UI", 9))
        self._mb["alab"].pack(side="left")
        # size
        tk.Label(row, text="Size", bg=bg, font=("Segoe UI", 9)).pack(side="left", padx=(6, 2))
        self._mb["z"] = ttk.Combobox(row, values=list(core.MARK_SIZES), width=3, state="readonly")
        self._mb["z"].pack(side="left")
        self._mb["z"].bind("<<ComboboxSelected>>", lambda e: self._set_prop("z", core.MARK_SIZES[self._mb["z"].get()]))
        tk.Button(row, text="Delete", bg="#c62828", fg="white", relief="flat", cursor="hand2", takefocus=False,
                  font=("Segoe UI", 9), padx=8, command=self.delete_mark).pack(side="left", padx=(10, 0))
        if m["t"] == "text":
            row2 = tk.Frame(bar, bg=bg)
            row2.pack(anchor="w", pady=(4, 0))
            tk.Label(row2, text="Font", bg=bg, font=("Segoe UI", 9)).pack(side="left", padx=(0, 2))
            self._mb["f"] = ttk.Combobox(row2, values=core.MARK_FONTS, width=11, state="readonly")
            self._mb["f"].pack(side="left")
            self._mb["f"].bind("<<ComboboxSelected>>", lambda e: self._set_prop("f", self._mb["f"].get()))
            self._mb["b"] = tk.Button(row2, text="B", font=("Segoe UI", 9, "bold"), width=2, relief="groove",
                                      cursor="hand2", takefocus=False, command=lambda: self._set_prop(
                                          "b", not bool(self._marks()[self._msel].get("b", True))))
            self._mb["b"].pack(side="left", padx=(6, 0))
            tk.Label(row2, text="Background", bg=bg, font=("Segoe UI", 9)).pack(side="left", padx=(10, 2))
            self._mb["bg"] = ttk.Combobox(row2, values=["Boxed", "Plain"], width=6, state="readonly")
            self._mb["bg"].pack(side="left")
            self._mb["bg"].bind("<<ComboboxSelected>>",
                                lambda e: self._set_prop("bg", "box" if self._mb["bg"].get() == "Boxed" else "plain"))
            tk.Button(row2, text="Edit text", relief="flat", bg="#546e7a", fg="white", cursor="hand2", takefocus=False,
                      font=("Segoe UI", 9), padx=8, command=lambda: self._edit_text(self._msel)).pack(side="left",
                                                                                                    padx=(10, 0))
        self._sync_markbar(m)
        return bar

    def _sync_markbar(self, m):
        mb = self._mb
        cur = str(m.get("c", "#1565c0")).lower()
        for k, b in mb.items():
            if k.startswith("c:"):
                b.configure(highlightbackground="#0d47a1" if k[2:] == cur else "#eceff1")
        a = int(round(core._mark_alpha(m) * 100))
        if int(float(mb["a"].get())) != a:
            mb["a"].set(a)
        mb["alab"].configure(text=f"{a}%")
        z = float(m.get("z", 1.0))
        mb["z"].set(min(core.MARK_SIZES, key=lambda n: abs(core.MARK_SIZES[n] - z)))
        if "f" in mb:
            mb["f"].set(core.font_family(m.get("f") or "Sans"))
            mb["b"].configure(relief="sunken" if m.get("b", True) else "raised")
            mb["bg"].set("Boxed" if m.get("bg", "box") == "box" else "Plain")

    def _set_prop(self, key, value):
        st = self._cur
        if st is None or self._msel is None:
            return
        st.marks[self._msel][key] = value
        self._mp[key] = value  # the next new mark starts with what was chosen last
        self._schedule_render()

    def _opacity_moved(self, v):
        st = self._cur
        if st is None or self._msel is None or not st.marks or self._msel >= len(st.marks):
            return
        a = round(int(float(v)) / 100, 2)
        if abs(core._mark_alpha(st.marks[self._msel]) - a) < 0.005:
            return
        self._mb["alab"].configure(text=f"{int(float(v))}%")
        st.marks[self._msel]["a"] = a
        self._mp["a"] = a
        self._schedule_render()

    def _schedule_render(self):
        if self._render_job is None:
            self._render_job = self.after(60, self._render_now)

    def _render_now(self):
        self._render_job = None
        self.s.save()
        self._edits += 1
        self.show_preview()

    # ------------------------------------------------------------------ inline text editing
    def _edit_text(self, idx=None, at=None):
        """Type text straight onto the picture.  idx = edit that mark; otherwise create one at `at` (image px,
        [x, y] or a dragged [x0, y0, x1, y1] box)."""
        self._commit_editor()
        if not self._marks_ok():
            return
        if idx is not None:
            mark = copy.deepcopy(self._marks()[idx])
        else:
            mark = {"t": "text", "p": at, "text": "", "c": self._mp["c"], "a": self._mp["a"], "z": self._mp["z"],
                    "f": self._mp["f"], "b": self._mp["b"], "bg": self._mp["bg"]}
        p = mark["p"]
        bb = core.mark_bounds(mark, self._img_size) if mark.get("text") else None
        k = self._scale
        left, top = self._to_canvas(*(bb[:2] if bb else (min(p[0], p[2]) if len(p) == 4 else p[0],
                                                          min(p[1], p[3]) if len(p) == 4 else p[1])))
        if len(p) == 4 and abs(p[2] - p[0]) > 30:
            width = abs(p[2] - p[0]) * k
        elif bb:
            width = max(160, (bb[2] - bb[0]) * k + 12)
        else:
            width = 240
        unit = core._mark_unit(mark, self._img_size[0])
        px = max(9, int(20 * unit * k))
        fam = core.TK_FONTS[core.font_family(mark.get("f") or "Sans")]
        col = mark.get("c", "#1565c0")
        w = tk.Text(self.cv, wrap="word", font=(fam, -px, "bold" if mark.get("b", True) else "normal"), fg=col,
                    bg="white", insertbackground=col, relief="solid", bd=2, highlightthickness=0, padx=4, pady=2,
                    undo=True)
        w.insert("1.0", mark.get("text", ""))
        win = self.cv.create_window(left, top, window=w, anchor="nw", width=width, height=px * 2 + 12, tags="editor")
        self._editor = {"w": w, "win": win, "idx": idx, "mark": mark, "px": px, "width": width}
        self.cv.delete("hint")
        self._banner("Type your text. Enter finishes, Shift+Enter = new line, Esc cancels")

        def fit(_e=None):
            try:
                lines = int(w.count("1.0", "end", "displaylines")[0])
            except (tk.TclError, TypeError, IndexError):
                lines = 1
            self.cv.itemconfigure(win, height=max(1, lines) * int(px * 1.35) + 12)

        w.bind("<KeyRelease>", fit)
        w.bind("<Return>", lambda e: (self._commit_editor(), "break")[1])
        w.bind("<Shift-Return>", lambda e: None)
        w.bind("<Escape>", lambda e: (self._cancel_editor(), "break")[1])
        w.bind("<FocusOut>", lambda e: self.after(120, self._commit_if_blurred))
        fit()
        w.focus_set()
        w.tag_add("sel", "1.0", "end-1c") if mark.get("text") else None

    def _commit_if_blurred(self):
        ed = self._editor
        if ed and self.focus_get() is not ed["w"]:
            self._commit_editor()

    def _cancel_editor(self):
        ed, self._editor = self._editor, None
        if ed:
            try:
                ed["w"].destroy()
                self.cv.delete("editor")
            except tk.TclError:
                pass
            self.show_preview()

    def _commit_editor(self):
        ed, self._editor = self._editor, None
        if not ed:
            return
        try:
            text = ed["w"].get("1.0", "end").strip()
            ed["w"].destroy()
            self.cv.delete("editor")
        except tk.TclError:
            return
        st = self._cur
        if st is None:
            return
        if ed["idx"] is None:
            if text:
                mark = ed["mark"]
                mark["text"] = text
                self._add_mark(mark)
                self._finish_create()
            else:
                self.show_preview()
            return
        marks = st.marks or []
        if ed["idx"] >= len(marks):
            return
        if not text:
            self.delete_mark(ed["idx"])
        elif text != marks[ed["idx"]].get("text"):
            marks[ed["idx"]]["text"] = text
            self._marks_changed()
        else:
            self.show_preview()

    def _banner(self, text):
        bx, by = self._off[0] + 8, self._off[1] + int(self._img_size[1] * self._scale) - 30
        t = self.cv.create_text(bx + 8, by + 11, anchor="w", fill="white", font=("Segoe UI", 9, "bold"), tags="hint",
                                text=text)
        x0, y0, x1, y1 = self.cv.bbox(t)
        r = self.cv.create_rectangle(x0 - 8, y0 - 4, x1 + 8, y1 + 4, fill="#37474f", outline="", tags="hint")
        self.cv.tag_lower(r, t)

    # ------------------------------------------------------------------ right-click menu pieces
    def _mark_menu(self, m, e):
        """Add mark-related entries to the picture's right-click menu `m` (e = the click)."""
        x, y = self._to_image(e.x, e.y)
        hit = self._mark_hit(x, y, 8 / max(self._scale, 0.1)) if self._cur and self._photo is not None else None
        if hit is not None:
            self._select(hit[0])
            mk = self._marks()[hit[0]]
            if mk.get("t") == "text":
                m.add_command(label="Edit text", command=lambda i=hit[0]: self._edit_text(i))
            m.add_command(label="Duplicate mark", command=self.duplicate_mark)
            m.add_command(label="Bring to front", command=lambda: self.reorder_mark(True))
            m.add_command(label="Send to back", command=lambda: self.reorder_mark(False))
            m.add_command(label="Delete mark", accelerator="Del", command=self.delete_mark)
            m.add_separator()
        sub = tk.Menu(m, tearoff=0)
        for val, lab in TOOLS:
            sub.add_radiobutton(label=lab, value=val, variable=self.var_tool, command=self._tool_changed)
        sub.add_separator()
        ok = bool(self._cur and self._photo is not None and self._cur.raw and self.var_which.get() != "after")
        W, H = self._img_size
        inside = ok and 0 <= x <= W and 0 <= y <= H
        sub.add_command(label="Add text here", state="normal" if inside else "disabled",
                        command=lambda: self._menu_text(x, y))
        sub.add_command(label="Add number here", state="normal" if inside else "disabled",
                        command=lambda: self._menu_num(x, y))
        sub.add_separator()
        sub.add_command(label="Undo last mark", command=self.undo_mark, state="normal" if self._marks() else "disabled")
        sub.add_command(label="Clear all marks", command=self.clear_marks, state="normal" if self._marks() else "disabled")
        m.add_cascade(label="Annotate", menu=sub)
        m.add_separator()

    def _menu_text(self, x, y):
        if self.var_tool.get() == "hide":
            self.var_tool.set("select")
            self._tool_changed()
        self._edit_text(None, [round(x, 1), round(y, 1)])

    def _menu_num(self, x, y):
        if self.var_tool.get() == "hide":
            self.var_tool.set("select")
            self._tool_changed()
        n = 1 + sum(1 for m in self._marks() if m.get("t") == "num")
        self._add_mark({"t": "num", "p": [round(x, 1), round(y, 1)], "n": n, **self._new_props()})
