<p align="center"><img src="assets/telestep_logo_256.png" alt="Telestep logo" width="128"></p>

# Telestep

Local, offline step recorder for Windows - a replacement for the Problem Steps Recorder (PSR).
It records what you click, with annotated screenshots, window and application names, and the name of the control you
touched, then exports the result as Markdown, Word, HTML, PDF or plain text.

Nothing leaves your computer: no cloud service, no account, no upload.

## Features

- **Recording:** clicks, double-clicks, drags, keyboard shortcuts, optional scrolling, typed text (off, count only, or text; never passwords), manual screenshots, and error or message boxes with their text.
- **Per-step details:** window title, application name and version, and the UI element clicked (via UI Automation). A machine summary (`environment.txt`) is saved with each session.
- **After-click capture:** optionally capture the result after the click, with a configurable delay.
- **Capture area:** screen under the click, all screens, one screen, the window under the click, or a custom area. Optional taskbar exclusion.
- **Privacy:**
  - Masks (fixed areas, or windows matched by title that follow the window when it moves) are applied before anything is saved.
  - Styles: solid, soft gray, hatched, pixelated, frosted, background-matched, and faded (readable, for de-emphasis only).
  - Optional OCR redaction of IP addresses, MAC addresses, keys and e-mail addresses.
- **Review editor:** delete, exclude, reorder, edit captions, add section headings and Note / Warning / Tip callouts, switch between friendly and technical wording, and mask anything you missed after the fact.
- **Export:** Markdown, DOCX, HTML (single file), PDF and text, with header, footer, logo and an environment appendix.
- **Support mode:** a one-button recorder for end users that produces a single ZIP (one-sheet HTML report, steps, system and network details) to send to IT.
- **Toolbar:** icon mini-bar with on-screen overlays showing what is captured and masked, saved presets, hotkeys, optional tray icon, and a built-in Help / About window (F1).
- **Safe by design:** the session is autosaved after every step, so a crash loses nothing.

## Requirements

- Windows 10 (2004 or later) or Windows 11
- Python 3.10 or newer
- Optional: [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) for OCR redaction

## Install

```
git clone https://gitlab.com/ac-pcr1/telestep.git
cd telestep
python -m pip install -r requirements.txt
python telestep.py
```

`run_telestep.bat` starts the toolbar without a console window. Run it as administrator to record clicks inside
elevated (admin) windows; without that, Telestep warns you when an admin window is in front.

### Optional extras

```
python -m pip install pytesseract                  # OCR redaction (also install the Tesseract program)
winget install --id UB-Mannheim.TesseractOCR -e
python -m pip install pystray                      # tray icon
```

## Usage

1. Open the settings (gear): choose the capture area, masks and keyboard behaviour, or load a preset.
2. Press **Record**, do the task, then press **Stop** or **F10**.
3. The review editor opens. Tidy the steps, then **Export**.

| Hotkey | Action |
|---|---|
| F9 | pause / resume |
| F10 | stop |
| Ctrl+Shift+F7 | add a note, warning or tip |
| Ctrl+Shift+F8 | take a screenshot now |
| Ctrl+Shift+F6 | delete the last step |
| F1 | help |

Hotkeys can be changed in Options.

### Output

```
Documents\Telestep\<yyyymmdd_hhmmss>_<title>\
    session.json        all steps and settings (autosaved)
    raw\                screenshots without markers (masks already applied)
    images\             annotated copies, rebuilt on every export
    steps.md / .docx / .html / .pdf / .txt
    environment.txt
```

Open an earlier session from the toolbar (list icon), or from the command line.

### Command line

```
python telestep_recorder.py --title "Fix Teams audio" --capture window --hide-window "Password:soft" --keys none --format md,docx,html
python telestep_recorder.py --review <session folder>
python telestep_recorder.py --export <session folder> --format md,docx,html,pdf
```

`--export` also imports a version-1 recording (a folder with `steps.md` and `images/`). Run
`python telestep_recorder.py --help` for every option.

## Support mode (one-click recording for IT)

A stripped-down mode for end users: type what is wrong, click **Record**, repeat the problem, click **Stop**.
Telestep writes one ZIP to the Desktop and shows its name; the user attaches it to an email or ticket. Nothing is uploaded.

```
Telestep.exe --support            (or:  python telestep.py --support)
build_support_exe.bat             builds dist\Telestep-Support.exe, which always starts in support mode
```

The ZIP contains:

| File | Content |
|---|---|
| `Telestep_report.html` | one-sheet report: the user's description, error boxes seen, system details, every step with a screenshot (opens in any browser; prints to PDF) |
| `steps.txt` | the steps as plain text |
| `environment.txt`, `network.txt` | computer, OS, displays; `ipconfig /all` |
| `session\` | optional: the full session, to open in Telestep's review editor |

Defaults suit remote support: screenshot under each click, typed text counted but never recorded, error and message
boxes captured with their text, screenshots shrunk until the ZIP is under 10 MB, temporary files deleted when the
window closes. To change them, put `telestep_support.json` (see `telestep_support.example.json`) in the same folder as
the exe: help-desk contact shown to the user, size limit, output folder, capture mode, `include_session`,
`collect_network`, and so on. Support mode never touches the normal Telestep settings.

The window asks for the user's name and a phone number or email (pre-filled from Windows when it knows them) and puts
them at the top of the report. Set `"require_contact": true` to insist on both, or `"ask_contact": false` to skip them.

### Sending it to a user

1. Run `build_support_exe.bat`.
2. Edit `dist\telestep_support.json` (set `contact` to your help-desk details).
3. Send **both** files, `Telestep-Support.exe` and `telestep_support.json`, in one folder (a zip works well). The exe
   alone also runs, with the defaults and no contact line.
4. The user keeps them together, double-clicks the exe and follows the window; they send you the ZIP it creates.

## Build a single .exe

```
python -m pip install pyinstaller
build_exe.bat
```

This produces `dist\Telestep.exe`. `HELP.md` (the end-user guide), the license and the third-party notices are bundled inside it; Help and About show them. Add `--uac-admin`
to the PyInstaller line in `build_exe.bat` if you want it to always start elevated. Tesseract is not bundled; install it
on each PC that needs OCR redaction.

## Project layout

| File | Purpose |
|---|---|
| `telestep.py` | toolbar (main entry point) |
| `telestep_recorder.py` | recording engine and command line |
| `telestep_core.py` | Windows helpers, hotkeys, masks, OCR, annotation |
| `telestep_model.py` | session data (`session.json`), wording, environment info |
| `telestep_report.py` | Markdown, DOCX, HTML, PDF and text export |
| `telestep_review.py` | review and edit window |
| `telestep_widgets.py` | icons, overlays, dialogs |
| `telestep_settings.py` | saved settings and presets |
| `telestep_support.py` | Support mode (one-click recorder that produces a ZIP for IT) |
| `telestep_help.py` | Help, About and License window |
| `HELP.md` | end-user guide shown in the Help window (bundled in the exe) |
| `assets\` | logo and `telestep.ico` |

## Known limits

- Recording is Windows only.
- Message-box detection covers classic Windows dialogs; modern in-app dialogs show up as a normal screenshot after your click.
- The toolbar and overlays are hidden from screenshots using `SetWindowDisplayAffinity`, which needs Windows 10 2004 or later.
- A window mask hides the whole window rectangle, including parts of other windows that overlap it.
- OCR can miss text. Review the screenshots before sharing anything sensitive.

## Support

Contact TE_dev: alan.c.hay@abc.com

## License

[MIT](LICENSE) - Copyright (c) 2026 TE_dev.

Telestep depends on third-party packages under their own licenses (including LGPLv3 for the optional `pynput` and
`pystray`); see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Repository: <https://gitlab.com/ac-pcr1/telestep>

Developed with AI assistance (Claude, by Anthropic). Provided as is, without warranty.
