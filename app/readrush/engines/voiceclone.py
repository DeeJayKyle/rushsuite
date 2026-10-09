"""Speech voice cloning with Coqui XTTS v2 (zero-shot, 6-30 s of reference audio).

Speed-ups over the plain API: the voice "fingerprint" (conditioning latents) is computed
once per voice and cached on disk, so every further sentence/clip starts immediately.
Model licence: Coqui Public Model License (non-commercial use).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import time
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio_io
from .. import paths

XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
XTTS_SR = 24000
SR = XTTS_SR

LANGUAGES = {
    "English": "en", "Spanish": "es", "French": "fr", "German": "de", "Italian": "it",
    "Portuguese": "pt", "Polish": "pl", "Turkish": "tr", "Russian": "ru", "Dutch": "nl",
    "Czech": "cs", "Arabic": "ar", "Chinese": "zh-cn", "Japanese": "ja", "Hungarian": "hu",
    "Korean": "ko", "Hindi": "hi",
}

ProgressFn = Callable[[float, str], None]
_tts = None
_latent_cache: dict[str, tuple] = {}


def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("TTS") is not None


def _get_tts():
    global _tts
    if _tts is None:
        if not available():
            raise RuntimeError("The speech engine (XTTS) is not installed. Run build.bat again and send "
                               "build.log + the logs folder if it keeps failing.")
        import torch
        _patch_torchaudio_load()
        from TTS.api import TTS
        _tts = TTS(XTTS_MODEL, progress_bar=False)
        if torch.cuda.is_available():
            _tts = _tts.to("cuda")
    return _tts


def _patch_torchaudio_load():
    """Load reference audio with soundfile (avoids torchaudio backend / torchcodec issues)."""
    try:
        import soundfile as sf
        import torch
        import torchaudio

        def _load(path, *args, **kwargs):
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
            return torch.from_numpy(data.T.copy()), sr

        torchaudio.load = _load
    except Exception:
        pass


# ------------------------------------------------------------------ saved voices
def list_voices() -> list[str]:
    return sorted(p.name for p in paths.CLONE_DIR.iterdir()
                  if p.is_dir() and any(p.glob("ref_*.wav")))


def voice_refs(name: str) -> list[str]:
    return [str(p) for p in sorted((paths.CLONE_DIR / name).glob("ref_*.wav"))]


def save_voice(name: str, files: list[str]) -> Path:
    name = re.sub(r'[\\/:*?"<>|]+', "", name).strip() or "My voice"
    d = paths.CLONE_DIR / name
    if d.exists():
        shutil.rmtree(d)
    _prepare_reference(files, d)
    return d


def delete_voice(name: str) -> None:
    shutil.rmtree(paths.CLONE_DIR / name, ignore_errors=True)


def _prepare_reference(files: list[str], workdir: Path) -> list[str]:
    """Clean 24 kHz mono wav, silence-trimmed, max 30 s each."""
    out = []
    workdir.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(files):
        audio, _ = audio_io.load_audio(p, sr=XTTS_SR, mono=True)
        a = audio[0]
        env = np.abs(a)
        idx = np.nonzero(env > 0.02 * (env.max() + 1e-9))[0]
        if idx.size:
            a = a[idx[0]: idx[-1] + 1]
        a = a[: XTTS_SR * 30]
        dst = workdir / f"ref_{i}.wav"
        audio_io.save_audio(dst, a, XTTS_SR, fmt="wav")
        out.append(str(dst))
    return out


def _key(refs: list[str]) -> str:
    h = hashlib.sha1()
    for r in refs:
        p = Path(r)
        h.update(f"{p.resolve()}|{p.stat().st_size}|{p.stat().st_mtime}".encode())
    return h.hexdigest()


def _latents(tts, refs: list[str]):
    """(gpt_cond_latent, speaker_embedding), memory + disk cached."""
    import torch
    k = _key(refs)
    if k in _latent_cache:
        return _latent_cache[k]
    cache_file = Path(refs[0]).parent / f"latents_{k[:12]}.pt"
    if cache_file.exists():
        try:
            lat = torch.load(cache_file, map_location="cpu")
            _latent_cache[k] = (lat["gpt"], lat["spk"])
            return _latent_cache[k]
        except Exception:
            pass
    model = tts.synthesizer.tts_model
    gpt, spk = model.get_conditioning_latents(audio_path=refs)
    try:
        torch.save({"gpt": gpt.cpu(), "spk": spk.cpu()}, cache_file)
    except Exception:
        pass
    _latent_cache[k] = (gpt, spk)
    return gpt, spk


def split_text(text: str, max_chars: int = 220) -> list[str]:
    sents = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    chunks, cur = [], ""
    for s in sents:
        if len(cur) + len(s) + 1 <= max_chars:
            cur = f"{cur} {s}".strip()
        else:
            if cur:
                chunks.append(cur)
            while len(s) > max_chars:
                cut = max(s.rfind(",", 0, max_chars), s.rfind(" ", 0, max_chars))
                cut = cut if cut > 20 else max_chars
                chunks.append(s[:cut].strip())
                s = s[cut:].strip(" ,")
            cur = s
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c]


def _speak(tts, text: str, refs: list[str], lang: str, speed: float, temperature: float) -> np.ndarray:
    import torch
    try:  # fast path: cached latents + direct model inference
        gpt, spk = _latents(tts, refs)
        model = tts.synthesizer.tts_model
        dev = next(model.parameters()).device
        with torch.inference_mode():
            out = model.inference(text, lang, gpt.to(dev), spk.to(dev), temperature=temperature,
                                  speed=speed, enable_text_splitting=False)
        wav = out["wav"]
        return (wav.cpu().numpy() if hasattr(wav, "cpu") else np.asarray(wav)).astype(np.float32)
    except Exception:
        try:
            wav = tts.tts(text=text, speaker_wav=refs, language=lang, speed=speed,
                          temperature=temperature, split_sentences=False)
        except TypeError:
            wav = tts.tts(text=text, speaker_wav=refs, language=lang)
        return np.asarray(wav, dtype=np.float32)


def synthesize(text: str, refs: list[str], language: str, out_path: str | Path, speed: float = 1.0,
               temperature: float = 0.7, fmt: str = "wav", progress: ProgressFn | None = None) -> Path:
    progress = progress or (lambda f, m: None)
    if not text.strip():
        raise ValueError("Type some text to speak.")
    if not refs:
        raise ValueError("Choose a voice (or add a reference recording) first.")
    progress(0.02, "Loading XTTS (first time ~30 s)")
    tts = _get_tts()
    progress(0.08, "Learning the voice")
    chunks = split_text(text)
    gap = np.zeros(int(0.15 * XTTS_SR), dtype=np.float32)
    pieces = []
    for i, c in enumerate(chunks):
        progress(0.1 + 0.88 * i / len(chunks), f"Speaking part {i + 1}/{len(chunks)}")
        pieces += [_speak(tts, c, refs, language, speed, temperature), gap]
    audio = np.concatenate(pieces) if pieces else np.zeros(1, np.float32)
    progress(1.0, "Done")
    return audio_io.save_audio(out_path, audio, XTTS_SR, fmt=fmt)


def synthesize_batch(lines: list[str], refs: list[str], language: str, out_dir: str | Path,
                     speed: float = 1.0, temperature: float = 0.7, fmt: str = "wav", prefix: str = "clip",
                     progress: ProgressFn | None = None) -> list[Path]:
    """One audio file per non-empty line (DJ drops, intros, adverts...)."""
    progress = progress or (lambda f, m: None)
    lines = [ln.strip() for ln in lines if ln.strip()]
    out_dir = Path(out_dir)
    stamp = time.strftime("%H%M%S")
    results = []
    for i, line in enumerate(lines):
        safe = re.sub(r"[^\w\- ]+", "", line)[:40].strip().replace(" ", "_") or "line"
        dst = out_dir / f"{prefix}_{i + 1:02d}_{safe}_{stamp}.{fmt}"
        sub = (lambda f, m, i=i: progress((i + f) / len(lines), f"Clip {i + 1}/{len(lines)}: {m}"))
        results.append(synthesize(line, refs, language, dst, speed, temperature, fmt, sub))
    progress(1.0, "Done")
    return results


def speak(text: str, name: str, speed: float = 1.0, language: str = "en") -> np.ndarray:
    """One sentence/paragraph in a cloned voice (used by the reader)."""
    tts = _get_tts()
    refs = voice_refs(name)
    if not refs:
        raise RuntimeError(f"Cloned voice '{name}' has no recordings")
    return _speak(tts, text, refs, language, speed, 0.7)
