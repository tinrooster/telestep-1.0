"""Microphone and playback on macOS and Linux through `sounddevice` (PortAudio): pip install sounddevice.

Without the package (or without PortAudio) voice recording is simply unavailable, as before.  On macOS playback uses
the built-in `afplay`, so it works even without sounddevice.  macOS asks once for microphone access (System Settings >
Privacy & Security > Microphone) the first time a recording starts."""
import subprocess
import sys
import threading
import wave

NAME = "sounddevice"
DEFAULT_NAME = "Default (System Settings)" if sys.platform == "darwin" else "Default (system setting)"
UNAVAILABLE = "voice recording needs the sounddevice package (pip install sounddevice)"
NEEDS = "needs sounddevice"  # short form, for a status line

_sd = False  # not tried yet; None = unavailable; else the module


def _lib():
    """sounddevice, imported on first use (it loads PortAudio, which can be missing or slow)."""
    global _sd
    if _sd is False:
        try:
            import sounddevice
            _sd = sounddevice
        except Exception:  # ImportError, or OSError when the PortAudio library is missing
            _sd = None
    return _sd


def available():
    return _lib() is not None


def list_devices():
    """[(index, name)] of the input devices PortAudio reports."""
    sd = _lib()
    if sd is None:
        return []
    try:
        return [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d.get("max_input_channels", 0) > 0]
    except Exception:
        return []


def device_id(name):
    """Device index for a saved name; None (the system default) for '' / the default label / a device that is gone."""
    if name and name != DEFAULT_NAME:
        for i, n in list_devices():
            if n == name:
                return i
    return None


def record(device, formats, on_open, on_chunk, stop):
    """Blocking.  Open the microphone named `device` ('' = default) in the first of `formats` [(rate, channels)] it
    accepts, call on_open(rate, channels), then on_chunk(bytes) with every ~100 ms of 16-bit PCM until `stop`
    (a threading.Event) is set.  Returns '' when it ran, or why the microphone could not be opened."""
    sd = _lib()
    if sd is None:
        return UNAVAILABLE
    dev = device_id(device)
    stream, err = None, "no microphone found"
    for rate, ch in formats:
        try:
            stream = sd.RawInputStream(samplerate=rate, channels=ch, dtype="int16", device=dev, blocksize=rate // 10)
            stream.start()
            break
        except Exception as e:
            err = str(e) or type(e).__name__
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            stream = None
    if stream is None:
        return err
    try:
        on_open(rate, ch)
        block = rate // 10
        while not stop.is_set():
            data, _overflowed = stream.read(block)  # waits for ~100 ms of audio
            on_chunk(bytes(data))
        return ""
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass


# ---- playback: one clip at a time, play() replaces whatever is playing
_player = None  # afplay process (macOS) or (thread, stop event) (sounddevice)
_lock = threading.Lock()


def can_play():
    return sys.platform == "darwin" or available()


def play(path):
    global _player
    stop_playing()
    try:
        if sys.platform == "darwin":
            proc = subprocess.Popen(["afplay", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with _lock:
                _player = proc
            return True
        sd = _lib()
        if sd is None:
            return False
        halt = threading.Event()
        t = threading.Thread(target=_play_sd, args=(sd, str(path), halt), name="telestep-play", daemon=True)
        with _lock:
            _player = (t, halt)
        t.start()
        return True
    except Exception:
        return False


def _play_sd(sd, path, halt):
    try:
        with wave.open(path, "rb") as w:
            rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            if width != 2:
                return
            with sd.RawOutputStream(samplerate=rate, channels=ch, dtype="int16") as out:
                while not halt.is_set():
                    frames = w.readframes(rate // 10)
                    if not frames:
                        break
                    out.write(frames)
    except Exception:
        pass


def stop_playing():
    global _player
    with _lock:
        p, _player = _player, None
    if p is None:
        return
    try:
        if isinstance(p, tuple):
            p[1].set()
        else:
            p.terminate()
    except Exception:
        pass
