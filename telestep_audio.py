"""Voice narration for Telestep.  The sound card is driven by telestep_platform.audio (on Windows the winmm waveIn
recorder and winsound, nothing to install; on macOS / Linux the sounddevice package); cutting uses the standard `wave`
module.

Two uses:
  * Narrator running for a whole recording: you talk while you click, and when you stop the one long recording is
    cut into a short clip per step (what you said BEFORE a click goes with that click).  Muting (the mic button, or
    Pause) throws the audio away instead of keeping it.
  * Narrator for a single clip: record / replace the voice note of one step in the review window, or test the
    microphone in Settings (live level meter).

Everything that touches the sound card happens on one helper thread (Narrator._run), because Windows sound handles do
not like being driven from several threads (the earlier MCI version failed that way).
"""
import array
import datetime as dt
import sys
import threading
import wave
from pathlib import Path

import telestep_platform as plat

RATE = 11025  # speech only: 22 KB/s, about 1.3 MB per minute
LAST_ERROR = ""  # why the last cut_clips failed
MIN_SECONDS = 0.4  # shorter clips are dropped (a click and a cough)
SILENCE_PEAK = 150  # of 32767: a clip that never gets louder than this is room noise, not speech
preferred = ""  # microphone name chosen in Settings > Audio (the app keeps this up to date)

_mic = plat.audio
DEFAULT_NAME = _mic.DEFAULT_NAME
available = _mic.available
list_devices = _mic.list_devices  # [(id, name)] of the recording devices


class Narrator:
    """One microphone recording.  start() -> (ok, message); pause()/resume() mute; stop(path) saves a WAV;
    `level` is 0..1 (loudness of the last moment, for a meter)."""

    FORMATS = ((RATE, 1), (22050, 1), (44100, 1), (44100, 2))  # tried in turn: speech-sized first

    def __init__(self, device=None, raw=None):
        """raw = a file to stream the recording into as it goes (crash-safe; recover() can rescue it).  Without it the
        recording is kept in memory (fine for a short voice note or a test)."""
        self.device = preferred if device is None else device
        self.raw = Path(raw) if raw else None
        self._fh = None
        self._nbytes = 0
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
            return False, _mic.UNAVAILABLE
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
        try:
            err = _mic.record(self.device, self.FORMATS, self._on_open, self._on_chunk, self._stop)
            if err:
                self._open_error = err
        except Exception as e:
            self._open_error = self._open_error or f"{type(e).__name__}: {e}"
            self.error = self._open_error
        finally:
            self._opened.set()
            self.level = 0.0

    def _on_open(self, rate, ch):
        self.format = (rate, ch)
        self._opened.set()

    def _on_chunk(self, chunk):
        self.level = min(1.0, _peak(chunk, 2) / 12000.0)  # speech rarely peaks above ~12000
        if not self._muted:
            self._append(chunk)

    def _append(self, chunk):
        """Keep a chunk of audio: appended to the raw file on disk (flushed), or held in memory."""
        self._nbytes += len(chunk)
        if self.raw is None:
            self._data += chunk
            return
        try:
            if self._fh is None:
                self.raw.parent.mkdir(parents=True, exist_ok=True)
                self._fh = open(self.raw, "wb")
                rate, ch = self.format or (RATE, 1)
                Path(str(self.raw) + ".fmt").write_text(f"{rate} {ch}", encoding="ascii")
            self._fh.write(chunk)
            self._fh.flush()
        except OSError as e:
            self.error = f"could not write to disk: {e}"
            self.raw, self._data = None, bytearray(chunk)  # carry on in memory rather than lose the rest

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
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        if not self._nbytes:
            self.error = self.error or "the microphone delivered no audio"
            return False
        rate, ch = self.format or (RATE, 1)
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            if self.raw is not None and self.raw.exists():
                raw_to_wav(self.raw, rate, ch, path)
                self._drop_raw()
            else:
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(ch)
                    w.setsampwidth(2)
                    w.setframerate(rate)
                    w.writeframes(bytes(self._data))
        except OSError as e:
            self.error = f"could not write the file: {e}"
            return False
        return True

    def _drop_raw(self):
        for f in (self.raw, Path(str(self.raw) + ".fmt")):
            try:
                f.unlink()
            except OSError:
                pass

    def cancel(self):
        self.running = False
        self._stop.set()
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        if self.raw is not None:
            self._drop_raw()

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


# --------------------------------------------------------------------------------------- smart cutting
FRAME_S = 0.03  # energy is measured in 30 ms slices
BRIDGE_S = 0.40  # pauses shorter than this stay inside one utterance
MIN_UTTERANCE_S = 0.30  # shorter bursts are clicks and coughs, not speech
CLICK_TOL_S = 0.50  # a click this close to an utterance still belongs to it
PAD_S = 0.15  # breathing room kept around each utterance
JOIN_GAP_S = 0.25  # silence put between two utterances of the same step (long waits are cut out)
ASSIGN_MODES = ("next", "prev")


def _frame_energy(samples, ch, rate):
    """Mean absolute level of each 30 ms slice (list of floats)."""
    n = max(1, int(rate * FRAME_S)) * ch
    return [sum(map(abs, samples[i:i + n])) / max(1, len(samples[i:i + n])) for i in range(0, len(samples), n)]


def utterances(energy):
    """[(start_frame, end_frame)] runs of speech: loud frames, short pauses bridged, tiny bursts dropped."""
    if not energy:
        return []
    srt = sorted(energy)
    noise = srt[int(len(srt) * 0.10)]
    loud = srt[int(len(srt) * 0.95)]  # when you barely pause, the "quiet" 10% is speech: cap by the loud end
    thr = max(60.0, min(noise * 3.0, loud * 0.2))
    bridge = max(1, int(BRIDGE_S / FRAME_S))
    runs, start, last = [], None, None
    for i, e in enumerate(energy):
        if e >= thr:
            if start is None:
                start = i
            elif i - last > bridge:
                runs.append((start, last + 1))
                start = i
            last = i
    if start is not None:
        runs.append((start, last + 1))
    return [(a, b) for a, b in runs
            if (b - a) * FRAME_S >= MIN_UTTERANCE_S and max(energy[a:b]) >= 120]


def _quietest(energy, lo, hi):
    lo, hi = max(0, lo), min(len(energy), max(lo + 1, hi))
    return min(range(lo, hi), key=lambda i: energy[i]) if lo < len(energy) else lo


def assign_utterances(utts, energy, clicks, mode="next"):
    """Decide which click each piece of speech belongs to.
    utts: [(a, b)] in frames; clicks: [seconds] ascending.  Returns [(click_index, a, b)] pieces in frames.
    Rules: speech that overlaps (or nearly touches) a click goes with that click and is never cut at the click;
    speech in a gap goes with the NEXT click ('next': you announce what you are about to do) or the PREVIOUS one
    ('prev': you explain what just happened).  One long utterance spanning several clicks is cut at the quietest
    moment near each later click."""
    out, nclk = [], len(clicks)
    if not nclk:
        return out
    tol = CLICK_TOL_S / FRAME_S
    cf = [c / FRAME_S for c in clicks]
    for a, b in utts:
        inside = [k for k in range(nclk) if a - tol <= cf[k] <= b + tol]
        if not inside:
            if mode == "prev":
                before = [k for k in range(nclk) if cf[k] < a]
                k = before[-1] if before else 0
            else:
                after = [k for k in range(nclk) if cf[k] > b]
                k = after[0] if after else nclk - 1
            out.append((k, a, b))
        elif len(inside) == 1:
            out.append((inside[0], a, b))
        else:
            # window around each later click where the person most likely paused for breath
            back, fwd = (1.2, 0.4) if mode == "next" else (0.4, 1.2)
            cuts, prev = [a], a
            for k in inside[1:]:
                p = _quietest(energy, int(cf[k] - back / FRAME_S), int(cf[k] + fwd / FRAME_S))
                p = min(max(p, prev + 1), b - 1)
                cuts.append(p)
                prev = p
            cuts.append(b)
            for j, k in enumerate(inside):
                if cuts[j + 1] > cuts[j]:
                    out.append((k, cuts[j], cuts[j + 1]))
    return out


def smart_clips(wav_path, marks, out_dir, mode="next"):
    """Like cut_clips, but cuts at pauses in your speech instead of at the click times.  `marks` = [(name, click_seconds)]
    ascending.  Returns {name: filename} (steps with no speech get none); sets LAST_ERROR on failure."""
    global LAST_ERROR
    LAST_ERROR = ""
    out, out_dir = {}, Path(out_dir)
    try:
        with wave.open(str(wav_path), "rb") as w:
            rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
            frames = w.readframes(w.getnframes())
        if width != 2:
            LAST_ERROR = f"unsupported sample size ({width * 8}-bit)"
            return cut_clips(wav_path, marks, out_dir)
        samples = array.array("h")
        samples.frombytes(frames[: len(frames) // 2 * 2])
        if sys.byteorder == "big":
            samples.byteswap()
        energy = _frame_energy(samples, ch, rate)
        pieces = assign_utterances(utterances(energy), energy, [t for _n, t in marks], mode)
        per = {}
        fs = max(1, int(rate * FRAME_S))
        pad = int(PAD_S * rate)
        gap = array.array("h", [0] * (int(JOIN_GAP_S * rate) * ch))
        for k, a, b in pieces:
            lo = max(0, a * fs - pad) * ch
            hi = min(len(samples) // ch, b * fs + pad) * ch
            per.setdefault(k, []).append(samples[lo:hi])
        out_dir.mkdir(parents=True, exist_ok=True)
        for k, parts in per.items():
            clip = array.array("h")
            for i, part in enumerate(parts):
                if i:
                    clip.extend(gap)
                clip.extend(part)
            if len(clip) / ch / rate < MIN_SECONDS:
                continue
            if sys.byteorder == "big":
                clip.byteswap()
            name = marks[k][0]
            with wave.open(str(out_dir / f"{name}.wav"), "wb") as o:
                o.setnchannels(ch)
                o.setsampwidth(2)
                o.setframerate(rate)
                o.writeframes(clip.tobytes())
            out[name] = f"{name}.wav"
    except (OSError, wave.Error, EOFError) as e:
        LAST_ERROR = f"{type(e).__name__}: {e}"
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


def raw_to_wav(raw, rate, ch, dest):
    """Wrap a raw 16-bit PCM file in a WAV header (copied in pieces, so long recordings stay cheap)."""
    with open(raw, "rb") as src, wave.open(str(dest), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            w.writeframes(chunk[: len(chunk) // (2 * ch) * (2 * ch)])


def recover(session_dir):
    """Rescue the narration of a recording that was interrupted (crash, power cut): turns audio/narration.raw into
    audio/narration.wav.  Returns the wav path, or None when there is nothing to recover."""
    adir = Path(session_dir) / "audio"
    raw, fmt, wav = adir / "narration.raw", adir / "narration.raw.fmt", adir / "narration.wav"
    if not raw.exists():
        return None
    try:
        if raw.stat().st_size < 2000:
            raw.unlink()
            fmt.unlink(missing_ok=True)
            return None
        rate, ch = (int(x) for x in fmt.read_text(encoding="ascii").split()) if fmt.exists() else (RATE, 1)
        raw_to_wav(raw, rate, ch, wav)
        raw.unlink()
        fmt.unlink(missing_ok=True)
        return wav
    except (OSError, ValueError, wave.Error):
        return None


def recover_session(session, mode="next"):
    """If the recording was interrupted while narrating, rescue the audio and cut it into the steps' clips.
    Returns the number of clips made, or None when there was nothing to recover."""
    wav = recover(session.dir)
    if not wav:
        return None
    marks, last = [], 0.0
    for st in session.steps:
        if st.numbered and st.apos >= 0:
            last = max(last, st.apos)
            marks.append((st.id, last))
    made = 0
    if marks:
        for sid, fn in smart_clips(wav, marks, session.dir / "audio", mode).items():
            st = session.find(sid)
            if st:
                st.audio = f"audio/{fn}"
                made += 1
        session.save()
    return made


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
def can_play():
    return _mic.can_play()


def play(path):
    return _mic.play(path)


def stop_playing():
    _mic.stop_playing()
