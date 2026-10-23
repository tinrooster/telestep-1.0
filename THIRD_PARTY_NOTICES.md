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
Telestep imports these libraries unmodified and does not alter them. The single-file `Telestep.exe` bundles them, so if
you redistribute the exe you should also make the Telestep source available (it is: https://gitlab.com/ac-pcr1/telestep)
and keep these notices with it. Users can replace the libraries by running Telestep from source with their own copies
(`python telestep.py`). This is a summary, not legal advice.
