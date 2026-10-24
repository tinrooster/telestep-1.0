# Third-party notices

Telestep itself is MIT licensed (see LICENSE). It uses the packages below, which are installed separately with pip and
keep their own licenses. License names are taken from each package's published metadata (checked 2026-10-22);
see each project for the full text.

| Package | Used for | License |
|---|---|---|
| pynput | mouse and keyboard listeners | LGPLv3 |
| pystray (optional) | tray icon | LGPLv3 |
| mss | screen capture | MIT |
| Pillow | image processing | HPND (MIT-CMU style) |
| uiautomation | control names via UI Automation | Apache 2.0 |
| python-docx | Word export | MIT |
| reportlab | PDF export | BSD |
| pytesseract (optional) | OCR redaction | Apache 2.0 |
| Tesseract OCR (optional, not bundled) | OCR engine | Apache 2.0 |
| PyInstaller (build only) | builds the .exe | GPLv2+ with a special exception that permits distributing the built program under any license |

## LGPL note (pynput, pystray)
pynput and pystray are licensed under the GNU LGPL v3. Telestep imports them unmodified and does not alter them. They are
separate libraries, not part of Telestep's own (MIT) code. The single-file `Telestep.exe` bundles them, so if you
redistribute the exe you must (1) keep this notice and the LGPL text with it, (2) make the library sources available
(they are on PyPI; Telestep's own source is at https://gitlab.com/ac-pcr1/telestep), and (3) let users swap in their own
version of these libraries - they can, by running Telestep from source (`python telestep.py`) with the library of their
choice installed. This is a summary, not legal advice; have your own counsel confirm if you redistribute commercially.
