"""Windows microphone and playback: the winmm waveIn recorder and winsound (nothing to install).

Every waveIn call for one recording happens in record(), on the caller's thread, because Windows sound handles do not
like being driven from several threads (an earlier MCI version failed that way)."""
import ctypes
import time
from ctypes import wintypes

NAME = "winmm"
DEFAULT_NAME = "Default (Windows sound setting)"
UNAVAILABLE = "voice recording needs Windows"
WAVE_MAPPER = 0xFFFFFFFF  # "the Windows default recording device"

try:
    _winmm = ctypes.WinDLL("winmm")
except Exception:
    _winmm = None


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


def record(device, formats, on_open, on_chunk, stop):
    """Blocking.  Open the microphone named `device` ('' = default) in the first of `formats` [(rate, channels)] it
    accepts, call on_open(rate, channels), then on_chunk(bytes) with every ~100 ms of 16-bit PCM until `stop`
    (a threading.Event) is set.  Returns '' when it ran, or why the microphone could not be opened."""
    hwi, hdrs, bufs = _H(), [], []
    opened = False
    try:
        dev = device_id(device)
        code = None
        for rate, ch in formats:
            fmt = WAVEFORMATEX(1, ch, rate, rate * 2 * ch, 2 * ch, 16, 0)
            code = _winmm.waveInOpen(ctypes.byref(hwi), dev, ctypes.byref(fmt), 0, 0, 0)
            if code == 0:
                opened = True
                break
        if not opened:
            return _err_text(code)
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
            return _err_text(code)
        on_open(rate, ch)
        while not stop.is_set():
            got = False
            for h, buf in zip(hdrs, bufs):
                if h.dwFlags & _WHDR_DONE:
                    got = True
                    on_chunk(buf.raw[:h.dwBytesRecorded])
                    h.dwBytesRecorded = 0
                    _winmm.waveInAddBuffer(hwi, ctypes.byref(h), ctypes.sizeof(h))
            if not got:
                time.sleep(0.02)
        return ""
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


# ---- playback
def can_play():
    return True


def play(path):
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True
    except Exception:
        return False


def stop_playing():
    try:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
