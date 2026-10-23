# Telestep - local replacement for Windows PSR

Records what you click, with annotated screenshots, window/app names and the control you touched, then exports
to Markdown, Word, HTML, PDF or plain text. Everything stays on your machine.

## Help
Press **F1** or the **?** icon in the toolbar for this guide (it is bundled inside the .exe) and the About page.

## Install
```
python -m pip install pynput mss pillow uiautomation python-docx reportlab
python telestep.py          (or double-click run_telestep.bat)
```
Keep all the `telestep*.py` files in one folder. Replace any older copies together - they depend on each other.

## Day to day
1. **Gear > Capture / Privacy** - choose the area, masks, keyboard behaviour (or load a **preset** on the General tab).
2. **Record** (red dot). Do the task. **Stop** (square) or press **F10**.
3. The **review editor** opens: fix captions, delete/reorder, add section headings and Note / Warning / Tip callouts,
   black out anything you missed, then **Export**.

| Hotkey | Action |
|---|---|
| F9 | pause / resume |
| F10 | stop |
| Ctrl+Shift+F7 | add a note / warning / tip |
| Ctrl+Shift+F8 | take a screenshot now (no click needed) |
| Ctrl+Shift+F6 | delete the last step |

(Change them in Options. They use Windows `RegisterHotKey`, not a keyboard hook, so "Mouse only" really means no key logging at all.)

## What gets recorded
Clicks, double-clicks, drags (arrow drawn), keyboard shortcuts (`Press Ctrl+S`), optional scrolling, typed text
(off / count only / text; never passwords), manual screenshots, and **error / message boxes with their text**.
Each step stores window title and application name + version. A machine summary (`environment.txt`) is saved and
can be appended to reports. If a window runs **as administrator** and Telestep doesn't, you get a warning
(and a warning note in the report) because Windows hides those clicks from non-admin programs.

**After-click capture:** Capture tab > *Screenshot* > "Also capture the result after the click" (or result only),
with a delay in ms. Handy for menus and dialogs that open on click.

## Hiding things (Privacy tab)
Masks are burned into the screenshot *before* it is saved - the unmasked screen never touches disk.
- **Add area** = fixed rectangle. **Add window** = hides any window whose title contains your text, wherever it moves
  (e.g. `Password`, `Vault`, `Teams chat`). (It hides the whole window rectangle, including parts of other windows that overlap it.)
- Styles: solid black, soft gray + "Hidden" label, hatched, pixelated, frosted glass, match background (looks like nothing was there).
  **Faded** only de-emphasises - the text is still readable, so don't use it for secrets.
- **OCR redaction** (optional) masks anything that looks like an IP address, MAC address, long key/token or e-mail.
  Needs `pip install pytesseract` **and** the Tesseract program (https://github.com/UB-Mannheim/tesseract/wiki).
  OCR can miss text - treat it as a safety net and review the pictures.
- In the review editor you can drag a rectangle on any screenshot and mask it (this step or all steps) after the fact.

## Files
```
<Documents>\Telestep\<yyyymmdd_hhmmss>_<title>\
   session.json     everything (autosaved after every step - safe if the PC crashes)
   raw\             screenshots without markers (masks already applied)
   images\          annotated copies, rebuilt on every export so numbers match after edits
   steps.md / .docx / .html / .pdf / .txt, environment.txt
```
Open an old session any time: list icon on the toolbar, or `python telestep_recorder.py --review <folder>`.
Re-export: `python telestep_recorder.py --export <folder> --format md,docx,html,pdf`.
A **version-1 recording** (steps.md + images) can be imported the same way (annotated pictures only, can't be re-annotated).

## Command line
```
python telestep_recorder.py --title "Fix Teams audio" --capture window --hide-window "Password:soft" ^
       --keys none --after pair --format md,docx,html
```
`python telestep_recorder.py --help` lists everything.

## Tray icon, .exe
- Tray icon (Options): `pip install pystray`.
- Single .exe: `pip install pyinstaller` then run `build_exe.bat`.

## Limits worth knowing
- Windows only for recording (the tools used are Windows APIs). Chrome/Electron apps give better control names with
  `--force-renderer-accessibility`.
- Message-box detection covers classic Windows dialogs; modern in-app dialogs are just a normal screenshot after your click.
- Screen overlays and the toolbar are hidden from screenshots using `SetWindowDisplayAffinity` (Windows 10 2004+ / 11).
- Masks that follow windows poll window positions at capture time; very fast window movement can leave a sliver visible.

## License and source
Telestep is free software under the MIT License. Source and issues: https://gitlab.com/ac-pcr1/telestep
See the License tab in this window for the full text and third-party notices.
