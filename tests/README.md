# Telestep tests

Run everything:

    python tests/run_tests.py

Each `test_*.py` runs in its own process and prints `N passed, M failed`. The Windows-only libraries (pynput, mss,
uiautomation, pystray) are replaced by stand-ins in `harness.py`, so the suite also runs on Linux under a virtual display
(`xvfb-run -a python tests/run_tests.py`). Needs: pillow, numpy, python-docx, reportlab (pytesseract + Tesseract for the
OCR tests). GitLab runs it on every push (`.gitlab-ci.yml`).
