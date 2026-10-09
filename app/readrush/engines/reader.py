"""Streaming read-aloud engine: synthesises a few sentences ahead while playing, and reports
exactly which sentence/word is being spoken for follow-along highlighting."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from . import textproc, tts

GAP_S = 0.12          # pause between sentences


@dataclass
class Segment:
    index: int
    audio: np.ndarray
    words: list       # [(t, char_start, char_end)]
    epoch: int


class StreamPlayer:
    def __init__(self, sr: int = tts.OUT_SR):
        self.sr = sr
        self.q: deque[Segment] = deque()
        self.cur: Segment | None = None
        self.pos = 0
        self.paused = True
        self.volume = 1.0
        self.lock = threading.Lock()
        self.stream = None
        self.underrun = False

    def _ensure(self):
        if self.stream is None:
            import sounddevice as sd
            self.stream = sd.OutputStream(samplerate=self.sr, channels=1, dtype="float32",
                                          blocksize=1024, callback=self._cb)
            self.stream.start()

    def _cb(self, out, frames, _t, _s):
        buf = np.zeros(frames, np.float32)
        with self.lock:
            if not self.paused:
                filled = 0
                while filled < frames:
                    if self.cur is None:
                        if not self.q:
                            self.underrun = True
                            break
                        self.cur, self.pos = self.q.popleft(), 0
                    a = self.cur.audio
                    take = min(frames - filled, len(a) - self.pos)
                    buf[filled: filled + take] = a[self.pos: self.pos + take]
                    filled += take
                    self.pos += take
                    if self.pos >= len(a):
                        self.cur = None
                buf *= self.volume
        out[:, 0] = buf

    def push(self, seg: Segment):
        with self.lock:
            self.q.append(seg)
            self.underrun = False

    def clear(self):
        with self.lock:
            self.q.clear()
            self.cur, self.pos = None, 0

    def play(self):
        self._ensure()
        self.paused = False

    def pause(self):
        self.paused = True

    def buffered(self) -> int:
        with self.lock:
            return len(self.q) + (1 if self.cur else 0)

    def position(self) -> tuple[int, float] | None:
        """(sentence index, seconds into it) of what is playing now."""
        with self.lock:
            if self.cur is None:
                return None
            return self.cur.index, self.pos / self.sr

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None


class Reader:
    """Read a document aloud from any sentence, at any speed and voice."""

    AHEAD = 3

    def __init__(self):
        self.player = StreamPlayer()
        self.sentences: list[textproc.Sentence] = []
        self.voice = tts.default_voice()
        self.speed = 1.0
        self.skip_citations = True
        self.epoch = 0
        self.next_index = 0
        self.last_index = 0
        self.error: str | None = None
        self.finished = False
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()

    # ------------------------------------------------------------ content
    def load(self, text: str):
        self.stop()
        self.sentences = textproc.segment(text)
        self.last_index = 0

    # ------------------------------------------------------------ transport
    @property
    def playing(self) -> bool:
        return not self.player.paused

    def play_from(self, index: int):
        if not self.sentences:
            return
        index = max(0, min(index, len(self.sentences) - 1))
        self.epoch += 1
        self.player.clear()
        self.next_index = index
        self.last_index = index
        self.finished = False
        self.error = None
        self.player.play()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._produce, daemon=True)
            self._thread.start()
        self._wake.set()

    def toggle(self):
        if self.playing:
            self.player.pause()
        elif self.player.buffered():
            self.player.play()
        else:
            self.play_from(self.last_index)

    def pause(self):
        self.player.pause()

    def stop(self):
        self.epoch += 1
        self.player.pause()
        self.player.clear()

    def skip(self, delta: int):
        self.play_from(self.current_index() + delta)

    def set_speed(self, speed: float):
        self.speed = speed
        if self.playing:
            self.play_from(self.current_index())

    def set_voice(self, voice_id: str):
        self.voice = voice_id
        if self.playing:
            self.play_from(self.current_index())

    def current_index(self) -> int:
        p = self.player.position()
        return p[0] if p else self.last_index

    def now(self) -> tuple[int, int, int] | None:
        """(sentence index, word char_start, word char_end) being spoken right now."""
        p = self.player.position()
        if p is None:
            return None
        idx, t = p
        self.last_index = idx
        seg = self.player.cur
        words = seg.words if seg else []
        cur = None
        for wt, a, b in words:
            if wt <= t:
                cur = (a, b)
            else:
                break
        if cur is None:
            s = self.sentences[idx]
            return idx, s.start, s.start
        return idx, cur[0], cur[1]

    def progress(self) -> float:
        return (self.current_index() + 1) / max(1, len(self.sentences))

    # ------------------------------------------------------------ producer
    def _produce(self):
        while True:
            epoch = self.epoch
            if self.next_index >= len(self.sentences):
                if self.player.buffered() == 0 and self.playing:
                    self.finished = True
                self._wake.wait(0.2)
                self._wake.clear()
                continue
            if self.player.buffered() >= self.AHEAD or self.player.paused and self.player.buffered() >= 1:
                self._wake.wait(0.05)
                self._wake.clear()
                continue
            idx = self.next_index
            s = self.sentences[idx]
            spoken = textproc.speakable(s.text, self.skip_citations)
            try:
                if spoken and any(ch.isalnum() for ch in spoken):
                    audio = tts.synth(spoken, self.voice, self.speed)
                else:
                    audio = np.zeros(int(tts.OUT_SR * 0.2), np.float32)
            except Exception as e:  # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"
                self.player.pause()
                self.epoch += 1
                time.sleep(0.3)
                continue
            if epoch != self.epoch:
                continue                       # user jumped/changed voice meanwhile
            dur = len(audio) / tts.OUT_SR
            audio = np.concatenate([audio, np.zeros(int(GAP_S * tts.OUT_SR), np.float32)])
            self.player.push(Segment(idx, audio, textproc.word_times(s, dur), epoch))
            self.next_index = idx + 1


def render_to_file(text: str, voice: str, speed: float, out_path, progress=None, skip_citations=True):
    """Export a whole document (or a podcast script line list) to an MP3/WAV audiobook."""
    from . import audio_io
    sents = textproc.segment(text)
    parts = []
    gap = np.zeros(int(GAP_S * tts.OUT_SR), np.float32)
    for i, s in enumerate(sents):
        if progress:
            progress(i / max(1, len(sents)), f"Recording sentence {i + 1}/{len(sents)}")
        spoken = textproc.speakable(s.text, skip_citations)
        if spoken and any(ch.isalnum() for ch in spoken):
            parts += [tts.synth(spoken, voice, speed), gap]
        if "\n" in text[s.end: s.end + 2]:
            parts.append(gap)
    audio = np.concatenate(parts) if parts else np.zeros(1, np.float32)
    return audio_io.save_audio(out_path, audio, tts.OUT_SR)
