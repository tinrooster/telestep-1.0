# Changelog

## Unreleased
- Support mode (`--support`, `build_support_exe.bat`): one-button recorder that writes a single ZIP with a one-sheet report for IT.
- The capture outline (preview) now shows only while Telestep is the active window and Settings is on the Capture or
  Privacy tab; the "Show capture outline" checkbox on the Capture tab turns it off.
- The capture outline follows setting changes immediately (it could show a stale area in Window mode).
- A collapse button at the right of the settings tabs collapses back to the mini toolbar.
- build_support_exe.bat now builds a folder (--onedir) and zips it with the settings file and a read-me, printing the
  SHA-256, so it can be shared as a link. The single-exe build is kept as build_support_onefile.bat.
- Settings tabs are clearly separated: the current tab is white, bold and underlined.
- Review editor: an "In report" tick column, Leave out / Put back, a "left out" tag on the picture, and a
  close-up view of the click (50/100/200%).
- The Tesseract check no longer runs on the UI thread; freezes are written to telestep_debug.log.
- Hotkeys are set by clicking the box and pressing the keys (no typing of names).
- Review button opens a list of saved recordings (newest first) instead of a bare folder dialog; clearer tooltips.
- Stop icon is dark red (was dark grey).
- Right-click menus: step list, screenshot (including 'select the clicked control') and toolbar.
- Support mode: privacy text lists exactly what is collected; optional "check before sending" review (hide areas, delete steps); `review` and `ocr_labels` settings.
- Clicks on unnamed controls are labelled with nearby text via OCR (optional, needs Tesseract).
- Review editor: Hide this area / Cancel buttons beside the selection.
- Tray: logo icon with recording/paused badge, close-to-tray option.

## 1.0 - 2026-10-22
First release.
- Step recording with annotated screenshots, window/app names and UI Automation control names.
- Capture area options, taskbar exclusion, on-screen overlays, masks and optional OCR redaction.
- Review editor; export to Markdown, DOCX, HTML, PDF and text.
- Icon toolbar, presets, hotkeys, optional tray icon, Help / About / License window (F1).
- MIT license; third-party notices in THIRD_PARTY_NOTICES.md.
