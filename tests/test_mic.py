import os, sys, tempfile, threading, time, wave, struct, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The Narrator talks to the sound card only through telestep_platform.audio.record(); drive it with fakes.
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1
    else: bad += 1; print("FAIL:", name, extra)

import telestep_audio as au
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
loud = struct.pack("<h", 9000) * 1102 + struct.pack("<h", -9000) * 1103  # 100 ms at 11025 Hz, mono

class FakeMic:
    DEFAULT_NAME = "Default"; UNAVAILABLE = "no"
    def __init__(s, fail=""): s.fail, s.seen = fail, None
    def available(s): return True
    def record(s, device, formats, on_open, on_chunk, stop):
        s.seen = (device, formats[0])
        if s.fail: return s.fail
        on_open(*formats[0])
        while not stop.is_set():
            on_chunk(loud); time.sleep(0.01)
        return ""

fake = FakeMic(); au._mic = fake; au.available = fake.available
n = au.Narrator(device="USB mic")
check("start ok", n.start() == (True, ""), n._open_error)
time.sleep(0.15)
check("format from backend", n.format == (11025, 1) and fake.seen == ("USB mic", (11025, 1)))
check("level meter", n.level > 0.5, n.level)
n.pause(); time.sleep(0.05); kept = n._nbytes; time.sleep(0.05)
check("muted audio is dropped", n._nbytes == kept)
n.resume(); time.sleep(0.05)
out = tmp / "n.wav"
check("stop writes wav", n.stop(out) and out.exists())
with wave.open(str(out)) as w:
    check("wav format", (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (11025, 1, 2))
check("level reset after stop", n.level == 0.0)

bad_mic = FakeMic(fail="the device is in use by another program"); au._mic = bad_mic
ok_, msg = au.Narrator().start()
check("open failure reported", not ok_ and "in use" in msg, msg)

# --- the sounddevice backend, against a fake sounddevice module
class Stream:
    opened = []
    def __init__(s, samplerate, channels, dtype, device, blocksize):
        if samplerate == 11025: raise RuntimeError("Invalid sample rate")
        s.rate, s.ch = samplerate, channels; Stream.opened.append((samplerate, channels, device, blocksize))
        s.closed = False
    def start(s): pass
    def read(s, n): time.sleep(0.005); return (b"\x10\x00" * n * s.ch, False)
    def stop(s): pass
    def close(s): s.closed = True
sd = types.SimpleNamespace(RawInputStream=Stream,
                           query_devices=lambda: [{"name": "Speakers", "max_input_channels": 0},
                                                  {"name": "MacBook Pro Microphone", "max_input_channels": 1}])
from telestep_platform import _audio_sd as asd
asd._sd = sd
check("sd lists input devices only", asd.list_devices() == [(1, "MacBook Pro Microphone")])
check("sd device by name", asd.device_id("MacBook Pro Microphone") == 1 and asd.device_id("") is None
      and asd.device_id("Gone") is None)
stop = threading.Event(); got = []; fmt = []
t = threading.Thread(target=lambda: got.append(asd.record("MacBook Pro Microphone", au.Narrator.FORMATS,
                                                          lambda r, c: fmt.append((r, c)), got.append, stop)))
t.start(); time.sleep(0.1); stop.set(); t.join(2)
check("sd falls back to the next format", fmt == [(22050, 1)] and Stream.opened[0] == (22050, 1, 1, 2205), (fmt, Stream.opened))
check("sd delivers 100 ms chunks", len(got) > 2 and len(got[0]) == 2205 * 2 and got[-1] == "", [type(x) for x in got[-2:]])
asd._sd = None
check("sd unavailable", not asd.available() and asd.record("", [(11025, 1)], None, None, stop) == asd.UNAVAILABLE)
print(f"{ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
