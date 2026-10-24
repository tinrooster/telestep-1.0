"""
telestep_model.py - the session data model (session.json), wording, environment info, legacy import.

A session folder looks like:
    session.json        every step + settings (autosaved while recording)
    raw/<id>.jpg        screenshot WITHOUT markers (masks/redactions already burned in - never the unmasked screen)
    images/step_*.jpg   annotated copies, regenerated whenever a report is exported
    environment.txt     machine/OS/app details for troubleshooting
    steps.md|docx|html|pdf|txt
"""
import datetime as dt
import json
import os
import platform
import re
import socket
import threading
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from telestep_core import VERSION, clean_text, is_admin

FORMAT_VERSION = 2
ACTION_KINDS = ("click", "dblclick", "drag", "scroll", "shortcut", "type", "shot", "dialog")
TEXT_KINDS = ("note", "section")


@dataclass
class Step:
    id: str
    kind: str = "click"  # ACTION_KINDS + TEXT_KINDS
    when: str = ""
    friendly: str = ""  # caption, plain-English wording ("Click the "Save" button")
    tech: str = ""  # caption, technical wording ("Left click on "Save" (Button)")
    custom: str = ""  # caption typed by the user in the review editor (wins over both)
    level: str = ""  # notes only: note | warning | tip
    window: str = ""
    app: str = ""
    app_version: str = ""
    dialog_text: str = ""
    raw: str = ""  # path relative to the session folder
    raw_after: str = ""
    image: str = ""  # annotated copy (set at export; imported old sessions only have this)
    image_after: str = ""
    marker: dict = None
    geom: dict = None  # {"left","top","scale"}: screen -> saved-image mapping
    el: dict = None  # {"name","kind","inherited","button","x","y"} clicked UI element
    skip: bool = False  # excluded from reports but kept in the session
    auto: bool = False  # made by Telestep itself (e.g. admin-window warning), not by the person
    comment: str = ""  # extra line shown under the caption (typed at record time or in the review editor)
    audio: str = ""  # voice note (WAV) relative to the session folder, e.g. audio/<id>.wav
    apos: float = -1.0  # where in the narration recording this step happened (seconds); -1 = not narrated
    marks: list = None  # hand-made annotations drawn on the picture: [{"t": box|arrow|text|num, "p": [...], ...}]

    def caption(self, wording="friendly"):
        if self.custom:
            return self.custom
        return self.tech if wording == "technical" and self.tech else (self.friendly or self.tech)

    @property
    def numbered(self):
        return self.kind not in TEXT_KINDS

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def new_id():
    return uuid.uuid4().hex[:8]


class Session:
    def __init__(self, folder, title="Recorded steps"):
        self.dir = Path(folder)
        self.title = title
        self.created = dt.datetime.now().isoformat(timespec="seconds")
        self.host = socket.gethostname()
        self.environment = {}
        self.steps = []
        self.settings = {}  # report settings saved with the session (wording, template ...)
        self.lock = threading.RLock()

    # ---- folders ----
    @property
    def raw_dir(self):
        return self.dir / "raw"

    @property
    def img_dir(self):
        return self.dir / "images"

    def make_dirs(self):
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.img_dir.mkdir(parents=True, exist_ok=True)

    # ---- steps ----
    def add(self, step, autosave=True):
        with self.lock:
            self.steps.append(step)
        if autosave:
            self.save()
        return step

    def find(self, step_id):
        return next((s for s in self.steps if s.id == step_id), None)

    def count(self):
        """Number of real steps (notes and section headings don't count)."""
        return sum(1 for s in self.steps if s.numbered and not s.skip)

    def numbering(self):
        """{step id: display number} for the exported (numbered, not skipped) steps."""
        n, out = 0, {}
        for s in self.steps:
            if s.numbered and not s.skip:
                n += 1
                out[s.id] = n
        return out

    def delete(self, step, remove_files=True):
        with self.lock:
            if step in self.steps:
                self.steps.remove(step)
        if remove_files:
            for rel in (step.raw, step.raw_after, step.image, step.image_after, step.audio):
                if rel:
                    try:
                        (self.dir / rel).unlink()
                    except OSError:
                        pass

    def move(self, step, delta):
        with self.lock:
            i = self.steps.index(step)
            j = i + delta
            if 0 <= j < len(self.steps):
                self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
                return True
        return False

    def move_block(self, steps, delta):
        """Move several steps together by `delta` places (keeping their order).  `delta` of +-len(steps list) or more
        goes to the very top / bottom.  Returns True if anything moved."""
        with self.lock:
            block = [s for s in self.steps if s in steps]
            if not block:
                return False
            rest = [s for s in self.steps if s not in steps]
            first = self.steps.index(block[0])
            before = len([s for s in self.steps[:first] if s not in steps])  # items of `rest` ahead of the block
            at = max(0, min(len(rest), before + (delta if abs(delta) < 10_000 else (-before if delta < 0 else len(rest)))))
            new = rest[:at] + block + rest[at:]
            if new == self.steps:
                return False
            self.steps[:] = new
            return True

    def duplicate(self, step):
        """A copy right after `step`, with its own copies of the screenshot files.  Returns the copy."""
        import copy
        import shutil
        with self.lock:
            twin = copy.deepcopy(step)
            twin.id = new_id()
            twin.image = twin.image_after = ""
            for attr in ("raw", "raw_after"):
                rel = getattr(step, attr)
                if rel and (self.dir / rel).exists():
                    new_rel = str(Path(rel).with_name(f"{twin.id}{'_after' if attr == 'raw_after' else ''}"
                                                       f"{Path(rel).suffix}")).replace("\\", "/")
                    try:
                        shutil.copyfile(self.dir / rel, self.dir / new_rel)
                        setattr(twin, attr, new_rel)
                    except OSError:
                        setattr(twin, attr, rel)  # fall back to sharing the file (delete() then keeps it, see below)
            if step.audio and (self.dir / step.audio).exists():
                new_rel = f"audio/{twin.id}.wav"
                try:
                    shutil.copyfile(self.dir / step.audio, self.dir / new_rel)
                    twin.audio = new_rel
                except OSError:
                    twin.audio = ""
            else:
                twin.audio = ""
            self.steps.insert(self.steps.index(step) + 1, twin)
        return twin

    def merge(self, steps):
        """Fold several steps into the first one (in list order): captions are joined ("Click A, then click B"), the
        first picture is kept and the LAST step's picture becomes its 'after' picture.  Returns the merged step."""
        with self.lock:
            group = [s for s in self.steps if s in steps and s.numbered]
            if len(group) < 2:
                return None
            head, rest = group[0], group[1:]

            def low(t):  # "Click ..." -> "click ..." but leave "OK", "URL" and names alone
                return t[:1].lower() + t[1:] if len(t) > 1 and t[0].isupper() and t[1].islower() else t

            for attr in ("friendly", "tech"):
                parts = [(s.custom or getattr(s, attr) or s.friendly or s.tech or "").strip().rstrip(".") for s in group]
                setattr(head, attr, ", then ".join([parts[0]] + [low(p) for p in parts[1:] if p]))
            head.custom = ""
            last = rest[-1]
            if last.raw and not head.raw_after:
                head.raw_after = last.raw
                keep_file = last.raw
            else:
                keep_file = ""
            head.comment = " ".join(x for x in [head.comment] + [s.comment for s in rest] if x).strip()
            clips = [s.audio for s in group if s.audio and (self.dir / s.audio).exists()]
            if len(clips) > 1:
                import telestep_audio
                dest = f"audio/{head.id}.wav"
                tmp = self.dir / "audio" / f"{head.id}_joined.tmp"
                if telestep_audio.join_clips([self.dir / c for c in clips], tmp):
                    for c in clips:
                        try:
                            (self.dir / c).unlink()
                        except OSError:
                            pass
                    tmp.replace(self.dir / dest)
                    head.audio = dest
            elif clips:
                head.audio = clips[0]
            head.dialog_text = "\n".join(x for x in [head.dialog_text] + [s.dialog_text for s in rest] if x)
            for s in rest:
                if s in self.steps:
                    self.steps.remove(s)
                for rel in (s.raw, s.raw_after, s.image, s.image_after):
                    if rel and rel != keep_file and rel not in (head.raw, head.raw_after):
                        try:
                            (self.dir / rel).unlink()
                        except OSError:
                            pass
            return head

    # ---- persistence ----
    def to_dict(self):
        with self.lock:
            return {"format": FORMAT_VERSION, "recorder": VERSION, "title": self.title, "created": self.created,
                    "host": self.host, "environment": self.environment, "settings": self.settings,
                    "steps": [asdict(s) for s in self.steps]}

    def save(self):
        """Atomic write, so a crash mid-save can't corrupt the session."""
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / "session.json.tmp"
            tmp.write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.dir / "session.json")
            return True
        except OSError:
            return False

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        p = folder / "session.json"
        if not p.exists():
            if (folder / "steps.md").exists():
                return cls.from_legacy(folder)
            raise FileNotFoundError(f"No session.json in {folder}")
        data = json.loads(p.read_text(encoding="utf-8"))
        s = cls(folder, data.get("title", "Recorded steps"))
        s.created = data.get("created", s.created)
        s.host = data.get("host", s.host)
        s.environment = data.get("environment", {})
        s.settings = data.get("settings", {})
        s.steps = [Step.from_dict(d) for d in data.get("steps", [])]
        return s

    @classmethod
    def from_legacy(cls, folder):
        """Rescue a version-1 recording from its steps.md + images/step_NNN.jpg (annotated images only)."""
        folder = Path(folder)
        text = (folder / "steps.md").read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        title = next((ln[2:].strip() for ln in lines if ln.startswith("# ")), "Recovered steps")
        s = cls(folder, title)
        blocks = re.split(r"^## Step \d+\s*$", text, flags=re.M)[1:]
        for blk in blocks:
            body = [ln for ln in blk.strip().splitlines()]
            img = ""
            m = re.search(r"!\[[^\]]*\]\(([^)]+)\)", blk)
            if m:
                img = m.group(1)
            if body and body[0].startswith(">"):
                note = "\n".join(re.sub(r"^>\s?", "", ln) for ln in body if ln.startswith(">"))
                note = re.sub(r"^\*\*Note:\*\*\s*", "", note)
                s.steps.append(Step(new_id(), "note", level="note", friendly=note, tech=note))
                continue
            cap = next((ln.strip().rstrip() for ln in body if ln.strip().startswith("**")), "")
            cap = re.sub(r"^\*\*(.*?)\*\*\s*$", r"\1", cap)
            meta = next((ln.strip().strip("_") for ln in body if ln.strip().startswith("_")), "")
            win = ""
            when = ""
            mm = re.search(r"Window:\s*(.*?)\s*\|\s*Time:\s*(\S+)", meta)
            if mm:
                win, when = mm.group(1), mm.group(2)
            else:
                mt = re.search(r"Time:\s*(\S+)", meta)
                when = mt.group(1) if mt else ""
            kind = "type" if cap.startswith("Typed text") else "click"
            s.steps.append(Step(new_id(), kind, when, cap, cap, window=win, image=img))
        return s


# ---------------------------------------------------------------------------
# wording
# ---------------------------------------------------------------------------
_VERB = {"left": "Click", "right": "Right-click", "middle": "Middle-click"}


def _q(name):
    return f'"{name}"'


# control types that are just containers: a name like "Message 73 of 74" says little, so OCR text helps
CONTAINER_KINDS = ("Group", "Pane", "Custom", "Document", "Window", "List", "Table")


def click_texts(kind, el):
    """(friendly, technical) captions for a click/dblclick/drag, from the stored element info.
    `el["near"]` (optional) is OCR text found next to the click; it is added when the control itself has no useful name."""
    friendly, tech = _click_texts(kind, el)
    near = (el or {}).get("near", "")
    if near:
        q = _q(near)
        tech += f" near text {q}"
        if (el or {}).get("name"):
            friendly += f" near {q}"
        else:
            friendly = friendly.rsplit(" on ", 1)[0] + f" near {q}"
    return friendly, tech


def _click_texts(kind, el):
    el = el or {}
    btn = el.get("button", "left")
    name, ck, inh = el.get("name", ""), el.get("kind", ""), el.get("inherited", False)
    x, y = el.get("x"), el.get("y")
    dbl = kind == "dblclick"

    # ---- technical ----
    tv = ("Double " if dbl else "") + {"left": "left click", "right": "right click", "middle": "middle click"}.get(
        btn, f"{btn} click")
    tv = tv[0].upper() + tv[1:]
    if kind == "drag":
        tv = "Drag"
    if name and ck and inh:
        tech = f'{tv} in "{name}" ({ck})'
    elif name and ck:
        tech = f'{tv} on "{name}" ({ck})'
    elif ck:
        tech = f"{tv} on {ck}"
    else:
        tech = f"{tv} at ({x}, {y})"

    # ---- friendly ----
    verb = "Double-click" if dbl else _VERB.get(btn, f"{btn.title()}-click")
    if kind == "drag":
        verb = "Drag"
    if not name:
        what = f"the {ck.lower()}" if ck else "the screen"
        return f"{verb} on {what}", tech
    q = _q(name)
    if inh:
        return f"{verb} in {q}", tech
    click = verb == "Click"
    phrase = {
        "Button": f"{verb} the {q} button", "SplitButton": f"{verb} the {q} button",
        "MenuItem": f"Select {q} from the menu" if click else f"{verb} the {q} menu item",
        "TabItem": f"{verb} the {q} tab",
        "CheckBox": f"{verb} the {q} checkbox",
        "RadioButton": f"Select the {q} option" if click else f"{verb} the {q} option",
        "Hyperlink": f"{verb} the {q} link",
        "Edit": f"{verb} in the {q} text box",
        "ComboBox": f"{verb} the {q} drop-down",
        "ListItem": f"Select {q}" if click else f"{verb} {q}",
        "TreeItem": f"Select {q}" if click else f"{verb} {q}",
        "DataItem": f"Select {q}" if click else f"{verb} {q}",
        "Image": f"{verb} the {q} image",
        "TitleBar": f"{verb} the title bar of {q}",
        "Window": f"{verb} in the {q} window",
    }.get(ck)
    return phrase or f"{verb} {q}", tech


def drag_texts(src, dst):
    s, t = (src or {}), (dst or {})
    if s.get("name") and t.get("name") and s["name"] != t["name"]:
        return (f'Drag {_q(s["name"])} to {_q(t["name"])}',
                f'Drag from "{s["name"]}" ({s.get("kind", "")}) to "{t["name"]}" ({t.get("kind", "")})')
    if s.get("name"):
        return f'Drag {_q(s["name"])}', f'Drag from "{s["name"]}" ({s.get("kind", "")})'
    return "Drag the mouse", f"Drag from ({s.get('x')}, {s.get('y')}) to ({t.get('x')}, {t.get('y')})"


def scroll_texts(direction, name):
    f = f"Scroll {direction}" + (f" in {_q(name)}" if name else "")
    return f, f


def type_texts(mode, text, count, password):
    if password:
        return ("Type your password", f"Typed text in a password field ({count} characters, hidden)")
    if mode == "text":
        return (f"Type {_q(text)}", f"Typed text: {text}")
    return (f"Type some text ({count} characters)", f"Typed text ({count} characters)")


def shortcut_texts(combo):
    return f"Press {combo}", f"Key combination {combo}"


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------
def collect_environment(monitors=None):
    env = {
        "Recorded": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Computer": socket.gethostname(),
        "User": os.environ.get("USERNAME") or os.environ.get("USER") or "",
        "Operating system": platform.platform(),
        "Python": platform.python_version(),
        "Recorder": f"Telestep {VERSION}",
        "Recorder running as administrator": "yes" if is_admin() else "no",
    }
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")

        def q(name):
            try:
                return str(winreg.QueryValueEx(k, name)[0])
            except OSError:
                return ""

        name, disp, build, ubr = q("ProductName"), q("DisplayVersion") or q("ReleaseId"), q("CurrentBuild"), q("UBR")
        if build and int(build) >= 22000:
            name = name.replace("Windows 10", "Windows 11")
        env["Windows"] = f"{name} {disp} (build {build}.{ubr})".strip()
    except Exception:
        pass
    try:
        import ctypes

        class MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = MEM()
        m.dwLength = ctypes.sizeof(MEM)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            env["Memory"] = f"{m.ullTotalPhys / 2**30:.1f} GB"
    except Exception:
        pass
    env["Processor"] = platform.processor() or platform.machine()
    env["CPU threads"] = str(os.cpu_count() or "?")
    if monitors and len(monitors) > 1:
        env["Displays"] = "; ".join(f"{i}: {m['width']}x{m['height']} at {m['left']},{m['top']}"
                                    for i, m in enumerate(monitors[1:], 1))
    try:
        import locale
        env["Locale"] = locale.getlocale()[0] or ""
    except Exception:
        pass
    env["Time zone"] = dt.datetime.now().astimezone().tzname() or ""
    return {k: clean_text(str(v)) for k, v in env.items() if v}


def environment_text(env, title=""):
    lines = [f"Environment - {title}" if title else "Environment", ""]
    w = max((len(k) for k in env), default=0)
    lines += [f"{k.ljust(w)} : {v}" for k, v in env.items()]
    return "\n".join(lines) + "\n"
