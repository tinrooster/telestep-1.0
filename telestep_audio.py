"""Voice narration for Telestep: no extra packages, only what Windows already has (the winmm waveIn recorder,
winsound to play, the standard `wave` module to cut).

Two uses:
  * Narrator running for a whole recording: you talk while you click, and when you stop the one long recording is
    cut into a short clip per step (what you said BEFORE a click goes with that click).  Muting (the mic button, or
    Pause) throws the audio away instead of keeping it.
  * Narrator for a single clip: record / replace the voice note of one step in the review window, or test the
    microphone in Settings (live level meter).

Everything that touches the sound card happens on one helper thread, because Windows sound handles do not like
being driven from several threads (the earlier MCI version failed that way).
"""
import array
import datetime as dt
import sys
import threading
import time
import wave
from pathlib import Path

RATE = 11025  # speech only: 22 KB/s, about 1.3 MB per minute
LAST_ERROR = ""  # why the last cut_clips failed
MIN_SECONDS = 0.4  # shorter clips are dropped (a click and a cough)
SILENCE_PEAK = 150  # of 32767: a clip that never gets louder than this is room noise, not speech
WAVE_MAPPER = 0xFFFFFFFF  # "the Windows default recording device"
DEFAULT_NAME = "Default (Windows sound setting)"
preferred = ""  # microphone name chosen in Settings > Audio (the app keeps this up to date)

try:
    import ctypes
    from ctypes import wintypes
    _winmm = ctypes.WinDLL("winmm") if sys.platform == "win32" else None
except Exception:  # not Windows
    ctypes, wintypes, _winmm = None, None, None


def available():
    return _winmm is not None


if _winmm is not None:
    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                    ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD),
                    ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]

    class WAVEHDR(ctypes.Structure):
        _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                    ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t), ("dwFlags", wintypes.DWORD),
                    ("dwLoops", wintypes.DWORD), ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]

    class WAVEINCAPSW(ctypes.Structure):
        _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                    ("szPname", ctypes.c_wchar * 32), ("dwFormats", wintypes.DWORD), ("wChannels", wintypes.WORD),
                    ("wReserved1", wintypes.WORD)]

    _H = ctypes.c_void_p
    _winmm.waveInGetNumDevs.restype = wintypes.UINT
    _winmm.waveInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(WAVEINCAPSW), wintypes.UINT]
    _winmm.waveInOpen.argtypes = [ctypes.POINTER(_H), wintypes.UINT, ctypes.POINTER(WAVEFORMATEX),
                                  ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
    for _n in ("waveInPrepareHeader", "waveInUnprepareHeader", "waveInAddBuffer"):
        getattr(_winmm, _n).argtypes = [_H, ctypes.POINTER(WAVEHDR), wintypes.UINT]
    for _n in ("waveInStart", "waveInStop", "waveInReset", "waveInClose"):
        getattr(_winmm, _n).argtypes = [_H]
    _WHDR_DONE = 1


def _err_text(code):
    names = {2: "no such recording device", 4: "the device is in use by another program",
             6: "no driver", 7: "out of memory", 32: "the device does not support this format",
             64: "no microphone found"}
    return names.get(code, f"Windows audio error {code}")


def list_devices():
    """[(index, name)] of the recording devices Windows reports (names are cut at 31 characters by Windows)."""
    out = []
    if not available():
        return out
    try:
        for i in range(_winmm.waveInGetNumDevs()):
            caps = WAVEINCAPSW()
            if _winmm.waveInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                out.append((i, caps.szPname))
    except Exception:
        pass
    return out


def device_id(name):
    """Device number for a saved name ('' / the default label / a name that is gone -> the Windows default)."""
    if name and name != DEFAULT_NAME:
        for i, n in list_devices():
            if n == name:
                return i
    return WAVE_MAPPER


class Narrator:
    """One microphone recording.  start() -> (ok, message); pause()/resume() mute; stop(path) saves a WAV;
    `level` is 0..1 (loudness of the last moment, for a meter)."""

    FORMATS = ((RATE, 1), (22050, 1), (44100, 1), (44100, 2))  # tried in turn: speech-sized first

    def __init__(self, device=None):
        self.device = preferred if device is None else device
        self.start_dt = None
        self.pauses = []  # [(paused_at, resumed_at or None)]
        self.running = False
        self.error = ""  # last problem, for the diagnostic file
        self.level = 0.0
        self.format = None  # (rate, channels) actually opened
        self._muted = False
        self._data = bytearray()
        self._stop = threading.Event()
        self._opened = threading.Event()
        self._thread = None
        self._open_error = ""

    # ---- the microphone (all sound-card calls happen in _run)
    def start(self):
        if not available():
            return False, "voice recording needs Windows"
        self._thread = threading.Thread(target=self._run, name="telestep-mic", daemon=True)
        self._thread.start()
        self._opened.wait(6)
        if self._open_error or not self._opened.is_set():
            self._stop.set()
            return False, (self._open_error or "the microphone did not respond") + \
                " (is a microphone connected and allowed for desktop apps?)"
        self.start_dt, self.pauses, self.running = dt.datetime.now(), [], True
        return True, ""

    def _run(self):
        hwi, hdrs, bufs = _H(), [], []
        opened = False
        try:
            dev = device_id(self.device)
            code = None
            for rate, ch in self.FORMATS:
                fmt = WAVEFORMATEX(1, ch, rate, rate * 2 * ch, 2 * ch, 16, 0)
                code = _winmm.waveInOpen(ctypes.byref(hwi), dev, ctypes.byref(fmt), 0, 0, 0)
                if code == 0:
                    self.format, opened = (rate, ch), True
                    break
            if not opened:
                self._open_error = _err_text(code)
                return
            rate, ch = self.format
            size = rate * 2 * ch // 10  # 100 ms per buffer
            for _ in range(8):
                buf = ctypes.create_string_buffer(size)
                h = WAVEHDR(ctypes.cast(buf, ctypes.c_void_p), size, 0, 0, 0, 0, None, 0)
                bufs.append(buf)
                hdrs.append(h)
                _winmm.waveInPrepareHeader(hwi, ctypes.byref(h), ctypes.sizeof(h))
                _winmm.waveInAddBuffer(hwi, ctypes.byref(h), ctypes.sizeof(h))
            code = _winmm.waveInStart(hwi)
            if code:
                self._open_error = _err_text(code)
                return
            self._opened.set()
            while not self._stop.is_set():
                got = False
                for h, buf in zip(hdrs, bufs):
                    if h.dwFlags & _WHDR_DONE:
                        got = True
                        chunk = buf.raw[:h.dwBytesRecorded]
                        self.level = min(1.0, _peak(chunk, 2) / 12000.0)  # speech rarely peaks above ~12000
                        if not self._muted:
                            self._data += chunk
                        h.dwBytesRecorded = 0
                        _winmm.waveInAddBuffer(hwi, ctypes.byref(h), ctypes.sizeof(h))
                if not got:
                    time.sleep(0.02)
        except Exception as e:
            self._open_error = self._open_error or f"{type(e).__name__}: {e}"
            self.error = self._open_error
        finally:
            if opened:
                try:
                    _winmm.waveInStop(hwi)
                    _winmm.waveInReset(hwi)
                    for h in hdrs:
                        _winmm.waveInUnprepareHeader(hwi, ctypes.byref(h), ctypes.sizeof(h))
                    _winmm.waveInClose(hwi)
                except Exception:
                    pass
            self._opened.set()
            self.level = 0.0

    def pause(self):
        if self.running and not self._muted:
            self._muted = True
            self.pauses.append((dt.datetime.now(), None))

    def resume(self):
        if self.running and self._muted:
            self._muted = False
            if self.pauses and self.pauses[-1][1] is None:
                self.pauses[-1] = (self.pauses[-1][0], dt.datetime.now())

    def stop(self, path):
        """Stop and save as `path` (WAV).  Returns True when a file was written."""
        if not self.running:
            return False
        self.running = False
        self._stop.set()
        if self._thread:
            self._thread.join(3)
        if self.error and not self._data:
            return False
        if not self._data:
            self.error = "the microphone delivered no audio"
            return False
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            rate, ch = self.format or (RATE, 1)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(ch)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(bytes(self._data))
        except OSError as e:
            self.error = f"could not write the file: {e}"
            return False
        return True

    def cancel(self):
        self.running = False
        self._stop.set()

    # ---- where in the recording a moment falls
    def pos_at(self, when):
        """Seconds of recorded audio before `when` (a datetime), not counting muted time."""
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
    global LAST_ERROR
    LAST_ERROR = ""
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
    except (OSError, wave.Error, EOFError) as e:
        LAST_ERROR = f"{type(e).__name__}: {e}"
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


def describe(path):
    """'rate Hz, 16-bit, 2 ch, 12.3 s, peak 4000' for the diagnostic file (or why it can't be read)."""
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.readframes(w.getnframes())
            return (f"{w.getframerate()} Hz, {w.getsampwidth() * 8}-bit, {w.getnchannels()} ch, "
                    f"{w.getnframes() / float(w.getframerate()):.1f} s, peak {_peak(frames, w.getsampwidth())}")
    except Exception as e:
        return f"unreadable ({type(e).__name__}: {e})"


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
