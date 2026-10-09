"""Audio loading / saving / resampling. Arrays are float32, shape (channels, samples)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

AUDIO_FILTER = "Audio files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.mp4 *.aiff *.aif *.opus *.wma);;All files (*)"


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def load_audio(path: str | Path, sr: int | None = None, mono: bool = False) -> tuple[np.ndarray, int]:
    path = str(path)
    try:
        data, file_sr = sf.read(path, dtype="float32", always_2d=True)
        audio = data.T
    except Exception:
        audio, file_sr = _load_with_ffmpeg(path)
    if mono and audio.shape[0] > 1:
        audio = audio.mean(axis=0, keepdims=True)
    if sr is not None and sr != file_sr:
        audio = resample(audio, file_sr, sr)
        file_sr = sr
    return np.ascontiguousarray(audio, dtype=np.float32), int(file_sr)


def _load_with_ffmpeg(path: str, sr: int = 44100) -> tuple[np.ndarray, int]:
    ff = _ffmpeg()
    if ff is None:
        raise RuntimeError(
            f"Cannot decode '{Path(path).name}'. Convert it to WAV/MP3/FLAC, "
            "or place ffmpeg.exe in the StemForge\\ffmpeg folder.")
    cmd = [ff, "-v", "error", "-i", path, "-f", "f32le", "-acodec", "pcm_f32le",
           "-ac", "2", "-ar", str(sr), "-"]
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    proc = subprocess.run(cmd, capture_output=True, creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore')[:400]}")
    audio = np.frombuffer(proc.stdout, dtype=np.float32).reshape(-1, 2).T.copy()
    return audio, sr


def resample(audio: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to:
        return audio
    g = gcd(int(sr_from), int(sr_to))
    up, down = sr_to // g, sr_from // g
    return resample_poly(audio, up, down, axis=-1).astype(np.float32)


def to_stereo(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        audio = audio[None]
    if audio.shape[0] == 1:
        return np.repeat(audio, 2, axis=0)
    return audio[:2]


def save_audio(path: str | Path, audio: np.ndarray, sr: int, fmt: str | None = None,
               mp3_bitrate: int = 320) -> Path:
    """Save (channels, samples) or (samples,) audio as wav/flac/mp3 (by extension)."""
    path = Path(path)
    if audio.ndim == 1:
        audio = audio[None]
    fmt = (fmt or path.suffix.lstrip(".") or "wav").lower()
    path = path.with_suffix("." + fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1.0:  # avoid clipping
        audio = audio / peak * 0.99
    if fmt == "mp3":
        import lameenc
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        if pcm.shape[0] > 2:
            pcm = pcm[:2]
        enc = lameenc.Encoder()
        enc.set_bit_rate(mp3_bitrate)
        enc.set_in_sample_rate(sr)
        enc.set_channels(pcm.shape[0])
        enc.set_quality(2)
        data = enc.encode(pcm.T.copy().tobytes()) + enc.flush()
        path.write_bytes(bytes(data))
    elif fmt == "flac":
        sf.write(str(path), audio.T, sr, subtype="PCM_24", format="FLAC")
    else:
        path = path.with_suffix(".wav")
        sf.write(str(path), audio.T, sr, subtype="PCM_24", format="WAV")
    return path
