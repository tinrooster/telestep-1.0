"""Voice narration for Telestep: no extra packages, only what Windows already has (the winmm MCI recorder to
record, winsound to play, the standard `wave` module to cut).

Two uses:
  * Narrator running for a whole recording: you talk while you click, and when you stop the one long recording is
    cut into a short clip per step (what you said BEFORE a click goes with that click).  Pausing the recording
    pauses the microphone too.
  * Narrator for a single clip: record / replace the voice note of one step in the review window.
"""
import array
import datetime as dt
import sys
import wave
from pathlib import Path

RATE = 11025  # speech only: 22 KB/s, about 1.3 MB per minute
MIN_SECONDS = 0.4  # shorter clips are dropped (a click and a cough)
SILENCE_PEAK = 400  # of 32767: a clip that never gets louder than this is room noise, not speech

try:
    import ctypes
    _winmm = ctypes.windll.winmm if sys.platform == "win32" else None
except Exception:  # not Windows
    ctypes, _winmm = None, None


def available():
    return _winmm is not None


def _mci(cmd):
    """Send one MCI command.  Returns (ok, message)."""
    buf = ctypes.create_unicode_buffer(256)
    err = _winmm.mciSendStringW(cmd, buf, 255, 0)
    if err:
        msg = ctypes.create_unicode_buffer(256)
        _winmm.mciGetErrorStringW(err, msg, 255)
        return False, msg.value or f"MCI error {err}"
    return True, buf.value


class Narrator:
    """One microphone recording.  start() -> (ok, message); pause()/resume(); stop(path) saves a WAV."""

    def __init__(self, alias="telestep_mic"):
        self.alias = alias
        self.start_dt = None
        self.pauses = []  # [(paused_at, resumed_at or None)]
        self.running = False

    # ---- the microphone
    def start(self):
        if not available():
            return False, "voice recording needs Windows"
        a = self.alias
        _mci(f"close {a}")
        ok, msg = _mci(f"open new type waveaudio alias {a}")
        if not ok:
            return False, msg
        for cmd in (f"set {a} time format ms", f"set {a} bitspersample 16", f"set {a} channels 1",
                    f"set {a} samplespersec {RATE}", f"set {a} alignment 2", f"set {a} bytespersec {RATE * 2}"):
            _mci(cmd)  # a device that refuses a setting still records, in its own format
        ok, msg = _mci(f"record {a}")
        if not ok:
            _mci(f"close {a}")
            return False, msg + " (is a microphone connected and allowed for desktop apps?)"
        self.start_dt, self.pauses, self.running = dt.datetime.now(), [], True
        return True, ""

    def pause(self):
        if self.running and not (self.pauses and self.pauses[-1][1] is None):
            _mci(f"pause {self.alias}")
            self.pauses.append((dt.datetime.now(), None))

    def resume(self):
        if self.running and self.pauses and self.pauses[-1][1] is None:
            _mci(f"resume {self.alias}")
            self.pauses[-1] = (self.pauses[-1][0], dt.datetime.now())

    def stop(self, path):
        """Stop and save as `path` (WAV).  Returns True when a file was written."""
        if not self.running:
            return False
        self.running = False
        a = self.alias
        _mci(f"stop {a}")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        ok, _ = _mci(f'save {a} "{path}"')
        _mci(f"close {a}")
        return ok and Path(path).exists()

    def cancel(self):
        if self.running:
            self.running = False
            _mci(f"stop {self.alias}")
            _mci(f"close {self.alias}")

    # ---- where in the recording a moment falls
    def pos_at(self, when):
        """Seconds of recorded audio before `when` (a datetime), not counting paused time."""
        if not self.start_dt:
            return -1.0
        total = (when - self.start_dt).total_seconds()
        for a, b in self.pauses:
            end = b or when
            lo, hi = max(a, self.start_dt), min(end, when)
            if hi > lo:
                total -= (hi - lo).total_seconds()
        return max(0.0, total)


# --------------------------------------------------------------------------------------- cutting
def _peak(frames, width):
    if width != 2 or not frames:
        return 32767 if frames else 0
    data = array.array("h")
    data.frombytes(frames[: len(frames) // 2 * 2])
    if sys.byteorder == "big":
        data.byteswap()
    return max(max(data), -min(data)) if data else 0


def cut_clips(wav_path, marks, out_dir):
    """Cut one long recording into clips.  `marks` = [(name, end_seconds)] in order; clip i runs from the previous
    mark to its own, and the last clip also takes whatever was said after the final click.  Writes
    out_dir/<name>.wav for clips that hold speech and returns {name: filename}."""
    out, out_dir = {}, Path(out_dir)
    try:
        with wave.open(str(wav_path), "rb") as w:
            rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
            total = w.getnframes()
            prev = 0
            for i, (name, end_s) in enumerate(marks):
                end = total if i == len(marks) - 1 else min(total, max(prev, int(end_s * rate)))
                n = end - prev
                if n > 0:
                    w.setpos(prev)
                    frames = w.readframes(n)
                    if n / rate >= MIN_SECONDS and _peak(frames, width) >= SILENCE_PEAK:
                        out_dir.mkdir(parents=True, exist_ok=True)
                        with wave.open(str(out_dir / f"{name}.wav"), "wb") as o:
                            o.setnchannels(ch)
                            o.setsampwidth(width)
                            o.setframerate(rate)
                            o.writeframes(frames)
                        out[name] = f"{name}.wav"
                prev = max(prev, end)
    except (OSError, wave.Error, EOFError):
        return out
    return out


def join_clips(paths, dest):
    """Concatenate WAV files (same format) into `dest`.  Returns True on success."""
    try:
        with wave.open(str(dest), "wb") as o:
            for i, p in enumerate(paths):
                with wave.open(str(p), "rb") as w:
                    if i == 0:
                        o.setparams(w.getparams())
                    o.writeframes(w.readframes(w.getnframes()))
        return True
    except (OSError, wave.Error):
        return False


def duration(path):
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (OSError, wave.Error, ZeroDivisionError):
        return 0.0


# --------------------------------------------------------------------------------------- playback
def play(path):
    if sys.platform != "win32":
        return False
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True
    except Exception:
        return False


def stop_playing():
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
