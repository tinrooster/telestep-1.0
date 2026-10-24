#!/usr/bin/env python3
"""
telestep_recorder.py - local, offline replacement for Windows Problem Steps Recorder (PSR).  Version 1.0.

Records clicks (plus double-clicks, drags, scrolling, keyboard shortcuts, error dialogs) with
annotated screenshots, window title, application name/version and the UI element touched
(via UI Automation).  Everything is autosaved to <session folder>/session.json, so you can
review/edit afterwards and export to Markdown, DOCX, HTML, PDF or plain text.

Record:   python telestep_recorder.py --title "Fix Teams audio"
Hotkeys:  F9 pause/resume   F10 stop   Ctrl+Shift+F7 note   Ctrl+Shift+F8 screenshot   Ctrl+Shift+F6 delete last step
Review:   python telestep_recorder.py --review  <session folder>
Export:   python telestep_recorder.py --export  <session folder> --format md,docx,html,pdf,txt
Rescue:   python telestep_recorder.py --export  <old v1 folder with steps.md>     (re-imports it as a v2 session)

Capture area:  --capture screen|all|monitor|window|region   --monitor N   --region L,T,R,B   --exclude-taskbar
Hiding:        --mask L,T,R,B[:style]   --hide-window "Title text"[:style]   --mask-style soft
               styles: solid soft match pixelate pixelate_fine blur blur_heavy dim
               --ocr-redact ip,mac,key,email   (needs Tesseract)
Keyboard:      --keys none|count|text    (none = mouse only: no keyboard hook at all)
Extras:        --after off|replace|pair  --after-ms 700   --scroll   --no-drag --no-dbl --no-shortcuts

Install:  pip install pynput mss pillow uiautomation python-docx reportlab
Note:     Run as administrator to capture clicks inside admin (elevated) windows.
"""
import argparse
import contextlib
import datetime as dt
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import telestep_core as core  # sets DPI awareness on import
from telestep_core import (Mask, OcrUnavailable, apply_masks, capture_box, clean_text, cursor_pos, foreground_info,
                      in_rects, norm_masks, ocr_redact, session_dir_name, taskbar_strips, window_info)
from PIL import Image
from telestep_model import (CONTAINER_KINDS, Session, Step, click_texts, collect_environment, drag_texts, new_id, scroll_texts,
                       shortcut_texts, type_texts)
from telestep_settings import DEFAULT_HOTKEYS

DIALOG_CLASSES = {"#32770"}
_MODKEYS = {"ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt": "alt", "alt_l": "alt", "alt_r": "alt",
            "alt_gr": "altgr", "shift": "shift", "shift_l": "shift", "shift_r": "shift",
            "cmd": "win", "cmd_l": "win", "cmd_r": "win"}
_MOD_ORDER = ("ctrl", "alt", "shift", "win")
_STANDALONE = {"esc", "delete", "print_screen"} | {f"f{i}" for i in range(1, 13)}
_KEY_LABELS = {"esc": "Esc", "delete": "Delete", "print_screen": "Print Screen", "enter": "Enter", "tab": "Tab",
               "backspace": "Backspace", "space": "Space", "left": "Left", "right": "Right", "up": "Up",
               "down": "Down", "home": "Home", "end": "End", "page_up": "Page Up", "page_down": "Page Down",
               "insert": "Insert"}


@dataclass
class CaptureOpts:
    mode: str = "screen"  # screen | all | monitor | window | region
    monitor: int = 1  # 1-based index, used when mode == "monitor"
    region: tuple = None  # (left, top, right, bottom) in screen pixels, used when mode == "region"
    exclude_taskbar: bool = False
    masks: list = field(default_factory=list)  # [Mask] (bare (l,t,r,b) tuples are accepted too)

    def __post_init__(self):
        self.masks = norm_masks(self.masks)


@dataclass
class RecordOpts:
    key_mode: str = "count"  # none (mouse only, no keyboard hook) | count | text
    max_width: int = 1600
    after_mode: str = "off"  # off | replace (show the result instead) | pair (before + after)
    after_delay_ms: int = 700
    dbl: bool = True
    drag: bool = True
    scroll: bool = False
    shortcuts: bool = True
    watch_dialogs: bool = True  # error/message boxes become steps with their text; admin-window warning
    ocr_kinds: list = field(default_factory=list)  # subset of ip, mac, key, email
    ocr_style: str = "solid"
    wording: str = "friendly"
    ocr_labels: bool = True  # label clicks on unnamed controls with nearby text (needs Tesseract; silently skipped if absent)
    hotkeys: dict = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))


class _Holder:
    """Result of the delayed 'after click' grab, filled by a helper thread."""

    def __init__(self):
        self.img = None
        self.done = threading.Event()


def _key_name(key):
    name = getattr(key, "name", None)  # pynput Key enum member
    if name:
        return name.lower()
    vk, ch = getattr(key, "vk", None), getattr(key, "char", None)
    if vk and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
        return chr(vk).lower()
    if ch and ord(ch) >= 32:
        return ch.lower()
    return ""


def _key_label(name):
    if name in _KEY_LABELS:
        return _KEY_LABELS[name]
    if re.fullmatch(r"f\d{1,2}", name):
        return name.upper()
    return name.upper() if len(name) == 1 else name.replace("_", " ").title()


class Recorder:
    def __init__(self, outdir, cap=None, opts=None, title="Recorded steps"):
        self.cap = cap or CaptureOpts()
        self.o = opts or RecordOpts()
        self.session = Session(outdir, title)
        self.session.make_dirs()
        self.ignore_titles = set()  # clicks/keys in windows with these exact titles are skipped
        self.ignore_rects = []  # (l, t, r, b) screen rectangles whose clicks are skipped (the toolbar)
        self.paused = False
        self.stop_evt = threading.Event()
        self.q = queue.Queue()  # listener threads -> worker
        self.events = queue.Queue()  # recorder -> toolbar: ("captured",) ("note",) ("undone", n) ("warn", text) ...
        self.elevated = core.is_admin()
        self._typed, self._typed_count = [], 0
        self._lock = threading.Lock()
        self._tls = threading.local()
        self._last_pw = False
        self._mods = set()
        self._press = None
        self._last_click = None
        self._last_pos = None
        self._dbl_time = core.double_click_time()
        self._scroll = None
        self._slock = threading.Lock()
        self._ml = self._kl = self._hk = None
        self._hk_fallback = []
        self._warned_ocr = False
        self._ocr_ok = None  # None = not tried yet, False = Tesseract missing
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._watcher = threading.Thread(target=self._watch, daemon=True)
        self._hk_specs = []  # (modifier set, key name) of every configured hotkey
        for spec in self.o.hotkeys.values():
            parts = [p.strip().lower() for p in (spec or "").split("+") if p.strip()]
            if parts:
                self._hk_specs.append((frozenset({"ctrl" if p == "control" else p for p in parts[:-1]}), parts[-1]))

    # convenience for the toolbar
    @property
    def steps(self):
        return self.session.steps

    # ------------------------------------------------------------------ capture (listener threads)
    def _sct(self):
        import mss
        sct = getattr(self._tls, "sct", None)
        if sct is None:
            sct = self._tls.sct = (getattr(mss, "MSS", None) or mss.mss)()  # mss.mss is deprecated
        return sct

    def _shoot(self, box):
        """Grab `box` and burn the masks in.  Raw (unmasked) pixels never leave this function."""
        sct = self._sct()
        raw = sct.grab(box)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        masks = list(self.cap.masks)
        if self.cap.exclude_taskbar and self.cap.mode == "all":
            masks += [Mask(rect=r, style="soft", label="Taskbar") for r in taskbar_strips(sct.monitors)]
        apply_masks(img, box, masks)
        return img

    def _grab(self, x, y):
        """(PIL image, box) for the configured capture area, or None if (x, y) is out of scope."""
        box = capture_box(self.cap, self._sct().monitors, x, y)
        if box is None:
            return None
        return self._shoot(box), box

    def _ignored(self, x, y, title=None):
        if title is not None and title in self.ignore_titles:
            return True
        return in_rects(x, y, self.ignore_rects)

    def on_click(self, x, y, button, pressed):
        if self.paused or self.stop_evt.is_set():
            return
        name = button.name
        if not pressed:
            self._on_release(x, y, name)
            return
        if not self._backlog_ok():
            self._press = None
            return
        info = window_info(x, y)
        try:
            info["wrect"] = core.window_rect(x, y)  # measured now: the worker may get to this click seconds later
        except Exception:
            info["wrect"] = None
        if self._ignored(x, y, info["title"]):
            self._press = None
            return
        self._last_pos = (x, y)
        self._flush_scroll(force=True)
        now = time.monotonic()
        lc = self._last_click
        if (self.o.dbl and name == "left" and lc and now - lc[0] <= self._dbl_time
                and abs(x - lc[1]) <= 4 and abs(y - lc[2]) <= 4):
            self._last_click = None
            self._press = (x, y, now, name, True)
            self.q.put(("dbl", dt.datetime.now(), x, y))
            return
        got = self._grab(x, y)
        if got is None:  # click outside the chosen screen/region
            self._press = None
            return
        img, box = got
        self._flush_typing()
        self._last_click = (now, x, y) if name == "left" else None
        self._press = (x, y, now, name, False)
        holder = None
        if self.o.after_mode in ("replace", "pair"):
            holder = _Holder()
            threading.Thread(target=self._grab_after, args=(holder, box), daemon=True).start()
        self.q.put(("click", dt.datetime.now(), x, y, name, img, box, info, holder))
        self.events.put(("captured",))

    def _on_release(self, x, y, name):
        p, self._press = self._press, None
        if not p or not self.o.drag or name != "left" or p[4]:
            return
        if (abs(x - p[0]) >= 12 or abs(y - p[1]) >= 12) and time.monotonic() - p[2] >= 0.15:
            self._last_click = None
            self.q.put(("drag", dt.datetime.now(), p[0], p[1], x, y))

    def _grab_after(self, holder, box):
        try:
            time.sleep(self.o.after_delay_ms / 1000.0)
            holder.img = self._shoot(box)
        except Exception:
            holder.img = None
        finally:
            holder.done.set()

    def on_scroll(self, x, y, dx, dy):
        if not self.o.scroll or self.paused or self.stop_evt.is_set() or self._ignored(x, y) or self.holding:
            return
        with self._slock:
            sc = self._scroll or {"x": x, "y": y, "dy": 0.0}
            sc["dy"] += dy
            sc["t"] = time.monotonic()
            self._scroll = sc

    def _flush_scroll(self, force=False):
        with self._slock:
            sc = self._scroll
            if not sc or (not force and time.monotonic() - sc["t"] < 0.8):
                return
            self._scroll = None
        if abs(sc["dy"]) < 0.5:
            return
        got = self._grab(sc["x"], sc["y"])
        if got is None:
            return
        self._flush_typing()
        self.q.put(("scroll", dt.datetime.now(), sc["x"], sc["y"], sc["dy"], got[0], got[1],
                    window_info(sc["x"], sc["y"])))

    def add_note(self, text, level="note"):
        """Insert a free-text note (level: note | warning | tip) as its own entry."""
        self._flush_typing()
        self.q.put(("note", dt.datetime.now(), text, level))

    def manual_shot(self, pos=None, from_menu=False):
        """Screenshot without a click (hotkey / toolbar button).  Uses the cursor position to pick the area.
        from_menu=True (tray or right-click menu): the cursor is over the menu, so use the last click instead."""
        if self.paused or self.stop_evt.is_set() or not self._backlog_ok():
            return
        pos = pos or (self._last_pos if from_menu else None) or cursor_pos() or self._last_pos
        cap = self.cap
        if pos is None or in_rects(pos[0], pos[1], self.ignore_rects):  # cursor is on the toolbar
            pos = self._last_pos or pos
            if cap.mode == "window":
                cap = CaptureOpts("screen", cap.monitor, cap.region, cap.exclude_taskbar, cap.masks)
        try:
            mons = self._sct().monitors
            if pos is None:
                pos = (mons[1]["left"] + mons[1]["width"] // 2, mons[1]["top"] + mons[1]["height"] // 2)
            box = capture_box(cap, mons, *pos)
            if box is None and cap.mode == "region" and cap.region:
                l, t, r, b = cap.region
                box = capture_box(cap, mons, (l + r) // 2, (t + b) // 2)
            if box is None:
                return
            img = self._shoot(box)
        except Exception:
            return
        self._flush_typing()
        self.q.put(("shot", dt.datetime.now(), img, box, window_info(*pos)))
        self.events.put(("captured",))

    def undo_last(self):
        self.q.put(("undo",))

    # Each queued click holds a full-size screenshot (about 18 MB on three monitors), so a machine that cannot
    # keep up must not pile them up without limit.
    WARN_AT, HOLD_AT, RESUME_AT = 25, 60, 15
    holding = False
    _backlog_warned = False

    def _backlog_ok(self):
        """False while the processing queue is too long to take more screenshots (events tell the toolbar)."""
        n = self.q.qsize()
        if self.holding:
            if n > self.RESUME_AT:
                return False
            self.holding = False
            self.events.put(("backlog", "resumed", n))
        elif n >= self.HOLD_AT:
            self.holding = True
            self.events.put(("backlog", "hold", n))
            return False
        if n >= self.WARN_AT and not self._backlog_warned:
            self._backlog_warned = True
            self.events.put(("backlog", "warn", n))
        elif n < self.RESUME_AT:
            self._backlog_warned = False
        return True

    def toggle_pause(self):
        self.paused = not self.paused
        self.events.put(("paused", self.paused))

    def request_stop(self):
        self.stop_evt.set()

    # ------------------------------------------------------------------ keyboard
    def _fallback_hotkey(self, key):
        if not self._hk_fallback:
            return False
        name = _key_name(key)
        for (mods, kname), fn in self._hk_fallback:
            if kname == name and mods == (self._mods & set(_MOD_ORDER)):
                fn()
                return True
        return False

    def _is_hotkey(self, key):
        name = _key_name(key)
        mods = frozenset(self._mods & set(_MOD_ORDER))
        return any(k == name and m == mods for m, k in self._hk_specs)

    def on_press(self, key):
        mod = _MODKEYS.get(getattr(key, "name", "") or "")
        if mod:
            self._mods.add(mod)
            return
        if self._fallback_hotkey(key) or self._is_hotkey(key):
            return  # our own hotkeys are never recorded as steps
        if self.o.key_mode == "none" or self.paused:
            return
        if foreground_info()["title"] in self.ignore_titles:
            return
        from pynput.keyboard import Key
        name = _key_name(key)
        held = self._mods & {"ctrl", "alt", "win"}
        altgr_text = {"ctrl", "alt"} <= held and getattr(key, "char", None) and ord(key.char) >= 32
        if self.o.shortcuts and name and not altgr_text and (held or name in _STANDALONE):
            self._shortcut(name)
            return
        with self._lock:
            ch = getattr(key, "char", None)
            if ch and ord(ch) < 32:  # Ctrl+letter control code - not text
                return
            if ch:
                self._typed.append(ch)
                self._typed_count += 1
            elif key == Key.space:
                self._typed.append(" ")
                self._typed_count += 1
            elif key == Key.enter:
                self._typed.append("<Enter>")
                self._typed_count += 1
            elif key == Key.tab:
                self._typed.append("<Tab>")
                self._typed_count += 1
            elif key == Key.backspace and self._typed:
                self._typed.pop()
                self._typed_count = max(0, self._typed_count - 1)

    def on_release(self, key):
        mod = _MODKEYS.get(getattr(key, "name", "") or "")
        if mod:
            self._mods.discard(mod)

    def _shortcut(self, name):
        mods = [m for m in _MOD_ORDER if m in self._mods]
        combo = "+".join([{"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}[m] for m in mods]
                         + [_key_label(name)])
        self._flush_typing()
        pos = cursor_pos() or self._last_pos
        img = box = info = None
        if pos is not None and not in_rects(pos[0], pos[1], self.ignore_rects):
            try:
                got = self._grab(*pos)
                if got:
                    img, box = got
                    info = window_info(*pos)
            except Exception:
                pass
        self.q.put(("shortcut", dt.datetime.now(), combo, img, box, info))

    def _flush_typing(self):
        with self._lock:
            if not self._typed_count:
                return
            item = ("type", dt.datetime.now(), "".join(self._typed), self._typed_count)
            self._typed, self._typed_count = [], 0
        self.q.put(item)

    # ------------------------------------------------------------------ background watcher
    def _watch(self):
        """Every ~0.35 s: flush idle scrolling, notice message boxes, warn about admin windows."""
        last, warned = None, set()
        while not self.stop_evt.wait(0.35):
            try:
                self._flush_scroll()
                if self.paused or not self.o.watch_dialogs:
                    continue
                fg = foreground_info()
                key = (fg["hwnd"], fg["title"])
                if not fg["hwnd"] or key == last:
                    continue
                last = key
                if fg["title"] in self.ignore_titles:
                    continue
                if not self.elevated and fg["pid"] and fg["hwnd"] not in warned:
                    if core.app_info(fg["pid"]).get("elevated"):
                        warned.add(fg["hwnd"])
                        msg = (f'Window "{fg["title"] or core.app_info(fg["pid"])["app"]}" runs as administrator, so '
                               "clicks and keys inside it are NOT recorded. Restart Telestep as administrator.")
                        self.q.put(("warn", dt.datetime.now(), msg))
                        self.events.put(("warn", msg))
                        continue
                if fg["cls"] in DIALOG_CLASSES and fg["title"]:
                    time.sleep(0.25)  # let the dialog finish painting
                    rc = core._frame_rect(fg["hwnd"])
                    cx, cy = (rc[0] + rc[2]) // 2, (rc[1] + rc[3]) // 2
                    got = self._grab(cx, cy)
                    if got:
                        self.q.put(("dialog", dt.datetime.now(), fg, got[0], got[1]))
            except Exception:
                continue

    # ------------------------------------------------------------------ processing (worker thread)
    def _describe(self, auto, x, y, pid=None):
        """Return (name, kind, rect, is_password, inherited) for the UI element at the point.

        If the element itself has no name (common for Chrome/Electron/Word "Pane" elements),
        walk up to 4 parents and use the nearest named one; `inherited` is True in that case.
        """
        if auto is None:
            return "", "", None, False, False
        slow = self.__dict__.setdefault("_slow_uia", {})  # pid -> count of lookups that took over 2.5 s
        if pid and slow.get(pid, 0) >= 2:
            return "", "", None, False, False  # this program answers too slowly: describe it by its window title
        t0 = time.monotonic()
        try:
            return self._describe_inner(auto, x, y, pid)
        finally:
            took = time.monotonic() - t0
            if pid and took > 2.5:
                slow[pid] = slow.get(pid, 0) + 1
                if slow[pid] == 2:
                    self.events.put(("warn", "This program is slow to describe its buttons, so later clicks in it "
                                             "are named by window instead (the screenshots are unaffected)."))

    def _describe_inner(self, auto, x, y, pid=None):
        try:
            c = auto.ControlFromPoint(x, y)
            if c is None:
                return "", "", None, False, False
            try:  # the worker can run seconds behind the click: ignore an element from a different program
                if pid and c.ProcessId and c.ProcessId != pid:
                    return "", "", None, False, False
            except Exception:
                pass
            name = (c.Name or "").strip().replace("\n", " ")[:80]
            kind = (c.ControlTypeName or "").replace("Control", "")
            r = c.BoundingRectangle
            rect = (r.left, r.top, r.right, r.bottom)
            try:
                pw = bool(c.GetPropertyValue(auto.PropertyId.IsPasswordProperty))
            except Exception:
                pw = False
            inherited = False
            if not name:
                p = c
                for _ in range(4):
                    try:
                        p = p.GetParentControl()
                    except Exception:
                        p = None
                    if p is None:
                        break
                    pn = (p.Name or "").strip().replace("\n", " ")[:80]
                    if pn:
                        name, inherited = pn, True
                        break
            return name, kind, rect, pw, inherited
        except Exception:
            return "", "", None, False, False

    def _dialog_info(self, auto, hwnd):
        """(texts, button_count, element_count) of a dialog window via UI Automation."""
        texts, buttons, total = [], 0, 0
        if auto is None:
            return texts, buttons, total
        try:
            root = auto.ControlFromHandle(hwnd)

            def walk(ctrl, depth):
                nonlocal buttons, total
                if depth > 5 or total > 60:
                    return
                for ch in ctrl.GetChildren():
                    total += 1
                    t, nm = ch.ControlTypeName, (ch.Name or "").strip()
                    if t == "TextControl" and nm and nm not in texts:
                        texts.append(nm)
                    elif t == "ButtonControl":
                        buttons += 1
                    walk(ch, depth + 1)

            walk(root, 0)
        except Exception:
            pass
        return texts, buttons, total

    def _prepare(self, img):
        """Redact sensitive-looking text (optional) and downscale.  Returns (image, scale)."""
        t0 = time.monotonic()
        try:
            return self._prepare_inner(img)
        finally:
            self._prep_s = time.monotonic() - t0

    def _prepare_inner(self, img):
        if self.o.ocr_kinds:
            try:
                ocr_redact(img, self.o.ocr_kinds, self.o.ocr_style, cache=self.__dict__.setdefault("_ocr_cache", {}))
            except OcrUnavailable:
                if not self._warned_ocr:
                    self._warned_ocr = True
                    self.events.put(("warn", "OCR redaction is on but Tesseract is not installed - screenshots "
                                             "were NOT redacted."))
        scale = 1.0
        if img.width > self.o.max_width:
            scale = self.o.max_width / img.width
            img = img.resize((self.o.max_width, max(1, int(img.height * scale))), Image.LANCZOS)
        return img, scale

    def _save_raw(self, step_id, img, suffix=""):
        rel = f"raw/{step_id}{suffix}.jpg"
        img.save(self.session.dir / rel, "JPEG", quality=90)
        return rel

    def _new(self, kind, when, friendly, tech, info=None, **kw):
        info = info or {}
        with self._stage("app-info"):
            app = core.app_info(info.get("pid", 0)) if info.get("pid") else {}
        return Step(new_id(), kind, when.strftime("%H:%M:%S"), friendly, tech, window=info.get("title", ""),
                    app=app.get("app", ""), app_version=app.get("version", ""), **kw)

    def _win_marker(self, geom, x, y, wr=None):
        """The clicked window's rectangle in picture pixels (used by the 'blur all but the window' option).
        `wr` is the rectangle measured at click time; asking again later (the queue can lag) finds whatever
        is under that point by then."""
        try:
            wr = wr or core.window_rect(x, y)
            if wr:
                return (self._map(geom, wr["left"], wr["top"])
                        + self._map(geom, wr["left"] + wr["width"], wr["top"] + wr["height"]))
        except Exception:
            pass
        return None

    def _map(self, geom, x, y):
        return [round((x - geom["left"]) * geom["scale"], 1), round((y - geom["top"]) * geom["scale"], 1)]

    def _work(self):
        try:
            import uiautomation as auto
            ctx = auto.UIAutomationInitializerInThread()
        except Exception:
            auto, ctx = None, contextlib.nullcontext()
        with ctx:
            while True:
                item = self.q.get()
                if item is None:
                    break
                t0 = time.monotonic()
                self._stages = {}
                try:
                    getattr(self, "_do_" + item[0])(auto, *item[1:])
                    took = time.monotonic() - t0
                    if took > 2.0 and self.slow_log:
                        self.slow_log(f"step '{item[0]}' took {took:.1f}s ("
                                      + ", ".join(f"{k} {v:.1f}s" for k, v in self._stages.items() if v >= 0.05)
                                      + f"; {self.q.qsize()} still queued)")
                except Exception as e:  # one bad step must never lose the rest of the session
                    self.events.put(("warn", f"Skipped a step ({type(e).__name__}: {e})"))

    def _do_type(self, auto, when, text, count):
        f, t = type_texts(self.o.key_mode, text, count, self._last_pw)
        self.session.add(self._new("type", when, f, t))

    def _do_note(self, auto, when, text, level):
        text = clean_text(text)
        st = self._new("note", when, text, text)
        st.level = level
        self.session.add(st)

    def _do_warn(self, auto, when, text):
        st = self._new("note", when, text, text)
        st.level = "warning"
        st.auto = True
        self.session.add(st)

    def _do_undo(self, auto):
        if self.session.steps:
            st = self.session.steps[-1]
            self.session.delete(st)
            self.session.save()
            self.events.put(("undone", st.caption(self.o.wording)[:40]))

    @contextlib.contextmanager
    def _stage(self, name):
        """Add the time spent in the block to this step's breakdown (shown in the debug log for slow steps)."""
        t0 = time.monotonic()
        try:
            yield
        finally:
            d = self.__dict__.setdefault("_stages", {})
            d[name] = d.get(name, 0.0) + time.monotonic() - t0

    def _do_click(self, auto, when, x, y, btn, img, box, info, holder):
        with self._stage("lookup"):
            name, ckind, rect, pw, inherited = self._describe(auto, x, y, info.get("pid"))
        self._last_pw = pw
        el = {"name": name, "kind": ckind, "inherited": inherited, "button": btn, "x": x, "y": y}
        full = img  # full-size picture: label OCR needs it, the downsized one is unreadable on multi-monitor
        with self._stage("redact"):
            img, scale = self._prepare(img)  # redaction and masks happen first, so OCR below can't read hidden text
        geom = {"left": box["left"], "top": box["top"], "scale": scale}
        marker = {"shape": "click", "pt": self._map(geom, x, y), "rect": None, "win": self._win_marker(geom, x, y, info.get("wrect"))}
        if self.o.ocr_labels and not pw and (not name or ckind in CONTAINER_KINDS):
            with self._stage("label-ocr"):
                near = self._label_near(full, (x - box["left"], y - box["top"]))
            if near:
                el["near"] = near
        friendly, tech = click_texts("click", el)
        if rect and rect[2] > rect[0] and rect[3] > rect[1]:
            marker["rect"] = self._map(geom, rect[0], rect[1]) + self._map(geom, rect[2], rect[3])
        st = self._new("click", when, friendly, tech, info, marker=marker, geom=geom, el=el)
        if info.get("cls") in DIALOG_CLASSES:
            st.dialog_text = clean_text("\n".join(self._dialog_info(auto, info["hwnd"])[0]))
        with self._stage("save"):
            st.raw = self._save_raw(st.id, img)
        if holder is not None:
            with self._stage("after-wait"):
                holder.done.wait(self.o.after_delay_ms / 1000.0 + 3)
            if holder.img is not None:
                with self._stage("redact"):
                    after, _ = self._prepare(holder.img)
                with self._stage("save"):
                    if self.o.after_mode == "replace":
                        st.raw = self._save_raw(st.id, after)
                    else:
                        st.raw_after = self._save_raw(st.id, after, "_after")
        with self._stage("session"):
            self.session.add(st)

    def _label_near(self, img, pt):
        if self._ocr_ok is False:
            return ""
        try:
            text = core.ocr_label_near(img, pt[0], pt[1], half_w=300, half_h=90, max_dist=130)
            self._ocr_ok = True
            return text
        except core.OcrUnavailable:
            self._ocr_ok = False
        except Exception:
            pass
        return ""

    def _last_click_step(self, x, y, tol):
        st = self.session.steps[-1] if self.session.steps else None
        if st and st.kind == "click" and st.el and st.el.get("button") == "left" \
                and abs(st.el["x"] - x) <= tol and abs(st.el["y"] - y) <= tol:
            return st
        return None

    def _do_dbl(self, auto, when, x, y):
        st = self._last_click_step(x, y, 6)
        if st:
            st.kind = "dblclick"
            st.marker["shape"] = "dbl"
            st.friendly, st.tech = click_texts("dblclick", st.el)
            self.session.save()

    def _do_drag(self, auto, when, x0, y0, x1, y1):
        st = self._last_click_step(x0, y0, 6)
        if not st:
            return
        name, ckind, _r, _pw, inherited = self._describe(auto, x1, y1)
        dst = {"name": name, "kind": ckind, "inherited": inherited, "x": x1, "y": y1}
        st.kind = "drag"
        st.el["to"] = dst
        st.marker["shape"] = "drag"
        st.marker["to"] = self._map(st.geom, x1, y1)
        st.marker["rect"] = None
        st.friendly, st.tech = drag_texts(st.el, dst)
        self.session.save()

    def _do_scroll(self, auto, when, x, y, dy, img, box, info):
        name = self._describe(auto, x, y, info.get("pid"))[0]
        direction = "up" if dy > 0 else "down"
        friendly, tech = scroll_texts(direction, name)
        img, scale = self._prepare(img)
        geom = {"left": box["left"], "top": box["top"], "scale": scale}
        st = self._new("scroll", when, friendly, tech, info, geom=geom,
                       marker={"shape": "scroll", "pt": self._map(geom, x, y), "dir": direction,
                               "win": self._win_marker(geom, x, y, info.get("wrect"))})
        st.raw = self._save_raw(st.id, img)
        self.session.add(st)

    def _do_shortcut(self, auto, when, combo, img, box, info):
        friendly, tech = shortcut_texts(combo)
        st = self._new("shortcut", when, friendly, tech, info, marker={"shape": "none"})
        if img is not None:
            img, scale = self._prepare(img)
            st.geom = {"left": box["left"], "top": box["top"], "scale": scale}
            st.raw = self._save_raw(st.id, img)
        self.session.add(st)

    def _do_shot(self, auto, when, img, box, info):
        img, scale = self._prepare(img)
        st = self._new("shot", when, "Screenshot", "Manual screenshot", info, marker={"shape": "none"},
                       geom={"left": box["left"], "top": box["top"], "scale": scale})
        st.raw = self._save_raw(st.id, img)
        self.session.add(st)

    def _do_dialog(self, auto, when, fg, img, box):
        texts, buttons, total = self._dialog_info(auto, fg["hwnd"])
        looks_like_msgbox = bool(texts) and buttons <= 4 and total <= 16
        errorish = re.search(r"error|warning|fail|cannot|can't|unable|not responding|denied|invalid", fg["title"], re.I)
        if auto is not None and not looks_like_msgbox:
            return  # ordinary dialog (Open/Save/Settings...): the click that opened it is already a step
        if auto is None and not errorish:
            return
        img, scale = self._prepare(img)
        text = clean_text("\n".join(texts))
        st = self._new("dialog", when, f'A dialog appeared: "{fg["title"]}"', f'Dialog window "{fg["title"]}"',
                       fg, marker={"shape": "none"}, dialog_text=text,
                       geom={"left": box["left"], "top": box["top"], "scale": scale})
        st.raw = self._save_raw(st.id, img)
        self.session.add(st)

    # ------------------------------------------------------------------ lifecycle
    def _register_hotkeys(self):
        actions = {"pause": self.toggle_pause, "stop": self.request_stop,
                   "note": lambda: self.events.put(("note",)), "shot": self.manual_shot, "undo": self.undo_last}
        bindings = {self.o.hotkeys[a]: fn for a, fn in actions.items() if self.o.hotkeys.get(a)}
        self._hk = core.HotkeyListener(bindings)
        self._hk.start()
        self.hotkeys_failed = list(self._hk.failed)
        for spec in self._hk.failed:  # not Windows, or the combination is taken: use the keyboard hook
            parts = [p.strip().lower() for p in spec.split("+")]
            mods = {"control": "ctrl"}
            self._hk_fallback.append(((frozenset(mods.get(p, p) for p in parts[:-1]), parts[-1]), bindings[spec]))

    def start(self):
        """Begin recording without blocking (used by the toolbar)."""
        from pynput import keyboard, mouse
        try:
            import mss
            with (getattr(mss, "MSS", None) or mss.mss)() as s:
                mons = [dict(m) for m in s.monitors]
        except Exception:
            mons = None
        self.session.environment = collect_environment(mons)
        self.session.settings = {"wording": self.o.wording}
        self.session.save()
        self._register_hotkeys()
        self._worker.start()
        self._watcher.start()
        self._ml = mouse.Listener(on_click=self.on_click, on_scroll=self.on_scroll)
        self._ml.start()
        if self.o.key_mode != "none" or self._hk_fallback:
            self._kl = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
            self._kl.start()

    slow_log = None  # optional callable(str); the app points it at its debug log

    def pending(self):
        return self.q.qsize()

    def stop(self):
        """Stop listeners, drain the queue, save, return the Session."""
        self.stop_evt.set()
        for h in (self._ml, self._kl):
            if h:
                h.stop()
        if self._hk:
            self._hk.stop()
        self._flush_scroll(force=True)
        self._flush_typing()
        self.q.put(None)
        self._worker.join()
        if self._watcher.is_alive():
            self._watcher.join(2)
        self.session.save()
        return self.session

    def run(self):
        self.start()
        hk = self.o.hotkeys
        print(f"Recording. {hk['pause']} = pause/resume, {hk['stop']} = stop and save, {hk['shot']} = screenshot, "
              f"{hk['undo']} = delete last step. Ctrl+C also stops.")
        try:
            while not self.stop_evt.is_set():
                self.stop_evt.wait(0.2)
                while not self.events.empty():
                    ev = self.events.get_nowait()
                    if ev[0] == "warn":
                        print("WARNING:", ev[1])
        except KeyboardInterrupt:
            pass
        return self.stop()


# ---------------------------------------------------------------------------------------- CLI
def _parse_rect(text):
    l, t, r, b = (int(v) for v in text.split(","))
    return (min(l, r), min(t, b), max(l, r), max(t, b))


def _split_style(text, default):
    if ":" in text:
        head, _, tail = text.rpartition(":")
        if tail.strip().lower() in core.MASK_STYLES or tail.strip().lower() in core.LEGACY_STYLES:
            return head, core.canon_style(tail.strip().lower())
    return text, default


def main(argv=None):
    ap = argparse.ArgumentParser(description="Local step recorder (PSR replacement)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--title", default=None, help="report title; also appended to the folder name")
    ap.add_argument("--out", default=None, help="session folder (default: recordings/<timestamp>_<title>)")
    ap.add_argument("--format", default="md,docx", help="comma list of md,docx,html,pdf,txt (or 'both' = md,docx)")
    ap.add_argument("--max-width", type=int, default=1600, help="max screenshot width in px")
    ap.add_argument("--wording", choices=["friendly", "technical"], default="friendly")
    ap.add_argument("--capture", choices=["screen", "all", "monitor", "window", "region"], default="screen")
    ap.add_argument("--monitor", type=int, default=1)
    ap.add_argument("--region", help="L,T,R,B in screen pixels for --capture region")
    ap.add_argument("--exclude-taskbar", action="store_true")
    ap.add_argument("--mask", action="append", default=[], metavar="L,T,R,B[:style]")
    ap.add_argument("--hide-window", action="append", default=[], metavar="TITLE[:style]",
                    help="mask any window whose title contains TITLE (follows the window)")
    ap.add_argument("--mask-style", default="solid", choices=list(core.MASK_STYLES) + list(core.LEGACY_STYLES))
    ap.add_argument("--ocr-redact", default="", help="comma list of ip,mac,key,email")
    ap.add_argument("--keys", choices=["none", "count", "text"], default="count")
    ap.add_argument("--log-keys", action="store_true", help="same as --keys text")
    ap.add_argument("--mouse-only", action="store_true", help="same as --keys none")
    ap.add_argument("--after", choices=["off", "replace", "pair"], default="off")
    ap.add_argument("--after-ms", type=int, default=700)
    ap.add_argument("--scroll", action="store_true", help="record scrolling")
    ap.add_argument("--no-drag", action="store_true")
    ap.add_argument("--no-dbl", action="store_true")
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--no-dialogs", action="store_true", help="don't watch for message boxes / admin windows")
    ap.add_argument("--export", metavar="DIR", help="export an existing session (or old v1 folder) and exit")
    ap.add_argument("--review", metavar="DIR", help="open the review editor for a session and exit")
    a = ap.parse_args(argv)

    fmts = [f for f in ("md,docx" if a.format == "both" else a.format).replace(" ", "").split(",") if f]

    if a.review:
        import telestep_review
        telestep_review.review_main(a.review)
        return
    if a.export:
        import telestep_report
        sess = Session.load(a.export)
        sess.save()
        for fmt, res in telestep_report.export(sess, telestep_report.Template.from_settings(sess.settings), fmts).items():
            print(f"{fmt}: {res}")
        return

    try:
        masks = []
        for m in a.mask:
            r, st = _split_style(m, a.mask_style)
            masks.append(Mask(rect=_parse_rect(r), style=st))
        for w in a.hide_window:
            t, st = _split_style(w, a.mask_style)
            masks.append(Mask(title=t, style=st))
        cap = CaptureOpts(a.capture, a.monitor, _parse_rect(a.region) if a.region else None, a.exclude_taskbar, masks)
    except ValueError:
        ap.error("--region and --mask need four comma-separated integers: L,T,R,B")
    if cap.mode == "region" and not cap.region:
        ap.error("--capture region requires --region L,T,R,B")

    kinds = [k for k in a.ocr_redact.replace(" ", "").split(",") if k in core.OCR_PATTERNS]
    opts = RecordOpts(
        key_mode="text" if a.log_keys else "none" if a.mouse_only else a.keys, max_width=a.max_width,
        after_mode=a.after, after_delay_ms=a.after_ms, dbl=not a.no_dbl, drag=not a.no_drag, scroll=a.scroll,
        shortcuts=not a.no_shortcuts, watch_dialogs=not a.no_dialogs, ocr_kinds=kinds, ocr_style=a.mask_style,
        wording=a.wording)
    title = a.title or "Recorded steps"
    out = Path(a.out) if a.out else Path("recordings") / session_dir_name(a.title)
    rec = Recorder(out, cap, opts, title)
    sess = rec.run()
    if not sess.steps:
        print("No steps recorded.")
        return
    import telestep_report
    tpl = telestep_report.Template(wording=a.wording)
    for fmt, res in telestep_report.export(sess, tpl, fmts).items():
        print(f"{fmt}: {res}")


if __name__ == "__main__":
    main()
