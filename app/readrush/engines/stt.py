"""Speech to text with faster-whisper (Whisper on CTranslate2, int8 on CPU - fast & offline)."""
from __future__ import annotations

import threading
from typing import Callable

import numpy as np

from .. import paths

SIZES = {"tiny": "fastest", "base": "fast", "small": "balanced (recommended)", "medium": "most accurate, slow"}
_model = None
_name = None
_lock = threading.Lock()


def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("faster_whisper") is not None


def _load():
    global _model, _name
    size = paths.settings.get("stt_model", "small")
    if _model is not None and _name == size:
        return _model
    if not available():
        raise RuntimeError("Speech recognition (faster-whisper) isn't installed - run build.bat again.")
    from faster_whisper import WhisperModel
    local = paths.WHISPER_DIR / size
    src = str(local) if (local / "model.bin").exists() else size
    device = "cpu"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device = "cuda"
    except Exception:
        pass
    import os
    _model = WhisperModel(src, device=device, compute_type="int8" if device == "cpu" else "float16",
                          cpu_threads=max(1, (os.cpu_count() or 4) - 1), download_root=str(paths.WHISPER_DIR))
    _name = size
    return _model


def preload():
    with _lock:
        _load()


def transcribe(audio16k: np.ndarray, language: str | None = None, timestamps: bool = False,
               progress: Callable[[float, str], None] | None = None, fast: bool = True):
    """Return text, or (text, [(start, end, text)]) when timestamps=True."""
    lang = language or paths.settings.get("stt_language", "auto")
    lang = None if lang in (None, "", "auto") else lang
    with _lock:
        m = _load()
        segs, info = m.transcribe(audio16k.astype(np.float32), language=lang, vad_filter=True,
                                  beam_size=1 if fast else 5, condition_on_previous_text=not fast)
        total = max(1e-6, info.duration)
        out = []
        for s in segs:
            out.append((s.start, s.end, s.text.strip()))
            if progress:
                progress(min(0.99, s.end / total), f"Transcribing {int(s.end // 60)}:{int(s.end % 60):02d}")
    text = " ".join(t for _, _, t in out).strip()
    return (text, out) if timestamps else text
