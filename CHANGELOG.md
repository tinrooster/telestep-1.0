# Changelog

## Unreleased
- Support mode (`--support`, `build_support_exe.bat`): one-button recorder that writes a single ZIP with a one-sheet report for IT.
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
