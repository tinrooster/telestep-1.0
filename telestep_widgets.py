"""
telestep_widgets.py - Tk building blocks for the Telestep toolbar: icons, tooltips, click-through
screen overlays (capture frame / masks / taskbar), the area picker, note and window-picker dialogs.
"""
import ctypes
import json
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from PIL import Image, ImageDraw, ImageTk

import telestep_core as core

NOTE_TITLE = "Telestep Note"
PICK_TITLE = "Telestep Area"
WINPICK_TITLE = "Telestep Windows"
OVERLAY_TITLE = "Telestep Overlay"

COL_REC, COL_PAUSE, COL_PREVIEW = "#e53935", "#f59e0b", "#2979ff"
COL_MASK, COL_EXCL, COL_FLASH = "#d500f9", "#757575", "#ffffff"


# ---------- small Windows helpers (all no-ops elsewhere) ----------
def _hwnd(widget):
    return ctypes.windll.user32.GetAncestor(widget.winfo_id(), 2)  # GA_ROOT


def exclude_from_capture(widget, on=True):
    try:
        widget.update_idletasks()
        ctypes.windll.user32.SetWindowDisplayAffinity(_hwnd(widget), 0x11 if on else 0)  # WDA_EXCLUDEFROMCAPTURE
    except Exception:
        pass


def window_screen_rect(widget):
    """Screen rectangle (l, t, r, b) of a Tk window including its title bar, or None."""
    try:
        from ctypes import wintypes
        rc = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(_hwnd(widget), ctypes.byref(rc))
        return (rc.left, rc.top, rc.right, rc.bottom)
    except Exception:
        return None


def list_screens():
    """mss monitor list: index 0 = whole virtual desktop, 1..N = individual monitors."""
    try:
        import mss
        with (getattr(mss, "MSS", None) or mss.mss)() as sct:
            return [dict(m) for m in sct.monitors]
    except Exception:
        return []


# ---------- icons (drawn at 6x and downsampled, so no font or image files needed) ----------
def make_icon(kind, color, size=20):
    S = size * 6
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def f(v):
        return v * S

    if kind == "record":
        d.ellipse([f(.16), f(.16), f(.84), f(.84)], fill=color)
    elif kind == "pause":
        d.rounded_rectangle([f(.22), f(.16), f(.42), f(.84)], radius=f(.04), fill=color)
        d.rounded_rectangle([f(.58), f(.16), f(.78), f(.84)], radius=f(.04), fill=color)
    elif kind == "resume":
        d.polygon([(f(.26), f(.14)), (f(.26), f(.86)), (f(.86), f(.5))], fill=color)
    elif kind == "stop":
        d.rounded_rectangle([f(.2), f(.2), f(.8), f(.8)], radius=f(.08), fill=color)
    elif kind == "note":
        d.polygon([(f(.2), f(.1)), (f(.62), f(.1)), (f(.82), f(.3)), (f(.82), f(.9)), (f(.2), f(.9))], fill=color)
        d.polygon([(f(.62), f(.1)), (f(.62), f(.3)), (f(.82), f(.3))], fill=(255, 255, 255, 150))
        for y in (.5, .64, .78):
            d.rectangle([f(.3), f(y - .03), f(.7), f(y + .03)], fill=(255, 255, 255, 235))
    elif kind == "folder":
        d.polygon([(f(.08), f(.26)), (f(.4), f(.26)), (f(.48), f(.36)), (f(.92), f(.36)),
                   (f(.92), f(.82)), (f(.08), f(.82))], fill=color)
    elif kind == "camera":
        d.rounded_rectangle([f(.08), f(.28), f(.92), f(.84)], radius=f(.08), fill=color)
        d.rectangle([f(.32), f(.18), f(.5), f(.3)], fill=color)
        d.ellipse([f(.31), f(.36), f(.69), f(.76)], fill=(255, 255, 255, 235))
        d.ellipse([f(.39), f(.44), f(.61), f(.68)], fill=color)
    elif kind == "help":
        d.ellipse([f(.08), f(.08), f(.92), f(.92)], fill=color)
        d.text((S / 2, S / 2 + f(.02)), "?", fill=(255, 255, 255, 255), font=core.get_font(f(.62), bold=True), anchor="mm")
    elif kind == "review":
        for y in (.24, .5, .76):
            d.ellipse([f(.1), f(y - .06), f(.22), f(y + .06)], fill=color)
            d.rounded_rectangle([f(.32), f(y - .05), f(.9), f(y + .05)], radius=f(.03), fill=color)
    elif kind == "gear":
        import math
        c = S / 2
        for i in range(8):
            a = math.radians(i * 45)
            d.line([(c + math.cos(a) * f(.2), c + math.sin(a) * f(.2)),
                    (c + math.cos(a) * f(.43), c + math.sin(a) * f(.43))], fill=color, width=int(f(.15)))
        d.ellipse([f(.2), f(.2), f(.8), f(.8)], fill=color)
        d.ellipse([f(.38), f(.38), f(.62), f(.62)], fill=(0, 0, 0, 0))
    return ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))


class Tip:
    """Tiny hover tooltip for icon-only buttons."""

    def __init__(self, widget, text):
        self.w, self.text, self.tw, self.job = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._hide()
        self.job = self.w.after(450, self._show)

    def _show(self):
        self.job = None
        self.tw = tw = tk.Toplevel(self.w)
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        tk.Label(tw, text=self.text, bg="#ffffe0", fg="black", relief="solid", bd=1,
                 font=("Segoe UI", 9), padx=4, pady=1).pack()
        tw.geometry(f"+{self.w.winfo_rootx()}+{self.w.winfo_rooty() + self.w.winfo_height() + 4}")
        exclude_from_capture(tw)

    def _hide(self, _e=None):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.tw:
            self.tw.destroy()
            self.tw = None



# ---------- on-screen overlays ----------
class Overlay(tk.Toplevel):
    """Borderless, always-on-top, click-through window, excluded from screen captures."""

    def __init__(self, root, bg, alpha, text="", anchor="w", font=("Segoe UI", 9, "bold"), hide_fn=None):
        super().__init__(root)
        self.title(OVERLAY_TITLE)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", alpha)  # must be < 1 so Windows treats it as a layered window
        self.configure(bg=bg)
        self.lbl = tk.Label(self, text=text, bg=bg, fg="white", font=font, anchor=anchor, bd=0, padx=6, pady=1)
        self.lbl.pack(fill="both", expand=True)
        self.hide_fn = hide_fn or (lambda: True)
        self._bg, self._text, self._geo = bg, text, None
        self._auto = None
        self._visible = self._styled = False
        self.withdraw()

    def apply_affinity(self):
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(_hwnd(self), 0x11 if self.hide_fn() else 0)
        except Exception:
            pass

    def _style(self):
        try:
            self.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = _hwnd(self)
            ex = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            # LAYERED | TRANSPARENT (click-through) | TOOLWINDOW | NOACTIVATE
            user32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x08000000)
        except Exception:
            pass
        self.apply_affinity()

    def show(self, l, t, w=None, h=None, bg=None, text=None):
        """Place/style the window. Returns True if it just became visible."""
        changed = False
        if bg is not None and bg != self._bg:
            self._bg = bg
            self.configure(bg=bg)
            self.lbl.configure(bg=bg)
        if text is not None and text != self._text:
            self._text = text
            self.lbl.configure(text=text)
            changed = True
        if w is None or h is None:  # size to the label text
            if changed or self._auto is None:
                self.update_idletasks()
                self._auto = (self.lbl.winfo_reqwidth(), self.lbl.winfo_reqheight())
            w, h = self._auto
        geo = f"{max(1, int(w))}x{max(1, int(h))}+{int(l)}+{int(t)}"
        if geo != self._geo:
            self._geo = geo
            self.geometry(geo)
        if not self._visible:
            self.deiconify()
            self._visible = True
            if not self._styled:
                self.update_idletasks()
                self._style()
                self._styled = True
            return True
        return False

    def hide(self):
        if self._visible:
            self.withdraw()
            self._visible = False


class OverlayManager:
    """Draws what is (and isn't) being captured: frame, tag, taskbar shading, mask shading."""

    def __init__(self, app):
        self.app = app
        self.bars, self.tag, self.shades = [], None, []
        self.last_box = None
        self._strips, self._strips_t = [], 0.0
        self._win_cache = {}

    def _all(self):
        return self.bars + ([self.tag] if self.tag else []) + self.shades

    def _ensure(self):
        if self.bars:
            return
        root, hide_fn = self.app.root, self.app.var_hide.get
        self.bars = [Overlay(root, COL_PREVIEW, 0.9, hide_fn=hide_fn) for _ in range(4)]
        self.tag = Overlay(root, COL_PREVIEW, 0.93, text=" ", hide_fn=hide_fn)

    def _shade(self, i):
        while len(self.shades) <= i:
            self.shades.append(Overlay(self.app.root, COL_MASK, 0.42, anchor="center",
                                       font=("Segoe UI", 11, "bold"), hide_fn=self.app.var_hide.get))
        return self.shades[i]

    def hide(self):
        for o in self._all():
            o.hide()

    def apply_affinity(self):
        for o in self._all():
            o.apply_affinity()

    def _taskbar_strips(self, screens):
        now = time.monotonic()
        if now - self._strips_t > 2.0:  # the taskbar rarely moves; don't poll Windows every tick
            self._strips = core.taskbar_strips(screens)
            self._strips_t = now
        return self._strips

    def _window_rects(self, title):
        now = time.monotonic()
        t, rects = self._win_cache.get(title, (0, []))
        if now - t > 0.4:  # follow the window, but don't enumerate windows on every tick
            rects = core.find_windows(title)
            self._win_cache[title] = (now, rects)
        return rects

    def update(self, state):
        app = self.app
        screens = app.screens
        if len(screens) < 2:
            self.hide()
            return
        self._ensure()
        mode, monitor = app.current_mode()
        opts = app.capture_opts()
        pos = core.cursor_pos() or (screens[1]["left"] + 10, screens[1]["top"] + 10)
        key = (mode, monitor, opts.exclude_taskbar, opts.region)
        if key != getattr(self, "_key", None):  # setting changed: a remembered outline would be stale
            self._key, self.last_box = key, None

        # Fixed areas are evaluated at their centre; "screen"/"window" follow the cursor.
        box = None
        if mode == "monitor":
            m = screens[monitor] if 1 <= monitor < len(screens) else screens[1]
            box = core.capture_box(opts, screens, m["left"] + m["width"] // 2, m["top"] + m["height"] // 2)
        elif mode == "region":
            if app.region:
                l, t, r, b = app.region
                box = core.capture_box(opts, screens, (l + r) // 2, (t + b) // 2)
        elif mode == "window" and app.over_toolbar(pos):
            # hovering the toolbar: keep the last real window, or (nothing yet) the screen being used
            box = self.last_box or core.capture_box(
                type(opts)("screen", monitor, opts.region, opts.exclude_taskbar, opts.masks), screens, *pos)
        else:
            box = core.capture_box(opts, screens, *pos)
        self.last_box = box or self.last_box

        color, head = {"rec": (COL_REC, "● REC"), "paused": (COL_PAUSE, "‖ PAUSED"),
                       "preview": (COL_PREVIEW, "PREVIEW")}[state]
        if app.flash_active():
            color = COL_FLASH  # brief white flash = a screenshot was just taken
        newly = False
        if box:
            B = app.bar_px
            l, t, w, h = box["left"], box["top"], box["width"], box["height"]
            rects = [(l, t, w, B), (l, t + h - B, w, B), (l, t + B, B, h - 2 * B), (l + w - B, t + B, B, h - 2 * B)]
            for o, (x, y, ww, hh) in zip(self.bars, rects):
                newly |= o.show(x, y, ww, hh, bg=color)
            newly |= self.tag.show(l + B, t + B, bg=color, text=f"{head}  {app.scope_text()}")
        else:
            for o in self.bars:
                o.hide()
            newly |= self.tag.show(screens[1]["left"] + 10, screens[1]["top"] + 10, bg=color,
                                   text=f"{head}  choose a custom area")

        items = []
        for m in app.masks:
            label = "MASKED - " + core.MASK_STYLES.get(m.style, m.style).split(" (")[0].lower()
            for r in ([m.rect] if m.rect else self._window_rects(m.title)):
                items.append((core._box(*r), COL_MASK, label))
        if app.var_taskbar.get():
            strips = self._taskbar_strips(screens)
            if mode != "all" and box:  # only the monitor being captured
                cx, cy = box["left"] + box["width"] // 2, box["top"] + box["height"] // 2
                mon = next((m for m in screens[1:] if core._contains(m, cx, cy)), None)
                if mon:
                    strips = [s for s in strips if core._contains(mon, (s[0] + s[2]) // 2, (s[1] + s[3]) // 2)]
            items += [(core._box(*s), COL_EXCL, "EXCLUDED") for s in strips]
        for i, (b, col, txt) in enumerate(items):
            newly |= self._shade(i).show(b["left"], b["top"], b["width"], b["height"], bg=col, text=txt)
        for extra in self.shades[len(items):]:
            extra.hide()
        if newly:
            app.root.lift()  # keep the toolbar above the overlays


# ---------- dialogs ----------
def pick_area(root, screens):
    """Translucent overlay across the whole desktop; drag to choose a rectangle.
    Returns (left, top, right, bottom) in screen pixels, or None if cancelled."""
    if screens:
        vs = screens[0]
    else:
        vs = {"left": 0, "top": 0, "width": root.winfo_screenwidth(), "height": root.winfo_screenheight()}
    top = tk.Toplevel(root)
    top.title(PICK_TITLE)
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    top.attributes("-alpha", 0.30)
    top.geometry(f"{vs['width']}x{vs['height']}+{vs['left']}+{vs['top']}")
    cv = tk.Canvas(top, bg="black", highlightthickness=0, cursor="crosshair")
    cv.pack(fill="both", expand=True)
    prim = screens[1] if len(screens) > 1 else vs
    cv.create_text(prim["left"] - vs["left"] + prim["width"] // 2, prim["top"] - vs["top"] + 60,
                   text="Drag to select an area  •  Esc or right-click to cancel",
                   fill="white", font=("Segoe UI", 18))
    state = {"start": None, "start_root": None, "rect": None, "result": None}

    def press(e):
        state["start"], state["start_root"] = (e.x, e.y), (e.x_root, e.y_root)
        state["rect"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=3)

    def drag(e):
        if state["rect"] is not None:
            cv.coords(state["rect"], state["start"][0], state["start"][1], e.x, e.y)

    def release(e):
        if state["start_root"] is None:
            return
        x0, y0 = state["start_root"]
        l, t, r, b = min(x0, e.x_root), min(y0, e.y_root), max(x0, e.x_root), max(y0, e.y_root)
        if r - l >= 20 and b - t >= 20:
            state["result"] = (l, t, r, b)
        top.destroy()

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", drag)
    cv.bind("<ButtonRelease-1>", release)
    cv.bind("<Button-3>", lambda e: top.destroy())
    top.bind("<Escape>", lambda e: top.destroy())
    top.update()
    top.focus_force()
    cv.focus_set()
    top.grab_set()
    root.wait_window(top)
    return state["result"]


class NoteDialog(tk.Toplevel):
    """Resizable multi-line note entry. Ctrl+Enter adds, Esc cancels. `result` is the text or None."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title(NOTE_TITLE)
        self.attributes("-topmost", True)
        self.transient(parent)
        self.result = None
        self.level = "note"
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        frm = ttk.Frame(self, padding=8)
        frm.grid(sticky="nsew")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)
        ttk.Label(frm, text="Note  (Ctrl+Enter to add, Esc to cancel)").grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.txt = tk.Text(frm, width=64, height=12, wrap="word", font=("Segoe UI", 10), undo=True)
        sb = ttk.Scrollbar(frm, command=self.txt.yview)
        self.txt.config(yscrollcommand=sb.set)
        self.txt.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        sb.grid(row=1, column=1, sticky="ns", pady=(4, 0))
        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        btns.columnconfigure(3, weight=1)
        self._lvl = tk.StringVar(value="note")
        for i, (val, lab) in enumerate((("note", "Note"), ("warning", "Warning"), ("tip", "Tip"))):
            ttk.Radiobutton(btns, text=lab, value=val, variable=self._lvl).grid(row=0, column=i, padx=(0, 8))
        ttk.Button(btns, text="Cancel", command=self.destroy).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(btns, text="Add", command=self.ok).grid(row=0, column=5)
        self.bind("<Control-Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        x = parent.winfo_rootx()
        y = parent.winfo_rooty() + parent.winfo_height() + 8
        if y + self.winfo_reqheight() > self.winfo_screenheight():
            y = max(0, parent.winfo_rooty() - self.winfo_reqheight() - 8)
        self.geometry(f"+{x}+{y}")
        self.txt.focus_set()
        self.grab_set()
        self.wait_window(self)

    def ok(self):
        self.result = self.txt.get("1.0", "end").strip()
        self.level = self._lvl.get()
        self.destroy()


class WindowPicker(tk.Toplevel):
    """Pick (or type) part of a window title.  `result` is the text or None."""

    def __init__(self, parent, prompt="Hide any window whose title contains:"):
        super().__init__(parent)
        self.title(WINPICK_TITLE)
        self.attributes("-topmost", True)
        self.transient(parent)
        self.result = None
        frm = ttk.Frame(self, padding=8)
        frm.grid(sticky="nsew")
        frm.columnconfigure(0, weight=1)
        ttk.Label(frm, text="Open windows (double-click one, or type your own text below):").grid(sticky="w")
        self.lst = tk.Listbox(frm, width=60, height=12, exportselection=False)
        self.lst.grid(row=1, column=0, sticky="nsew", pady=(4, 6))
        titles = []
        for w in core.list_windows():
            if w["title"] not in titles and w["title"] not in (NOTE_TITLE, PICK_TITLE, WINPICK_TITLE, OVERLAY_TITLE):
                titles.append(w["title"])
        for t in titles:
            self.lst.insert("end", t)
        ttk.Label(frm, text=prompt).grid(row=2, sticky="w")
        self.var = tk.StringVar()
        ent = ttk.Entry(frm, textvariable=self.var)
        ent.grid(row=3, sticky="ew", pady=(2, 8))
        btns = ttk.Frame(frm)
        btns.grid(row=4, sticky="e")
        ttk.Button(btns, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text="Add", command=self.ok).grid(row=0, column=1)
        self.lst.bind("<<ListboxSelect>>", lambda e: self.var.set(self.lst.get(self.lst.curselection()[0]))
                      if self.lst.curselection() else None)
        self.lst.bind("<Double-Button-1>", lambda e: self.ok())
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx()}+{parent.winfo_rooty() + parent.winfo_height() + 8}")
        ent.focus_set()
        self.grab_set()
        self.wait_window(self)

    def ok(self):
        self.result = self.var.get().strip() or None
        self.destroy()


def list_sessions(base, limit=200):
    """[(folder, created 'YYYY-MM-DD HH:MM', title, step count)] for recordings found in `base`, newest first."""
    rows = []
    try:
        kids = [d for d in Path(base).iterdir() if d.is_dir() and (d / "session.json").exists()]
    except OSError:
        return rows
    for d in kids:
        try:
            data = json.loads((d / "session.json").read_text(encoding="utf-8"))
            steps = sum(1 for st in data.get("steps", []) if st.get("kind") not in ("note", "section") and not st.get("skip"))
            created = str(data.get("created", "")).replace("T", " ")[:16]
            rows.append((d, created or time.strftime("%Y-%m-%d %H:%M", time.localtime(d.stat().st_mtime)),
                         data.get("title", d.name), steps))
        except (OSError, ValueError):
            continue
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:limit]


class SessionPicker(tk.Toplevel):
    """'Open a recording': Telestep's own list of saved recordings (newest first).  `result` is a folder or None."""

    def __init__(self, parent, base):
        super().__init__(parent)
        self.title("Telestep - Open a recording")
        self.transient(parent)
        self.result = None
        self.base = Path(base)
        frm = ttk.Frame(self, padding=10)
        frm.grid(sticky="nsew")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)
        ttk.Label(frm, text="Pick a recording to review, edit or export (newest first):").grid(sticky="w")
        self.rows = list_sessions(self.base)
        self.tree = ttk.Treeview(frm, columns=("when", "title", "steps"), show="headings", height=10, selectmode="browse")
        for col, text, width in (("when", "Recorded", 120), ("title", "Title", 300), ("steps", "Steps", 50)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="e" if col == "steps" else "w", stretch=(col == "title"))
        for i, (_d, when, title, n) in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(i), values=(when, title, n))
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(4, 4))
        ttk.Label(frm, text=f"In: {self.base}" if self.rows else f"No recordings found yet in: {self.base}",
                  foreground="gray").grid(row=2, sticky="w")
        btns = ttk.Frame(frm)
        btns.grid(row=3, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Browse for another folder...", command=self.browse).grid(row=0, column=0, padx=(0, 12))
        ttk.Button(btns, text="Cancel", command=self.destroy).grid(row=0, column=1, padx=(0, 6))
        self.btn_open = ttk.Button(btns, text="Open", command=self.ok, state="normal" if self.rows else "disabled")
        self.btn_open.grid(row=0, column=2)
        self.tree.bind("<Double-Button-1>", lambda e: self.ok())
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())
        if self.rows:
            self.tree.selection_set("0")
            self.tree.focus("0")
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx()}+{parent.winfo_rooty() + parent.winfo_height() + 8}")
        self.tree.focus_set()
        self.grab_set()
        self.wait_window(self)

    def ok(self):
        sel = self.tree.selection()
        if sel:
            self.result = self.rows[int(sel[0])][0]
            self.destroy()

    def browse(self):
        d = filedialog.askdirectory(parent=self, title="Choose a recording folder", initialdir=str(self.base))
        if d:
            self.result = Path(d)
            self.destroy()


# ---------------------------------------------------------------------------
# click-to-set hotkey box
# ---------------------------------------------------------------------------
_ALT_MASK = 0x20000 if sys.platform == "win32" else 0x8  # Tk: Alt is 0x20000 on Windows (0x8 there is NumLock)
_KEYSYM_NAMES = {"space": "space", "Return": "enter", "Tab": "tab", "Delete": "delete", "Insert": "insert",
                 "Home": "home", "End": "end", "Prior": "pageup", "Next": "pagedown", "Pause": "pause",
                 "Print": "printscreen"}
_MODIFIER_KEYSYMS = {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
                     "Super_L", "Super_R", "Caps_Lock", "Num_Lock", "ISO_Level3_Shift"}
_BARE_OK = {"pause", "printscreen"}  # keys that may be a hotkey without Ctrl/Alt/Shift (plus F1-F24)


def hotkey_from_event(keysym, state):
    """Tk key event -> ('spec', None) like ('ctrl+shift+f7', None), or (None, 'reason it can't be used'),
    or (None, '') for a lone modifier press (keep waiting)."""
    if keysym in _MODIFIER_KEYSYMS:
        return None, ""
    mods = [n for n, bit in (("ctrl", 0x4), ("alt", _ALT_MASK), ("shift", 0x1)) if state & bit]
    if len(keysym) >= 2 and keysym[0] in "Ff" and keysym[1:].isdigit() and 1 <= int(keysym[1:]) <= 24:
        key = keysym.lower()
    elif len(keysym) == 1 and keysym.isalnum() and keysym.isascii():
        key = keysym.lower()
    elif keysym in _KEYSYM_NAMES:
        key = _KEYSYM_NAMES[keysym]
    else:
        return None, "That key can't be used as a hotkey"
    bare_ok = key in _BARE_OK or (key[0] == "f" and key[1:].isdigit())
    if not mods and not bare_ok:
        return None, "Add Ctrl, Alt or Shift"
    return "+".join(mods + [key]), None


def pretty_hotkey(spec):
    names = {"pageup": "PageUp", "pagedown": "PageDown", "printscreen": "PrintScreen"}
    out = []
    for p in (spec or "").split("+"):
        out.append(names.get(p) or (p.upper() if len(p) <= 3 and p[:1] == "f" and p[1:].isdigit() else p.title()))
    return "+".join(out)


class HotkeyEntry(ttk.Entry):
    """Read-only box that sets a hotkey by pressing it: click, then press the keys.
    Esc cancels, Backspace resets to the default.  `var` holds the spec ('ctrl+shift+f7').
    `validate(spec)` may return an error message to refuse a choice (e.g. already used)."""

    def __init__(self, parent, var, default, validate=None, **kw):
        self.var, self.default, self.validate = var, default, validate
        self.display = tk.StringVar()
        super().__init__(parent, textvariable=self.display, state="readonly", cursor="hand2", justify="center", **kw)
        self.capturing = False
        self._note = ""
        self.var.trace_add("write", lambda *_: self._refresh())
        self.bind("<Button-1>", self._start)
        self.bind("<Return>", self._start)
        self.bind("<space>", self._start)
        self.bind("<KeyPress>", self._key)
        self.bind("<FocusOut>", lambda e: self._stop())
        self._refresh()

    def _disabled(self):
        return self.instate(["disabled"])

    def _refresh(self):
        if self.capturing:
            self.display.set(self._note or "Press the keys...")
        else:
            self.display.set(self._note or pretty_hotkey(self.var.get()))

    def _start(self, _e=None):
        if self._disabled():
            return "break"
        self.focus_set()
        self.capturing, self._note = True, ""
        self._refresh()
        return "break"

    def _stop(self):
        self.capturing, self._note = False, ""
        self._refresh()

    def _flash(self, text):
        self._note = text
        self._refresh()
        self.after(1500, lambda: (setattr(self, "_note", ""), self._refresh()))

    def _key(self, e):
        if not self.capturing:
            return None
        if e.keysym == "Escape":
            self._stop()
            return "break"
        if e.keysym == "BackSpace":
            self.var.set(self.default)
            self._stop()
            return "break"
        spec, why = hotkey_from_event(e.keysym, e.state)
        if spec is None:
            if why:
                self._flash(why)
            return "break"
        err = self.validate(spec) if self.validate else None
        if err:
            self._flash(err)
            return "break"
        self.var.set(spec)
        self._stop()
        return "break"

