# Changelog

## Unreleased

- Icon toolbar: minimize the toolbar to a small always-on-top icon (button on the toolbar, right-click menu, or Settings > Options). Pointing at it expands Record / Pause / Stop and a Settings button (which shows the full toolbar and returns to the icon when Settings is collapsed); the icon shows idle / recording / paused. Drag to move. Right-click > Full toolbar leaves icon mode.
- INSTALL.md: install, build and troubleshooting guide.
- HELP.md: troubleshooting entries tidied.

- Options: toolbar opacity slider (30-100%), applied only while Settings is collapsed, optionally solid while the pointer is over the toolbar. Saved with the settings.

- Build scripts: `--noupx` and `--exclude-module numpy/pandas/setuptools/pkg_resources` (a normal Python install was pulling them into the exe), and a note to build from a clean virtual environment.

- Hide styles simplified: removed Hatched and Frosted glass; added Pixelated (fine), Blurred and Blurred (heavy) (real Gaussian blur that blends with its surroundings). Old settings and sessions that used the removed styles open as Soft gray / Blurred.

- Privacy tab: one "Use OCR" switch turns OCR redaction and click labelling on or off while keeping your ticked options (they grey out when it is off). It is saved with the settings and shown in the toolbar summary.

- Backlog guard: if a slow computer falls behind, Telestep warns at 25 waiting clicks and pauses capturing at 60 (each waiting click holds a full screenshot in memory), then resumes by itself at 15. The toolbar shows "Catching up" while paused.
- Privacy tab: note that OCR is the slowest part of recording.

- Debug log has headers: one line per app start (version, Windows, CPU threads), and one per recording (title, folder, capture mode, screens, redaction/label OCR, saved step count and total time). It starts over past 2 MB.

- OCR redaction remembers each monitor's last picture: a monitor that hasn't visibly changed since the previous click is not read again (a changed monitor, or even one new line of text, always is). Typically 2-3x faster on multi-monitor setups.
- "Near text" labels are now read from the full-size picture instead of the downsized one (multi-monitor pictures were shrunk until the text was unreadable) and look further from the click, so clicking blank space in a card can still name the card.

- The debug log's slow-step lines now break the time down (lookup, redact, label-ocr, save, app-info, after-wait).

- OCR redaction on multi-monitor screenshots reads the picture in parallel strips: about 8x faster in testing (18 s -> 2 s for three 1920-wide screens), and finds slightly more text.
- Cleaner "near text" labels: light-on-dark (dark mode) text is read properly, low-confidence words are dropped, and fragments that don't look like words are left out instead of recorded.

- Slow programs (Chrome web apps, Electron): if looking up the clicked control takes over 2.5 s twice for the same program, later clicks in it are named by window title instead, so recording keeps up. Screenshots are unaffected.
- About page: "Open the log folder" link.

- Fix: when processing lagged behind your clicks (OCR on several monitors), a click could be labelled "Desktop" and miss the Focus blur, because the window under the pointer was looked up late. The window's position is now measured at click time, and an element from a different program is ignored.
- Toolbar counter shows clicks still being processed ("● REC 12 +3 steps").

- Toolbar shows a one-line summary while idle and Settings is closed (title, screen, redaction, what happens on stop). Click it to open Settings.

- Stopping a recording no longer freezes the window: saving runs in the background and the toolbar shows "Saving... N steps left".
- `telestep_debug.log` now notes any step that takes over 2 s to process (with the redaction time), to pinpoint slow multi-monitor saves.
- Support mode (`--support`, `build_support_exe.bat`): one-button recorder that writes a single ZIP with a one-sheet report for IT.
- Focus option: blur everything except the clicked window or control (review window, Report tab, and `"focus"` in the
  Support config). Report pictures only; the saved screenshots are never changed.
- Review window: starts from the toolbar's Header/Footer/Author/Logo for a new recording, opens big enough to show the
  picture (with a message if the screen is too small), close-up zoom is 100/150/200%, and one-sheet pictures line up
  across a row even when a caption wraps.
- Documentation mode: report Style = Technical report / Documentation / Documentation - one sheet (no timestamps, window
  details, dialog dumps or environment; automatic technical entries dropped; condensed grid layout for one sheet).
- Review window: the action bar (Export, Copy steps, Open folder, Close) is always visible; Export is the blue default
  button (Enter / Ctrl+Enter), shows where files were saved and offers to open the folder; closing with unexported
  changes asks first.
- Footer, author and logo are larger and now also in the plain-text and Markdown exports.
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
