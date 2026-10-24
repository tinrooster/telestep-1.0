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
| Ctrl+Shift+F5 | comment on the next step (a line shown under its caption) |

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
- Styles: solid black, soft gray + "Hidden" label, match background (looks like nothing was there), pixelated (normal or fine), blurred (normal or heavy). For real secrets (passwords, keys) use solid black: blur and pixelation are meant to look good, not to withstand a determined attempt to undo them.
  **Faded** only de-emphasises - the text is still readable, so don't use it for secrets.
- **Hide common secrets** (Privacy tab) is one click: it turns OCR on and ticks every kind below.
- **OCR redaction** (optional) masks anything that looks like an IP address, MAC address, long key/token, e-mail, card-like number or ID number (123-45-6789).
  Needs `pip install pytesseract` **and** the Tesseract program (https://github.com/UB-Mannheim/tesseract/wiki).
  OCR can miss text - treat it as a safety net and review the pictures.
- In the review editor you can drag a rectangle on any screenshot and mask it (this step or all steps) after the fact.
- **Rules for one app:** in the review editor, select an area, right-click the picture and choose *Hide selected area now and
  in future recordings of this window...*. Telestep remembers that part of any window whose title contains your text (as a
  share of the window, so it still fits after a resize) and hides it in every future recording. It appears in the mask list
  and can be removed there.

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

## Hiding private information in the review editor
Select a step, then **click and drag a box on the picture** around what to hide (it turns orange). Pick a style, then click
**Hide this area**. Tick *Same area on every screenshot* to apply it to all of them. **Clear** cancels the box. Hiding
permanently changes the saved screenshot(s), so it is not undone by closing the editor.

## Toolbar icons: Review and Folder
- **Review / edit / export (list icon):** shows Telestep's own list of saved recordings (date, title, steps), newest first.
  Pick one and it opens in the editor, where you fix captions, hide private areas and export. *Browse for another
  folder...* is there for recordings stored elsewhere. After you stop a recording the editor opens by itself.
- **Recordings folder (folder icon):** opens File Explorer on the recordings folder, for grabbing the exported files
  (Word, PDF, ...) or the screenshots. It doesn't open anything in Telestep.

## Icon toolbar

The **minimize** button on the toolbar (or right-click > *Minimize to an icon*, or Settings > Options) shrinks the toolbar to a small icon that stays on top of your windows. Point at it for **Record / Pause / Stop** and a **Settings** button; move away and it shrinks back. The icon shows the state: the Telestep logo when idle, a red tile with a white dot while recording, an amber tile with a pause sign while paused. Drag it to move it.

Settings opens the full toolbar; when you collapse Settings (the ▲ button) you are back to the icon. To leave icon mode altogether, right-click the icon and choose *Full toolbar*. Clicks on the icon are never recorded.

## Toolbar opacity

Settings > Options > Toolbar opacity makes the toolbar see-through (30-100%). It only applies while Settings is collapsed; with Settings open the toolbar is solid (while you drag the slider you see the chosen level). With "Solid while the pointer is over it" ticked it also becomes fully solid when you point at it.

## Mark up the pictures
The **Tools** row right under the picture switches the mouse between *Hide area* (the privacy tool), *Select / move*,
*Box*, *Arrow*, *Text* and *Number*. The raised button that looks pressed is the active tool, and the line at the
bottom of the picture says what it does. Drawing tools are one-shot: after you place a mark the tool goes back to
*Select / move*, so the next click moves things instead of adding more. Tick **Keep tool** to place several in a row.
- **Box / Arrow**: drag on the picture. **Number**: click to drop 1, 2, 3 ... call-outs (they renumber if you delete one).
- **Text** is typed straight onto the picture: click (or drag a box to set its width) and type. **Enter** finishes,
  **Shift+Enter** starts a new line, **Esc** cancels. Double-click a text mark to edit it again.
- **Move and resize**: with any mark tool, drag an existing mark to move it; drag a box corner or an arrow end to resize
  it, or the side handles of a text mark to change its width (the text re-wraps). Arrow keys nudge the selected mark by 1 pixel (Shift = 10), **Delete** removes it.
- A bar docked at the bottom of the picture appears for the selected mark: **colour**, **opacity** (so a number or note
  doesn't hide what is under it), **size**, and for text the **font** (Sans, Serif, Console, Handwriting), **bold** and
  **background** (boxed, or plain with a halo). New marks start with whatever you chose last.
- **Right-click the picture** for the same things: edit text, duplicate, bring to front / send to back, delete, add text
  or a number exactly there, switch tool, undo, clear.

Marks are stored with the step (the saved screenshot is never changed), look blue by default so they stand apart from
Telestep's red click marker, and appear in every export. Marks go on the *Before* picture.

## Comments
A step can have a one-line comment shown under its caption (for what to wait for, why, or what to expect). While recording
press Ctrl+Shift+F5 (or right-click the toolbar > *Comment on next step*) and it is attached to the next step you record.
In the review editor use the **Comment** box under the caption.

## Voice narration
While recording, click the **microphone button** on the toolbar to start narrating (it turns red; click again to mute). Talk
while you work. When you stop, Telestep finds your sentences and gives each step its own clip. It cuts at the **pauses in
your speech, not at the click**, so you can talk straight through your clicks:
- Speech that overlaps a click (or ends right before it) goes with that click and is never chopped in half.
- Speech in a gap between clicks goes with the **next** click (you say what you are about to do) or the **previous** one
  (you explain what just happened): choose in *Settings > Audio*, or change your mind later with *More > Re-cut voice notes*
  in the review window.
- One long run of speech across several clicks is cut at the quietest moment near each click.
- Long silences (waiting for a page to load) are cut out of the clips.
Pausing the recording also mutes the microphone, so nothing said while paused is kept, and steps recorded while the mic is
off simply get no clip. A 🔊 in the step list marks steps with a voice note. The mic always starts **off**; a red mic icon stays visible on the
collapsed toolbar badge while recording (click it to switch), so you always know whether you are being recorded.

**Settings > Audio** lets you pick the microphone, **Test** it (live level bar, then play back what it heard) and open the
Windows sound / microphone-privacy settings. There is also an option to start every recording with the mic on.

The full narration is kept as `audio/narration.wav` in the recording folder (used for re-cutting). If no clips come out,
Telestep says why when you stop and writes `audio/narration_problem.txt`.

In the review editor, **Voice note** under the caption lets you play (with a progress bar and Stop), re-record or remove a
step's clip, and **Play all** steps through the whole recording showing each step while its clip plays (you can also add
notes to a recording made without narration). Voice notes are saved as `audio/` files in the recording folder; merging steps
joins their clips, duplicating copies them.

Exports: the **HTML** report gets a play button per step (about 1.3 MB per minute of speech, so long narrations make big
files), and the **ZIP bundle** and Markdown include and link the audio files. Word, PDF and plain text cannot play sound,
so they leave it out.

Privacy: the privacy check and hide tools work on pictures and text only. **Voice is not scrubbed**, so check what you said
before sharing a recording. Needs Windows and a microphone that desktop apps are allowed to use (Settings > Privacy >
Microphone). Command line: `--narrate`.

## Editing steps
- **Merge**: select two or more steps (Ctrl+click or Shift+click) and use *More > Merge selected steps* (or right-click).
  The captions are joined ("Click File, then click Save"), the first screenshot is kept and the last one becomes the
  *After* picture. The other steps are removed.
- **Duplicate** a step (for example to mark up the same screenshot twice), **Move to top / bottom**, and Up / Down now move
  a whole selection together. Select a range with Shift+click and **Delete** removes it.

## Hotkeys
In Settings, click a hotkey box and press the keys you want (for example Ctrl+Shift+F7). Esc cancels, Backspace resets
to the default. A key can't be used twice, and plain letters need Ctrl, Alt or Shift.

## Review editor: left-out steps and close-ups
- The **In report** column shows a tick for steps that will be in the report. Click the box (or use *Leave out* / *Put back*)
  to switch a step. Left-out steps are greyed, and the picture shows a red "LEFT OUT OF THE REPORT" tag.
- **View** under the picture: *Whole screenshot*, or *Close-up of the click* at 100%, 150% or 200% of real size. The close-up
  centres on the click, and hiding areas works the same way in either view.

## Report styles (Documentation mode)
Under **Report > Style** in the review window:
- **Technical report** - everything: times, window and app details, dialog text and the environment appendix.
- **Documentation** - steps and pictures only (numbered captions, no timestamps, machine names or dialog dumps; automatic
  technical entries are left out). Meant to be edited into a user guide.
- **Documentation - one sheet** - the same content with small pictures side by side, sized to fit one page when it can.
Your own section headings and Note / Warning / Tip callouts are kept in every style. Header, Footer, Author and Logo appear in
every format (Word and PDF page header/footer, HTML, Markdown, and the plain-text file).

## Focus: blur everything except what was clicked
Under the picture in the review window (and on the toolbar's Report tab), **Focus** can blur the rest of the screen:
- **Blur all but the clicked window** - the window you clicked stays sharp, the rest of the desktop is blurred.
- **Blur all but the clicked control** - only the control you clicked (plus a little context) stays sharp. If Telestep
  couldn't tell which control it was, a patch around the click is kept.
It only changes the pictures in the report; the saved screenshots are untouched, so you can switch it off again.
Recordings made before this feature don't know the window's outline, so *window* leaves them as they are.
In Support mode set `"focus": "window"` or `"control"` in `telestep_support.json`.

## Exporting
**Export** (the blue button, also Ctrl+Enter) writes the files into the recording folder shown beside it; it then offers to
open that folder. If you close the window with changes that haven't been exported, Telestep asks first.

Formats: Markdown (with a pictures folder), Word, HTML (one self-contained file), PDF and plain text, plus
- **Runbook checklist** (`runbook.md`): a tick-box procedure (`- [ ]` per step), warnings gathered under "Before you start",
  and a *Verification log* with the *Last verified* date and author (blank date = the day you export).
- **ZIP bundle** (`steps_bundle.zip`): `steps.md` plus only the pictures it uses, ready to attach to a wiki page or ticket.

**Check for private information before exporting** (on by default, switch it off under the format boxes): Telestep searches
captions, comments, window titles and dialog text for e-mail addresses, IP and MAC addresses, long keys, card-like and ID
numbers, and text such as `password: ...`. If it finds something a list opens: *Hide* replaces it with [hidden], *Ignore*
remembers that it is fine, *Also scan the screenshots* runs OCR over the pictures (slow, needs Tesseract) and *Hide* then
covers the matches. Matches are guesses; a clean result does not prove a screenshot is safe.

## Portable mode and updates
- **One copy at a time**: starting Telestep while it is already running just says so (Support mode has its own check).
  Start with `--allow-multiple`, or set `TELESTEP_MULTI=1`, to run two on purpose.
- **Portable mode**: create an empty file named `portable.txt` next to `Telestep.exe` (or the scripts). Settings, the log
  and, unless you pick another folder, recordings (`Recordings\`) then live beside the program, so it can run from a USB
  stick. Without that file everything is under `%APPDATA%\Telestep` and `Documents\Telestep`.
- **Update check**: off by default. Switch it on in Options, or use *About > Check for updates*. It makes one HTTPS request
  to the project's GitLab release list (nothing about you or your recordings), at most weekly, and only offers to open the
  download page; it never downloads or installs anything. It is the only time Telestep uses the internet.

## Troubleshooting

**Toolbar says "Catching up"** - processing (mostly OCR redaction) is behind your clicks. At 25 waiting clicks Telestep warns you; at 60 it stops taking new clicks until it has caught up, so memory doesn't fill up. Pause between clicks, or turn off OCR redaction you don't need.

**A slow or frozen window** - Telestep keeps a log, `telestep_debug.log` next to the settings file (About > Open the log folder). It notes each run and recording, every slow step with where the time went, and where the window was stuck if it ever froze for more than a few seconds. Send that file along with a description.

## Right-click menus
- **Step list (review editor):** edit or copy the caption, reset it to automatic wording, move up/down, leave out of the report or put back,
  delete, insert a section heading or note above/below, select all.
- **Picture (review editor):** *Select the clicked control* outlines the control you clicked (then choose a style or press
  **Hide this area**); *Hide selected area as...* hides it straight away in the style you pick; *...on every screenshot*;
  switch Before/After; leave out or delete the step.
- **Toolbar:** record/pause/stop, add a note, take a screenshot, open a saved recording, show the recordings folder, minimize to an icon, settings,
  Help, About, hide to tray, Quit.

## Support mode
Started with `Telestep.exe --support` (or an exe named *Support*): type what is wrong, click **Record**, repeat the
problem, click **Stop and package**. Telestep saves one ZIP on the Desktop to send to IT. Pause (F9) before showing
passwords or private data. After you stop, you can look through the screenshots and hide anything private before the ZIP is made. Enter your name and a phone number or email so IT can reach you. Use **Note** to point out where something goes wrong.

## Tray icon, .exe
- Tray icon (Options): `pip install pystray`. With the tray icon on, the close button hides Telestep to the tray (untick "close button sends it to the tray" to make it quit instead). Double-click the icon or choose **Show toolbar** to bring it back; **Quit** in the tray menu exits.
- The icon may sit under the **^** hidden-icons arrow in the taskbar; drag it out to keep it visible. It shows the Telestep logo, with a red badge while recording and an amber badge while paused.
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
