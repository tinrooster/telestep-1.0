# Telestep for Android

A step recorder for Android phones and tablets: it records which buttons you tap in other apps, with a screenshot of
each step, and saves the recording in the same format as desktop Telestep. Open it on your PC to edit it and export
Word, PDF, HTML, Markdown or the narrated player.

Android 11 or newer. Nothing leaves the phone unless you share a recording.

## How it works

Telestep is an **accessibility service**: Android tells it which element you tapped (its text, kind and position) and
lets it take screenshots. That is the only way an app can see taps in other apps, which is also why it is installed
from a file rather than from Google Play (Play restricts accessibility services to assistive apps).

- **Taps and long presses** become steps with a screenshot of the screen as it was *before* the tap, a red circle and
  outline on what you tapped, and (optionally) a second picture just after it.
- **Scrolling** in one list is one step; **typing** in one field is one step (off, character count, or the text).
- **Dialogs** that pop up become a step with their text.
- **Passwords** are never recorded, and password fields are blurred in every screenshot. Apps that block screenshots
  (banking apps, for example) give a step without a picture.
- Telestep's own floating button is blurred out of the screenshots.

## Install

1. Get the APK: the **Android** workflow on GitHub builds it on every change (Actions > Android > the latest run >
   Artifacts > `telestep-android-debug`).
2. Copy it to the phone and open it; allow installing from that source when asked.
3. Open Telestep and tap **Turn on Telestep in Accessibility settings**, then switch on *Telestep step recorder*.
   If Android says the setting is restricted (Android 13 and newer, for apps installed from a file): open
   **Settings > Apps > Telestep**, tap **⋮ > Allow restricted settings**, and switch it on again.

## Record

- In the app, tap **Start recording** (or **Show floating button**, then tap the button: blue with a red dot).
  It turns red. Do the steps.
- Tap the floating button to stop. Press and hold it to pause and resume. Drag it anywhere.
- When not recording, press and hold the button to hide it. It never appears on its own (for example after a restart).

## Turn it off

Android keeps an accessibility service running while it is switched on, also after a restart. To switch Telestep off
completely, tap **Turn off Telestep** in the app (or switch it off in **Settings > Accessibility**). Turn it on again in
Accessibility settings next time. Telestep does not appear in the recent-apps switcher: the recorder is a service,
not an open screen.

## Open a recording on your PC

In the app, tap **Share** next to a recording and send the ZIP to your PC (mail, Drive, Nearby Share, USB). Unzip it
into Telestep's recordings folder (Settings > General > Save to, on the desktop toolbar), then click **Review** and pick it.
Everything in the review editor works: captions, comments, hiding areas, marks, and every export format.

## Build

```
cd android
./gradlew :app:assembleDebug        # needs the Android SDK (Android Studio, or ANDROID_HOME)
./gradlew :core:test -PcoreOnly=true   # the recorder logic only: any JDK 17+, no Android SDK
```

`core/` is plain Kotlin (session format, naming, captions, step merging, ZIP export) and has the unit tests.
`app/` is the Android part (accessibility service, screenshots, floating button, the app screen) and uses no
libraries beyond the Android framework.

## Limits

- No global hotkeys and no voice narration yet.
- An element with no text and no description is named by the text inside it or around it; some apps (games, apps
  drawn entirely on a canvas) expose nothing, and those taps are captioned "Tap on the screen".
- The picture for a tap is the last one taken when the screen was still; a tap within about a third of a second of
  the previous change can show the screen slightly earlier.
