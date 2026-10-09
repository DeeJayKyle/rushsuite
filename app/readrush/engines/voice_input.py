"""Microphone input: Voice Typing anywhere (global hotkey -> speak -> text appears in the app you
were typing in), read-selection hotkey, and the meeting recorder (mic + computer audio).

Background threads never touch the UI; they post events to `events` (a queue) that the UI polls."""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import numpy as np

from .. import paths
from . import audio_io, textproc

SR = 16000
events: "queue.Queue[tuple]" = queue.Queue()


def post(*ev):
    events.put(ev)


class MicRecorder:
    def __init__(self, sr: int = SR):
        self.sr = sr
        self.chunks: list[np.ndarray] = []
        self.stream = None
        self.level = 0.0

    def _cb(self, indata, frames, _t, _s):
        x = indata[:, 0].copy()
        self.chunks.append(x)
        self.level = float(np.sqrt(np.mean(x ** 2)) if len(x) else 0.0)

    def start(self):
        import sounddevice as sd
        self.chunks = []
        self.stream = sd.InputStream(samplerate=self.sr, channels=1, dtype="float32", callback=self._cb,
                                     blocksize=1600)
        self.stream.start()

    def stop(self) -> np.ndarray:
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)


# ===================================================================== Voice Typing
class Dictation:
    """Toggle with the global hotkey; the UI pastes the final text into the active app."""

    def __init__(self):
        self.rec = MicRecorder()
        self.recording = False
        self.busy = False
        self.listener = None
        self.t0 = 0.0

    def start_hotkeys(self):
        self.stop_hotkeys()
        try:
            from pynput import keyboard
        except Exception as e:  # noqa: BLE001
            post("error", f"Global hotkeys unavailable: {e}")
            return False
        s = paths.settings
        mapping = {}
        if s.get("dictation_enabled", True):
            mapping[s.get("dictation_hotkey", "<ctrl>+<alt>+<space>")] = self.toggle
        mapping[s.get("read_hotkey", "<ctrl>+<alt>+r")] = lambda: post("read_selection")
        try:
            self.listener = keyboard.GlobalHotKeys(mapping)
            self.listener.daemon = True
            self.listener.start()
            return True
        except Exception as e:  # noqa: BLE001
            post("error", f"Couldn't register hotkeys ({e}). Try another combination in Settings.")
            return False

    def stop_hotkeys(self):
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None

    def toggle(self):
        if self.busy:
            return
        if not self.recording:
            try:
                self.rec.start()
            except Exception as e:  # noqa: BLE001
                post("error", f"Microphone error: {e}")
                return
            self.recording, self.t0 = True, time.time()
            post("dictation_state", "listening")
        else:
            self.recording = False
            audio = self.rec.stop()
            self.busy = True
            post("dictation_state", "transcribing")
            threading.Thread(target=self._finish, args=(audio,), daemon=True).start()

    def _finish(self, audio: np.ndarray):
        try:
            if len(audio) < SR * 0.3:
                post("dictation_state", "idle")
                return
            from . import stt
            raw = stt.transcribe(audio)
            text = textproc.clean_dictation(raw) if raw.strip() else ""
            if text and paths.settings.get("dictation_polish"):
                try:
                    from . import ai
                    text = ai.polish_dictation(text) or text
                except Exception:
                    pass
            post("dictation_text", text, raw)
        except Exception as e:  # noqa: BLE001
            post("error", f"Voice typing failed: {e}")
        finally:
            self.busy = False
            post("dictation_state", "idle")


def paste_text(text: str, set_clipboard) -> None:
    """Type text into whichever app has focus: put it on the clipboard and press Ctrl+V."""
    from pynput.keyboard import Controller, Key
    set_clipboard(text)
    kb = Controller()
    for k in (Key.ctrl, Key.alt, Key.shift, Key.cmd):     # make sure hotkey modifiers are up
        try:
            kb.release(k)
        except Exception:
            pass
    time.sleep(0.08)
    with kb.pressed(Key.ctrl):
        kb.press("v")
        kb.release("v")


def copy_selection() -> None:
    from pynput.keyboard import Controller, Key
    kb = Controller()
    for k in (Key.ctrl, Key.alt, Key.shift):
        try:
            kb.release(k)
        except Exception:
            pass
    time.sleep(0.05)
    with kb.pressed(Key.ctrl):
        kb.press("c")
        kb.release("c")


# ===================================================================== Meetings
class MeetingRecorder:
    """Records your microphone and (optionally) everything your computer plays - e.g. the other
    people in a Zoom/Meet/Teams call - into one track."""

    def __init__(self):
        self.mic = MicRecorder()
        self.sys_chunks: list[np.ndarray] = []
        self.sys_thread = None
        self.running = False
        self.t0 = 0.0
        self.sys_error = ""
        self.sys_level = 0.0

    @property
    def level(self) -> float:
        return max(self.mic.level, self.sys_level)

    def start(self, include_system: bool):
        self.sys_chunks, self.sys_error = [], ""
        self.mic.start()
        self.running, self.t0 = True, time.time()
        if include_system:
            self.sys_thread = threading.Thread(target=self._loopback, daemon=True)
            self.sys_thread.start()

    def _loopback(self):
        try:
            import soundcard as sc
            spk = sc.default_speaker()
            dev = sc.get_microphone(id=str(spk.name), include_loopback=True)
            with dev.recorder(samplerate=48000, channels=2, blocksize=4800) as r:
                while self.running:
                    d = r.record(numframes=4800).mean(axis=1).astype(np.float32)
                    self.sys_chunks.append(d)
                    self.sys_level = float(np.sqrt(np.mean(d ** 2)))
        except Exception as e:  # noqa: BLE001
            self.sys_error = str(e)

    def elapsed(self) -> float:
        return time.time() - self.t0 if self.running else 0.0

    def stop(self) -> Path:
        self.running = False
        mic = self.mic.stop()
        if self.sys_thread:
            self.sys_thread.join(timeout=2)
        mix = mic
        if self.sys_chunks:
            sysa = audio_io.resample(np.concatenate(self.sys_chunks), 48000, SR)
            n = max(len(mic), len(sysa))
            mix = np.zeros(n, np.float32)
            mix[: len(mic)] += mic
            mix[: len(sysa)] += sysa * 0.9
        peak = float(np.abs(mix).max()) if mix.size else 0
        if peak > 0:
            mix = mix / peak * 0.9
        out = paths.sub("Meetings") / f"Meeting {time.strftime('%Y-%m-%d %H-%M')}.wav"
        return audio_io.save_audio(out, mix, SR, fmt="wav")


def process_meeting(audio_path: str, title: str = "", progress=None):
    """Transcribe + AI notes -> library item."""
    from . import ai, library, stt
    progress = progress or (lambda f, m: None)
    a, _ = audio_io.load_audio(audio_path, sr=SR, mono=True)
    dur = len(a[0]) / SR
    progress(0.02, "Transcribing")
    text, segs = stt.transcribe(a[0], timestamps=True, fast=False,
                                progress=lambda f, m: progress(0.02 + 0.6 * f, m))
    transcript = "\n".join(f"[{int(s // 60):02d}:{int(s % 60):02d}] {t}" for s, _e, t in segs)
    notes = ""
    if text.strip():
        try:
            notes = ai.meeting_notes(transcript, lambda f, m: progress(0.62 + 0.36 * f, m))
        except Exception as e:  # noqa: BLE001
            notes = f"(AI notes unavailable: {e})"
    item = library.save(library.Item("meeting", title or Path(audio_path).stem, transcript or "(no speech found)",
                                     audio_path, extra={"notes": notes, "audio": audio_path,
                                                        "duration": round(dur, 1)}))
    progress(1.0, "Done")
    return item
