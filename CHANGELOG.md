# Changelog

## Unreleased

- New export format "Narrated player (HTML)": the Play all walkthrough as one self-contained, offline file (screenshots shown while each voice note plays, auto-advance, controls, progress bar, step list, speed).
- Review: Play now also works on several selected steps (their clips play one after another in list order, showing each step; the selection is restored afterwards). The open-mic icon pulse is much stronger (the disc swells and flashes with a rippling halo).
- Collapsed toolbar while recording: the app logo stays, a red record dot (click to pause) and the microphone indicator sit beside it, and hovering only adds Pause / Stop / Settings (the greyed-out Record button is gone while recording). An open microphone is a bigger red icon that ripples, so it can't be mistaken for "off".
- Voice clips are cut at pauses in your speech instead of at the click (speech over a click stays whole; speech between clicks goes with the next or previous click: Settings > Audio; More > Re-cut voice notes in Review). Long silences are trimmed. Review: Play/Stop with progress bar and Play all walkthrough. The mic indicator on the collapsed toolbar no longer moves when the toolbar expands.
- Voice narration: new Settings > Audio tab (choose microphone, live level test with play back); mic always starts off; red mic indicator stays on the collapsed badge while recording; recorder rewritten on Windows waveIn on a single helper thread (fixes "device is not open"). Toolbar microphone button switches narration on and off while recording (mute follows Pause); setting means "mic on from the start"; explains and keeps the raw recording if no clips come out. Microphone recording while you work, cut into one clip per step; play, re-record or remove clips in the review editor; HTML report gets players, ZIP bundle and Markdown include the audio. Uses only Windows built-ins (no new packages).
- Single instance: starting Telestep (or Support mode) a second time shows "already running" instead of opening another toolbar; `--allow-multiple` or `TELESTEP_MULTI=1` overrides.
- Review step list: more row height and alternating row shading; text marks can be resized from their side handles.
- Mark-up polish: the format bar is docked at the bottom of the picture instead of following the mark; plain arrow pointer for the mark tools; drawing tools are one-shot (back to Select / move after placing one; "Keep tool" to place several); tools are raised buttons with the active one pressed and highlighted; fonts reduced to Sans, Serif, Console and Handwriting (older saved names map to these).
- Mark-up tools reworked: a Tools row directly under the picture (Hide area / Select / Box / Arrow / Text / Number) whose hint updates as soon as the tool is chosen; text typed inline on the picture (drag a box to set its width, double-click to edit); marks can be dragged, and box corners and arrow ends resized; a floating bar sets colour, opacity, size, font, bold and background; right-click menu on the picture (edit, duplicate, front/back, delete, add text or number here); arrow keys nudge, Delete removes.
- "Hide common secrets" no longer freezes the window: it used to ask Tesseract for its version again on the UI thread; the answer is now cached.
- Privacy: card-like and ID numbers join the OCR kinds; a "Hide common secrets" button turns OCR on and ticks them all. A check before export searches captions, comments, window titles and dialog text (and, on request, the screenshots by OCR) for private-looking data and offers to hide or ignore it. Rules for one app: from the review editor, hide an area now and in future recordings of any window with a given title (stored as fractions of the window).
- Review editor: merge steps, duplicate a step, move to top/bottom, and move several selected steps together; a Comment line under any step (also recorded with Ctrl+Shift+F5 / right-click > Comment on next step); box, arrow, text and numbered call-out marks drawn on the pictures (stored per step, never burned into the saved screenshot).
- Export: Runbook checklist (`runbook.md`, with "Last verified" and a verification log) and a ZIP bundle (`steps_bundle.zip`: Markdown plus the pictures it uses). Comments appear in every format.
- Portable mode: `portable.txt` (or an existing `settings.json`) next to the program keeps settings, the log and recordings there.
- Optional update check (off by default, Settings > Options, or About > Check for updates): one HTTPS request to the project's GitLab releases, never downloads anything.
- Default hide style is now Pixelated (fine) for new settings, the command line and the review window's Hide tool. Existing saved settings keep their choice.
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
