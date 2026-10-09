"""Turn a document or a topic into a two-host AI podcast (script by the AI brain, voices by TTS)."""
from __future__ import annotations

import re
import time
from typing import Callable

import numpy as np

from .. import paths
from . import ai, audio_io, library, tts

ProgressFn = Callable[[float, str], None]


def render(lines: list[tuple[str, str]], voices: dict[str, str], speed: float = 1.0,
           progress: ProgressFn | None = None) -> np.ndarray:
    progress = progress or (lambda f, m: None)
    sr = tts.OUT_SR
    parts = [np.zeros(int(0.4 * sr), np.float32)]
    prev = None
    for i, (who, text) in enumerate(lines):
        progress(i / max(1, len(lines)), f"Recording line {i + 1}/{len(lines)}")
        audio = tts.synth(text, voices[who], speed)
        gap = 0.18 if who != prev else 0.08
        parts += [np.zeros(int(gap * sr), np.float32), audio]
        prev = who
    parts.append(np.zeros(int(0.6 * sr), np.float32))
    return np.concatenate(parts)


def create(source_text: str, topic: str, style: str, minutes: int, host_a: str, host_b: str,
           voice_a: str, voice_b: str, title: str = "", progress: ProgressFn | None = None) -> library.Item:
    progress = progress or (lambda f, m: None)
    lines = ai.podcast_script(source_text, topic, style, minutes, host_a, host_b,
                              lambda f, m: progress(0.4 * f, m))
    audio = render(lines, {host_a: voice_a, host_b: voice_b}, 1.0, lambda f, m: progress(0.4 + 0.58 * f, m))
    name = title or topic or "Podcast"
    safe = re.sub(r"[^\w\- ]+", "", name)[:50].strip() or "Podcast"
    out = audio_io.save_audio(paths.sub("Podcasts") / f"{safe} {time.strftime('%Y%m%d-%H%M')}.mp3",
                              audio, tts.OUT_SR, fmt="mp3", mp3_bitrate=192)
    script = "\n".join(f"{w}: {t}" for w, t in lines)
    item = library.save(library.Item("podcast", name, script, "", extra={
        "audio": str(out), "style": style, "hosts": [host_a, host_b], "voices": [voice_a, voice_b],
        "duration": round(len(audio) / tts.OUT_SR, 1)}))
    progress(1.0, "Done")
    return item
