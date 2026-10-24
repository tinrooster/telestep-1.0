# Installing Telestep

Telestep is a Windows program (Windows 10 version 2004 or later, or Windows 11). It runs entirely on the PC: nothing
is uploaded, and no account is needed. Pick the route that suits you:

| You want to... | Use |
|---|---|
| try it or develop it | [A. Run from source](#a-run-from-source) |
| put it on PCs that have no Python | [B. Build `Telestep.exe`](#b-build-a-single-exe) |
| send a one-click recorder to an end user | [C. Build the Support package](#c-build-the-support-package-for-it) |

## Before you start

- **Python 3.10 or newer** (only for A, and on the machine that builds B and C). Get it from python.org and tick
  **Add python.exe to PATH** in the installer. Check with `python --version`.
- **Git** (optional): to clone the repository. You can also download the repository as a ZIP from GitLab and unzip it.
- **Tesseract** (optional): only if you want OCR redaction or the "near text" click labels. See
  [Optional extras](#optional-extras).

## A. Run from source

1. Get the code:

   ```
   git clone https://gitlab.com/ac-pcr1/telestep.git
   cd telestep
   ```

2. (Recommended) create a virtual environment so Telestep's packages stay separate from the rest of your Python:

   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Install the packages:

   ```
   python -m pip install -r requirements.txt
   python -m pip install pytesseract pystray
   ```

   `requirements.txt` holds the required packages (`pynput`, `mss`, `pillow`, `uiautomation`, `python-docx`,
   `reportlab`). `pytesseract` (OCR) and `pystray` (tray icon) are optional but handy; Telestep works without them.

4. Start it:

   ```
   python telestep.py
   ```

   or double-click `run_telestep.bat`, which starts it without a console window. If you made a virtual environment,
   activate it first, or edit the last line of `run_telestep.bat` to use `.venv\Scripts\pythonw.exe`.

The toolbar appears at the top of the screen. Click the gear for settings, **Record** to start, **Stop** (or F10) to
finish, and the review window opens. `HELP.md` (also under the **?** button) is the user guide.

### Recording administrator windows

Windows stops a normal program from seeing clicks inside an elevated (administrator) window. To record those, start
Telestep as administrator: right-click `run_telestep.bat` (or `Telestep.exe`) and choose **Run as administrator**.
Telestep warns you when an admin window is in front and it isn't elevated.

## B. Build a single exe

Do this once on a build machine, then copy the exe anywhere. The target PCs need nothing installed.

```
python -m venv buildenv
buildenv\Scripts\activate
python -m pip install -r requirements.txt pytesseract pystray pyinstaller
build_exe.bat
```

The result is `dist\Telestep.exe` (about 26 MB). Building in a fresh virtual environment keeps unrelated packages
(numpy, pandas and so on) out of the exe, which makes it smaller and less likely to be flagged by antivirus.

- The help text, license and notices are bundled inside the exe.
- To make it always start as administrator, add `--uac-admin` to the PyInstaller line in `build_exe.bat`.
- Tesseract is not bundled. Install it on every PC that should use OCR.

## C. Build the Support package (for IT)

The Support package is a cut-down recorder for end users: they describe the problem, click **Record**, repeat it,
click **Stop**, and get one ZIP to send you.

1. Copy `telestep_support.example.json` to `telestep_support.json` and fill in your help-desk contact details. The
   other options are explained in `README.md` ("Support mode").
2. From the same virtual environment as in B, run:

   ```
   build_support_exe.bat
   ```

   This makes `dist\Telestep-Support.zip` (a folder build with your settings and a read-me, which antivirus flags less
   than a single exe) and prints its SHA-256.
3. Share the zip as a link rather than an email attachment, and publish the SHA-256 next to it. The user unzips it and
   runs `Telestep-Support.exe`.

`build_support_onefile.bat` builds a single `Telestep-Support.exe` instead. It works the same way but is flagged by
antivirus and SmartScreen more often.

## Optional extras

**OCR (hide IP addresses, keys and e-mail addresses automatically; name unlabelled clicks).**
Install the Tesseract program and the Python wrapper:

```
winget install --id UB-Mannheim.TesseractOCR -e
python -m pip install pytesseract
```

Telestep finds Tesseract in `C:\Program Files\Tesseract-OCR`. Open Settings > Privacy to see whether it was found.
OCR adds a few seconds of processing per click (more with several monitors); Settings > Privacy has a **Use OCR**
switch to turn it all off without losing your choices.

**Tray icon:** `python -m pip install pystray`. Without it, Telestep simply has no tray icon.

## Where things are stored

| What | Where |
|---|---|
| Recordings and reports | `Documents\Telestep` (change it under Settings > General) |
| Settings, presets, saved header and footer | `%APPDATA%\Telestep\settings.json` |
| Troubleshooting log | `%APPDATA%\Telestep\telestep_debug.log` (**About > Open the log folder**) |

To move Telestep to another PC, copy the program and, if you want your presets and header/footer, `settings.json`.

**Portable mode:** create an empty file named `portable.txt` next to `Telestep.exe` (or `telestep.py`). Settings
(`settings.json`), the log and, unless you choose another folder, recordings (`Recordings\`) are then kept beside the
program, so it can run from a USB stick or a locked-down PC without touching `%APPDATA%` or `Documents`.

**Network use:** none, except the optional update check (Settings > Options, off by default, or About > Check for
updates). It makes one HTTPS request to the project's GitLab release list and never downloads anything.

## Updating and removing

- **From source:** `git pull`, then `python -m pip install -r requirements.txt` again (if packages changed).
- **Exe:** replace `Telestep.exe` with the new build.
- **Removing:** delete the program folder or exe, and `%APPDATA%\Telestep` if you want the settings gone. Recordings in
  `Documents\Telestep` are yours; delete them separately if you wish. Telestep writes nothing to the registry.

## Troubleshooting

| Problem | What to try |
|---|---|
| `python` is not recognised | Reinstall Python and tick **Add python.exe to PATH**, or use `py -m pip` and `py telestep.py`. |
| `pip install` fails on `pynput` or `uiautomation` | Update pip first: `python -m pip install --upgrade pip`. Use 64-bit Python 3.10 or newer. |
| Nothing is recorded in some windows | Those windows are probably elevated. Run Telestep as administrator. |
| Windows SmartScreen or antivirus blocks the exe | Unsigned PyInstaller programs are often flagged. Use the folder build (C), share the SHA-256, and ask IT to allow-list it, or sign the exe. |
| "Tesseract is not installed" in Settings > Privacy | Install it (see above) and reopen Telestep. |
| No tray icon | `python -m pip install pystray`, then turn on **Tray icon** under Settings > Options. |
| Saving is slow with several monitors | OCR redaction is the slow part. Turn off the redaction types you don't need, or the **Use OCR** switch. |
| A hotkey doesn't work | Another program may own it. Click the hotkey box in Settings > Options and choose another. |

If something still misbehaves, open **About > Open the log folder** and look at `telestep_debug.log`; it shows slow
steps and freezes with timings, and is safe to share.
