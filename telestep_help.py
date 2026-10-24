"""
telestep_help.py - Help (HELP.md, bundled with the exe) and About window.
"""
import re
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

import telestep_core as core

APP_NAME = "Telestep"
AUTHOR = "TE_dev"
CONTACT = "alan.c.hay@abc.com"
HELP_TITLE = "Telestep Help"
REPO_URL = "https://gitlab.com/ac-pcr1/telestep"
LICENSE_NAME = "MIT License"
COPYRIGHT = "Copyright (c) 2026 TE_dev"


def about_lines():
    return [f"{APP_NAME} v{core.VERSION}", AUTHOR, CONTACT]


def _bundled(*names):
    """First existing file among `names`, next to the program or inside the PyInstaller bundle (--add-data)."""
    for base in (getattr(sys, "_MEIPASS", None), Path(__file__).resolve().parent):
        for n in names:
            if base and (Path(base) / n).exists():
                return Path(base) / n
    return None


def readme_path():
    """The end-user guide: HELP.md, falling back to README.md."""
    return _bundled("HELP.md", "README.md")


def license_text():
    """LICENSE plus THIRD_PARTY_NOTICES.md, as plain text for the License tab."""
    parts = []
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        p = _bundled(name)
        if p:
            try:
                parts.append(p.read_text(encoding="utf-8").strip())
            except OSError:
                pass
    if not parts:
        parts = [f"{LICENSE_NAME}\n{COPYRIGHT}\n\nThe license file was not found next to the program.\nSee {REPO_URL}"]
    return "\n\n" + ("\n\n" + "-" * 70 + "\n\n").join(parts) + "\n"


def logo_path(small=False):
    return _bundled("assets/telestep_logo_256.png" if not small else "assets/telestep_icon_64.png")


def apply_icon(win):
    """Give a Tk window the Telestep icon (silently skipped if the asset or Tk support is missing)."""
    p = logo_path(small=True)
    if not p:
        return
    try:
        img = tk.PhotoImage(file=str(p))
        win.iconphoto(True, img)
        win._telestep_icon = img  # keep a reference
    except (tk.TclError, OSError):
        pass


def readme_text():
    p = readme_path()
    if p:
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            pass
    return f"# {APP_NAME}\n\nThe help file (README.md) was not found next to the program.\n"


_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


def render_markdown(text_widget, md):
    """Very small Markdown renderer: headings, bullets, numbered lists, code blocks, tables, **bold**, `code`."""
    t = text_widget
    t.configure(state="normal")
    t.delete("1.0", "end")
    base = ("Segoe UI", 10)
    t.tag_configure("h1", font=("Segoe UI", 18, "bold"), spacing1=4, spacing3=8)
    t.tag_configure("h2", font=("Segoe UI", 13, "bold"), spacing1=14, spacing3=4, foreground="#1e5aa8")
    t.tag_configure("bold", font=("Segoe UI", 10, "bold"))
    t.tag_configure("code", font=("Consolas", 10), background="#eef0f3")
    t.tag_configure("block", font=("Consolas", 10), background="#eef0f3", lmargin1=16, lmargin2=16)
    t.tag_configure("bullet", lmargin1=16, lmargin2=30)
    t.tag_configure("table", font=("Consolas", 9), lmargin1=8)
    t.tag_configure("p", font=base, spacing3=2)

    def inline(line, *tags):
        for part in _INLINE.split(line):
            if not part:
                continue
            if part.startswith("**"):
                t.insert("end", part[2:-2], tags + ("bold",))
            elif part.startswith("`"):
                t.insert("end", part[1:-1], tags + ("code",))
            else:
                t.insert("end", part, tags)

    in_code = False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            t.insert("end", line + "\n", "block")
        elif line.startswith("# "):
            t.insert("end", line[2:] + "\n", "h1")
        elif line.startswith("## "):
            t.insert("end", line[3:] + "\n", "h2")
        elif line.startswith("|"):
            if set(line.replace("|", "").strip()) <= set("-: "):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            t.insert("end", "  " + cells[0].ljust(18) + "  ".join(cells[1:]) + "\n", "table")
        elif line.startswith("- ") or re.match(r"^\d+\. ", line):
            inline("• " + line[2:] if line.startswith("- ") else line, "bullet")
            t.insert("end", "\n")
        elif not line:
            t.insert("end", "\n", "p")
        else:
            inline(line, "p")
            t.insert("end", "\n")
    t.configure(state="disabled")


def open_log_folder(log_path=None):
    """Show telestep_debug.log in File Explorer (just the folder if no log has been written yet)."""
    import os
    import subprocess
    from pathlib import Path
    if log_path is None:
        import telestep_settings as cfg
        log_path = cfg.settings_path().with_name("telestep_debug.log")
    log_path = Path(log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists():
            subprocess.Popen(["explorer", f"/select,{log_path}"])
        else:
            os.startfile(str(log_path.parent))  # Windows only
    except Exception:
        pass


class HelpWindow(tk.Toplevel):
    """Help (README) and About in one window.  `start` = 'help' or 'about'."""

    def __init__(self, master, start="help", log_path=None):
        super().__init__(master)
        self.title(HELP_TITLE)
        apply_icon(self)
        self.geometry("760x640")
        self.minsize(520, 400)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        hp = ttk.Frame(nb)
        self.txt = tk.Text(hp, wrap="word", padx=12, pady=8, relief="flat", cursor="arrow")
        sb = ttk.Scrollbar(hp, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        render_markdown(self.txt, readme_text())
        nb.add(hp, text="Help")

        ab = ttk.Frame(nb, padding=30)
        name, author, contact = about_lines()
        self._logo = None
        lp = logo_path()
        if lp:
            try:
                self._logo = tk.PhotoImage(file=str(lp)).subsample(2, 2)
                ttk.Label(ab, image=self._logo).pack(anchor="center", pady=(10, 0))
            except tk.TclError:
                self._logo = None
        ttk.Label(ab, text=name, font=("Segoe UI", 24, "bold")).pack(anchor="center", pady=(10, 4))
        ttk.Label(ab, text="Local step recorder for documentation and troubleshooting",
                  foreground="gray").pack(anchor="center", pady=(0, 18))
        ttk.Label(ab, text=author, font=("Segoe UI", 13)).pack(anchor="center")
        link = ttk.Label(ab, text=contact, font=("Segoe UI", 11, "underline"), foreground="#1e5aa8", cursor="hand2")
        link.pack(anchor="center", pady=(4, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(f"mailto:{contact}"))
        repo = ttk.Label(ab, text=REPO_URL, font=("Segoe UI", 10, "underline"), foreground="#1e5aa8", cursor="hand2")
        repo.pack(anchor="center", pady=(12, 0))
        repo.bind("<Button-1>", lambda e: webbrowser.open(REPO_URL))
        lic = ttk.Label(ab, text=f"{LICENSE_NAME} - {COPYRIGHT}", foreground="gray")
        lic.pack(anchor="center", pady=(6, 0))
        log = ttk.Label(ab, text="Open the log folder (for troubleshooting)", font=("Segoe UI", 10, "underline"),
                        foreground="#1e5aa8", cursor="hand2")
        log.pack(anchor="center", pady=(12, 0))
        log.bind("<Button-1>", lambda e: open_log_folder(log_path))
        import telestep_core
        import telestep_settings as cfg
        ver = f"Version {telestep_core.VERSION}" + ("   |   Portable mode (settings are kept next to the program)"
                                                    if cfg.portable() else "")
        ttk.Label(ab, text=ver, foreground="gray").pack(anchor="center", pady=(12, 0))
        self.var_upd = tk.StringVar(value="")
        upd = ttk.Label(ab, text="Check for updates", font=("Segoe UI", 10, "underline"), foreground="#1e5aa8",
                        cursor="hand2")
        upd.pack(anchor="center", pady=(6, 0))
        upd.bind("<Button-1>", lambda e: self._check_updates())
        self.lbl_upd = ttk.Label(ab, textvariable=self.var_upd, foreground="gray", wraplength=520, justify="center")
        self.lbl_upd.pack(anchor="center")
        ttk.Label(ab, text="Everything is recorded and stored locally on this computer. The only time Telestep uses "
                           "the internet is\nwhen you press \"Check for updates\" (or switch the check on in "
                           "Settings > Options).", foreground="gray", justify="center").pack(anchor="center",
                                                                                           pady=(18, 0))
        nb.add(ab, text="About")

        lp_ = ttk.Frame(nb)
        self.lic = tk.Text(lp_, wrap="word", padx=12, pady=8, relief="flat", font=("Consolas", 9))
        sb2 = ttk.Scrollbar(lp_, command=self.lic.yview)
        self.lic.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.lic.pack(side="left", fill="both", expand=True)
        self.lic.insert("1.0", license_text())
        self.lic.configure(state="disabled")
        nb.add(lp_, text="License")
        nb.select(ab if start == "about" else hp)
        self.bind("<Escape>", lambda e: self.destroy())

    def _check_updates(self):
        """Ask GitLab for the newest release in a background thread; never installs anything."""
        import threading

        import telestep_core
        import telestep_update
        self.var_upd.set("Checking...")
        box = {}

        def work():
            box["r"] = telestep_update.check(telestep_core.VERSION)

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def poll():
            if t.is_alive():
                self.after(200, poll)
                return
            r = box.get("r", {})
            msg = {"newer": f"Version {r.get('version', '').lstrip('v')} is available.",
                   "current": f"You have the latest version ({telestep_core.VERSION}).",
                   "unknown": "No published releases were found.",
                   "error": f"Couldn't reach the update server ({r.get('error', '')})."}.get(r.get("status"), "")
            self.var_upd.set(msg)
            if r.get("status") == "newer" and messagebox.askyesno(
                    "Telestep", msg + "\n\nOpen the download page?", parent=self):
                webbrowser.open(r.get("url") or telestep_update.PAGE)

        self.after(200, poll)
