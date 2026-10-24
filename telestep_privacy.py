"""
telestep_privacy.py - the "check for private information before exporting" scan and its dialog.

Two scans:
  * text   - captions, comments, window titles, dialog text and control names are searched for e-mail addresses, IP
             and MAC addresses, long keys/tokens, card-like and ID numbers, and "password: ..." style text. Instant.
  * images - the saved screenshots are read with OCR (needs Tesseract) and the same patterns are looked for in the
             pictures. Slow, so it only runs when asked.
Findings can be fixed (text replaced by [hidden], picture areas hidden) or ignored; ignored ones are remembered in the
recording so the same item is not offered again.
"""
import re
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from PIL import Image

import telestep_core as core

HIDDEN = "[hidden]"
KIND_LABEL = dict(core.OCR_LABELS, secret="Password / secret in text")

_TEXT = {
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "ip": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b(?::\d{1,5})?"),
    "mac": re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    "key": re.compile(r"(?<![\w/\\.])(?:[A-Za-z0-9+/=_-]{28,}|[0-9A-Fa-f]{24,})(?![\w/\\.])"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "secret": re.compile(r"(?i)\b(?:password|passwd|pwd|passcode|secret|api[ _-]?key|token)\s*(?:is|[:=])\s*(\S+)"),
}
_CARD = re.compile(r"(?<![\d.])(?:\d[ -]?){13,19}(?![\d])")
_IP_OK = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)")


def luhn(digits):
    total, alt = 0, False
    for ch in reversed(digits):
        n = int(ch)
        if alt:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
        alt = not alt
    return total % 10 == 0


@dataclass
class Finding:
    step_id: str
    where: str  # caption | comment | window | dialog | control | image | image_after
    kind: str
    text: str  # the matched text
    rect: tuple = None  # image findings: (l, t, r, b) in the saved picture's pixels
    fixed: bool = False

    @property
    def key(self):
        return f"{self.step_id}|{self.where}|{self.kind}|{self.text}"


def find_in_text(text):
    """[(kind, matched text)] for everything private-looking in a string."""
    out, seen = [], set()
    if not text:
        return out

    def add(kind, m):
        if m and m not in seen:
            seen.add(m)
            out.append((kind, m))

    for kind in ("email", "mac", "ssn", "key"):
        for mt in _TEXT[kind].finditer(text):
            add(kind, mt.group(0))
    for mt in _TEXT["ip"].finditer(text):
        if _IP_OK.match(mt.group(0)) and not re.match(r"^\d\.\d\.\d\.\d$", mt.group(0)):
            add("ip", mt.group(0))
    for mt in _CARD.finditer(text):
        digits = re.sub(r"\D", "", mt.group(0))
        if 13 <= len(digits) <= 19 and luhn(digits):
            add("card", mt.group(0).strip())
    for mt in _TEXT["secret"].finditer(text):
        add("secret", mt.group(1).strip(".,;"))
    return out


def _fields(step):
    """(where, getter-text) pairs searched for one step."""
    yield "caption", step.custom or ""
    yield "caption", step.friendly or ""
    yield "caption", step.tech or ""
    yield "comment", getattr(step, "comment", "") or ""
    yield "window", step.window or ""
    yield "dialog", step.dialog_text or ""
    yield "control", (step.el or {}).get("name", "") if isinstance(step.el, dict) else ""


def scan_text(session, ignored=()):
    """Findings in the words of every step that will be exported (left-out steps are not checked)."""
    found, seen = [], set()
    for st in session.steps:
        if st.skip:
            continue
        for where, txt in _fields(st):
            for kind, m in find_in_text(txt):
                f = Finding(st.id, where, kind, m)
                if f.key in ignored or f.key in seen:
                    continue
                seen.add(f.key)
                found.append(f)
    return found


def scan_images(session, kinds=None, ignored=(), progress=None, cancel=None):
    """OCR every picture of every exported step and report private-looking words.  Needs Tesseract."""
    kinds = list(kinds or core.COMMON_SECRETS)
    found = []
    steps = [s for s in session.steps if not s.skip and (s.raw or s.raw_after)]
    for i, st in enumerate(steps):
        if cancel and cancel():
            break
        if progress:
            progress(i, len(steps))
        for where, rel in (("image", st.raw), ("image_after", st.raw_after)):
            p = session.dir / rel if rel else None
            if not p or not p.exists():
                continue
            with Image.open(p) as im0:
                im = im0.convert("RGB")
            words = core.ocr_words_tiled(im)
            for (txt, l, t, r, b) in words:
                if core.ocr_match_rects([(txt, l, t, r, b)], kinds):
                    f = Finding(st.id, where, "ocr", txt.strip(".,;:()[]{}<>\"'"), (l, t, r, b))
                    for k in kinds:  # which pattern matched, for the list
                        if core.ocr_match_rects([(txt, l, t, r, b)], [k]):
                            f.kind = k
                            break
                    if f.key not in ignored:
                        found.append(f)
    if progress:
        progress(len(steps), len(steps))
    return found


def fix_text(session, f):
    """Replace the matched text with [hidden] in the field(s) it came from."""
    st = session.find(f.step_id)
    if not st or f.rect:
        return False
    changed = False
    for attr in ("custom", "friendly", "tech", "comment", "window", "dialog_text"):
        v = getattr(st, attr, "") or ""
        if f.text in v:
            setattr(st, attr, v.replace(f.text, HIDDEN))
            changed = True
    if isinstance(st.el, dict) and f.text in (st.el.get("name") or ""):
        st.el["name"] = st.el["name"].replace(f.text, HIDDEN)
        changed = True
    f.fixed = changed
    return changed


def fix_image(session, f, style="solid"):
    """Hide the matched area on the saved screenshot (permanent, like the review window's Hide tool)."""
    st = session.find(f.step_id)
    rel = (st.raw_after if f.where == "image_after" else st.raw) if st else ""
    p = session.dir / rel if rel else None
    if not p or not p.exists() or not f.rect:
        return False
    with Image.open(p) as im0:
        im = im0.convert("RGB")
    l, t, r, b = f.rect
    core.apply_mask(im, (l - 3, t - 2, r + 3, b + 2), style, "")
    im.save(p, "JPEG", quality=92)
    f.fixed = True
    return True


# ---------------------------------------------------------------------------
class PrivacyDialog(tk.Toplevel):
    """Lists what was found.  `result` is 'export' or 'cancel'.  `changed` tells the caller pictures/text were altered."""

    def __init__(self, parent, session, findings, style="solid", ocr_ok=False, step_no=None):
        super().__init__(parent)
        self.s, self.findings, self.style = session, list(findings), style
        self.result, self.changed = "cancel", False
        self.ignored = set(session.settings.get("privacy_ignored", []))
        self._step_no = step_no or session.numbering()
        self.title("Telestep - check for private information")
        self.transient(parent)
        self.minsize(640, 360)
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)
        self.var_head = tk.StringVar()
        ttk.Label(frm, textvariable=self.var_head, font=("Segoe UI", 10, "bold"), wraplength=620,
                  justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
        self.tree = ttk.Treeview(frm, columns=("step", "where", "kind", "found"), show="headings", height=9,
                                 selectmode="extended")
        for col, text, w in (("step", "Step", 50), ("where", "Where", 110), ("kind", "Looks like", 170),
                             ("found", "Found", 260)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor="w", stretch=(col == "found"))
        sb = ttk.Scrollbar(frm, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        sb.grid(row=1, column=1, sticky="ns", pady=(8, 0))
        self.var_note = tk.StringVar()
        ttk.Label(frm, textvariable=self.var_note, foreground="gray", wraplength=620, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        bar = ttk.Frame(frm)
        bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.btn_hide = ttk.Button(bar, text="Hide selected", command=lambda: self.fix(selected=True))
        self.btn_hide.pack(side="left")
        ttk.Button(bar, text="Hide all", command=lambda: self.fix(selected=False)).pack(side="left", padx=(6, 0))
        self.btn_ign = ttk.Button(bar, text="Ignore selected", command=self.ignore)
        self.btn_ign.pack(side="left", padx=(6, 0))
        self.btn_ocr = ttk.Button(bar, text="Also scan the screenshots (slow)", command=self.scan_pictures,
                                  state="normal" if ocr_ok else "disabled")
        self.btn_ocr.pack(side="left", padx=(16, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        self.btn_go = ttk.Button(bar, text="Export anyway", command=self.go)
        self.btn_go.pack(side="right", padx=(0, 6))
        self.bind("<Escape>", lambda e: self.destroy())
        self.refresh()
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + 60
            y = parent.winfo_rooty() + 60
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        self.grab_set()
        self.wait_window(self)

    # ---- list ----
    def _open(self):
        return [f for f in self.findings if not f.fixed and f.key not in self.ignored]

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        where = {"caption": "Caption", "comment": "Comment", "window": "Window title", "dialog": "Dialog text",
                 "control": "Control name", "image": "Screenshot", "image_after": "Screenshot (after)"}
        for i, f in enumerate(self._open()):
            self.tree.insert("", "end", iid=str(self.findings.index(f)),
                             values=(self._step_no.get(f.step_id, "-"), where.get(f.where, f.where),
                                     KIND_LABEL.get(f.kind, f.kind), f.text))
        n = len(self._open())
        self.var_head.set("Nothing private-looking is left." if not n else
                          f"{n} item{'s' if n != 1 else ''} in this recording look{'s' if n == 1 else ''} private. "
                          "Hide them, ignore the ones that are fine, or export as it is.")
        self.var_note.set("Text items are replaced by [hidden]; picture items are covered on the saved screenshot "
                          "(this changes the screenshot permanently). Matches are guesses - check them.")
        self.btn_go.configure(text="Export" if not n else "Export anyway")
        self.btn_hide.configure(state="normal" if n else "disabled")
        self.btn_ign.configure(state="normal" if n else "disabled")

    def _targets(self, selected):
        if selected:
            return [self.findings[int(i)] for i in self.tree.selection()]
        return self._open()

    def fix(self, selected=True):
        todo = self._targets(selected)
        if not todo:
            messagebox.showinfo("Telestep", "Select the items to hide first.", parent=self)
            return
        n_img = sum(1 for f in todo if f.rect)
        if n_img and not messagebox.askyesno(
                "Telestep", f"Cover {n_img} area(s) on the saved screenshots? This can't be undone.", parent=self):
            return
        for f in todo:
            (fix_image(self.s, f, self.style) if f.rect else fix_text(self.s, f))
        # a text fix also clears identical findings on other steps' fields only when they were fixed themselves
        self.changed = True
        self.s.save()
        self.refresh()

    def ignore(self):
        for f in self._targets(True):
            self.ignored.add(f.key)
        self.s.settings["privacy_ignored"] = sorted(self.ignored)
        self.s.save()
        self.refresh()

    def scan_pictures(self):
        self.btn_ocr.configure(state="disabled", text="Scanning screenshots...")
        self.update_idletasks()
        box = {"found": None, "err": None, "i": 0, "n": 1, "cancel": False}

        def work():
            try:
                box["found"] = scan_images(self.s, ignored=self.ignored,
                                           progress=lambda i, n: box.update(i=i, n=n), cancel=lambda: box["cancel"])
            except Exception as e:  # noqa: BLE001 - shown to the user
                box["err"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def tick():
            if t.is_alive():
                if self.winfo_exists():
                    self.btn_ocr.configure(text=f"Scanning screenshots... {box['i']}/{box['n']}")
                    self.after(300, tick)
                return
            if not self.winfo_exists():
                return
            if box["err"]:
                messagebox.showerror("Telestep", f"The screenshot scan failed:\n{box['err']}", parent=self)
                self.btn_ocr.configure(state="normal", text="Also scan the screenshots (slow)")
                return
            have = {f.key for f in self.findings}
            self.findings += [f for f in box["found"] if f.key not in have]
            self.btn_ocr.configure(text=f"Screenshots scanned ({len(box['found'])} found)")
            self.refresh()

        self.after(300, tick)
        self.protocol("WM_DELETE_WINDOW", lambda: (box.update(cancel=True), self.destroy()))

    def go(self):
        # anything still listed and not ignored is remembered as "seen" so the same list isn't shown on every export
        for f in self._open():
            self.ignored.add(f.key)
        self.s.settings["privacy_ignored"] = sorted(self.ignored)
        self.result = "export"
        self.destroy()


def check_before_export(parent, session, style="solid", step_no=None):
    """Run the text scan; if it finds anything, show the dialog.  Returns (go_on, changed)."""
    ignored = set(session.settings.get("privacy_ignored", []))
    found = scan_text(session, ignored)
    if not found:
        return True, False
    dlg = PrivacyDialog(parent, session, found, style=style, ocr_ok=core.ocr_status() is not False, step_no=step_no)
    return dlg.result == "export", dlg.changed
