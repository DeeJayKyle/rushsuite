"""Voices: Kokoro (natural, 8 languages, ~50 voices), Piper (100+ voices in 40+ languages,
installable from the Voices page) and your own cloned voice (XTTS, optional).

All engines return mono float32 audio at OUT_SR. Speeds the engine can't do natively are
reached with a pitch-preserving WSOLA time-stretch, so 3x still sounds like a person.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import paths
from . import audio_io

OUT_SR = 24000

KOKORO_LANG = {"a": ("en-us", "English (US)"), "b": ("en-gb", "English (UK)"), "e": ("es", "Spanish"),
               "f": ("fr-fr", "French"), "h": ("hi", "Hindi"), "i": ("it", "Italian"),
               "j": ("ja", "Japanese"), "p": ("pt-br", "Portuguese (BR)"), "z": ("cmn", "Chinese")}


@dataclass
class Voice:
    id: str            # engine:name
    name: str
    language: str
    gender: str
    engine: str
    note: str = ""

    @property
    def label(self) -> str:
        g = {"f": "♀", "m": "♂"}.get(self.gender, "")
        return f"{self.name} {g}  ·  {self.language}" + (f"  ·  {self.note}" if self.note else "")


# ===================================================================== time stretch (WSOLA)
def time_stretch(x: np.ndarray, rate: float, sr: int = OUT_SR) -> np.ndarray:
    """Speed up (rate>1) or slow down speech without changing pitch."""
    if abs(rate - 1.0) < 0.01 or len(x) < sr // 10:
        return x
    n = int(sr * 0.030)                 # 30 ms frames
    hs = n // 2                          # synthesis hop
    ha = hs * rate                       # analysis hop
    tol = int(sr * 0.008)
    win = np.hanning(n).astype(np.float32)
    out_len = int(len(x) / rate) + n
    y = np.zeros(out_len + n, np.float32)
    wsum = np.zeros_like(y)
    xp = np.pad(x.astype(np.float32), (tol, n + tol + int(ha) + 2))
    pos_in, pos_out, delta = 0.0, 0, 0
    prev_tail = None
    while pos_out + n < out_len and int(pos_in) + delta + n + tol < len(xp) - tol:
        a = int(pos_in) + tol
        if prev_tail is not None:
            seg = xp[a - tol: a + tol + n]
            # find the shift whose frame best continues the previous output (cross-correlation)
            corr = np.correlate(seg[: 2 * tol + hs], prev_tail, mode="valid")
            delta = int(np.argmax(corr)) - tol
        frame = xp[a + delta: a + delta + n]
        if len(frame) < n:
            break
        y[pos_out: pos_out + n] += frame * win
        wsum[pos_out: pos_out + n] += win
        prev_tail = xp[a + delta + hs: a + delta + hs + hs]
        if len(prev_tail) < hs:
            break
        pos_in += ha
        pos_out += hs
    wsum[wsum < 1e-3] = 1.0
    return (y / wsum)[: int(len(x) / rate)]


# ===================================================================== engines
class Kokoro:
    MAX_SPEED = 2.0

    def __init__(self):
        self.k = None
        self.lock = threading.Lock()

    @staticmethod
    def files() -> tuple[Path, Path]:
        d = paths.KOKORO_DIR
        model = next((p for p in (d / "kokoro-v1.0.onnx", d / "kokoro-v1.0.int8.onnx") if p.exists()),
                     d / "kokoro-v1.0.onnx")
        return model, d / "voices-v1.0.bin"

    def available(self) -> bool:
        import importlib.util
        m, v = self.files()
        return m.exists() and v.exists() and importlib.util.find_spec("kokoro_onnx") is not None

    def _load(self):
        if self.k is None:
            from kokoro_onnx import Kokoro as K
            m, v = self.files()
            self.k = K(str(m), str(v))
        return self.k

    def voices(self) -> list[Voice]:
        if not self.available():
            return []
        names = []
        try:          # read voice names straight from the voices file (fast, no model load)
            with np.load(str(self.files()[1])) as z:
                names = sorted(z.files)
        except Exception:
            try:
                names = sorted(self._load().get_voices())
            except Exception:
                return []
        out = []
        for n in names:
            lang = KOKORO_LANG.get(n[:1], ("en-us", "English"))[1]
            nice = n.split("_", 1)[-1].capitalize()
            out.append(Voice(f"kokoro:{n}", nice, lang, n[1:2], "kokoro", "natural"))
        best = {"af_heart": 0, "af_bella": 1, "bf_emma": 2, "am_michael": 3, "am_fenrir": 4, "bm_george": 5}
        out.sort(key=lambda v: (best.get(v.id.split(":")[1], 99), v.language, v.name))
        return out

    def synth(self, text: str, name: str, speed: float) -> tuple[np.ndarray, int]:
        k = self._load()
        lang = KOKORO_LANG.get(name[:1], ("en-us", ""))[0]
        with self.lock:
            audio, sr = k.create(text, voice=name, speed=float(np.clip(speed, 0.5, self.MAX_SPEED)), lang=lang)
        return np.asarray(audio, np.float32), int(sr)


class Piper:
    MAX_SPEED = 2.5

    def __init__(self):
        self.loaded: dict[str, object] = {}
        self.lock = threading.Lock()

    def available(self) -> bool:
        import importlib.util
        return importlib.util.find_spec("piper") is not None

    def voices(self) -> list[Voice]:
        out = []
        for onnx in sorted(paths.PIPER_DIR.rglob("*.onnx")):
            cfg = Path(str(onnx) + ".json")
            lang, name = "", onnx.stem
            try:
                c = json.loads(cfg.read_text(encoding="utf-8"))
                lang = c.get("language", {}).get("name_english", "") or c.get("language", {}).get("code", "")
                region = c.get("language", {}).get("country_english", "")
                lang = f"{lang} ({region})" if region else lang
            except Exception:
                pass
            m = re.match(r"([a-z]{2,3}_[A-Z]{2})-(.+)-(x_low|low|medium|high)", onnx.stem)
            if m:
                name = f"{m.group(2).replace('_', ' ').title()} ({m.group(3)})"
                lang = lang or m.group(1)
            out.append(Voice(f"piper:{onnx.stem}", name, lang or "?", "", "piper", "fast"))
        return out

    def _voice(self, name: str):
        if name not in self.loaded:
            from piper import PiperVoice
            onnx = next(paths.PIPER_DIR.rglob(f"{name}.onnx"))
            try:
                self.loaded[name] = PiperVoice.load(str(onnx))
            except TypeError:
                self.loaded[name] = PiperVoice.load(str(onnx), config_path=str(onnx) + ".json")
        return self.loaded[name]

    def synth(self, text: str, name: str, speed: float) -> tuple[np.ndarray, int]:
        v = self._voice(name)
        ls = 1.0 / float(np.clip(speed, 0.4, self.MAX_SPEED))
        with self.lock:
            try:                                  # piper-tts >= 1.3
                from piper import SynthesisConfig
                chunks = list(v.synthesize(text, syn_config=SynthesisConfig(length_scale=ls)))
                sr = chunks[0].sample_rate if chunks else 22050
                audio = np.concatenate([c.audio_float_array for c in chunks]) if chunks else np.zeros(1)
            except ImportError:                   # piper-tts 1.2
                raw = b"".join(v.synthesize_stream_raw(text, length_scale=ls))
                sr = v.config.sample_rate
                audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        return np.asarray(audio, np.float32), int(sr)


class Cloned:
    """Your own voice via XTTS v2 (optional component; slow on CPU)."""
    MAX_SPEED = 1.5

    def available(self) -> bool:
        import importlib.util
        return importlib.util.find_spec("TTS") is not None

    def voices(self) -> list[Voice]:
        if not self.available():
            return []
        return [Voice(f"clone:{d.name}", d.name, "Your voice", "", "clone", "cloned · slower")
                for d in sorted(paths.CLONE_DIR.iterdir()) if d.is_dir() and any(d.glob("ref_*.wav"))]

    def synth(self, text: str, name: str, speed: float) -> tuple[np.ndarray, int]:
        from . import voiceclone
        return voiceclone.speak(text, name, float(np.clip(speed, 0.7, self.MAX_SPEED))), voiceclone.SR


ENGINES = {"kokoro": Kokoro(), "piper": Piper(), "clone": Cloned()}


def all_voices() -> list[Voice]:
    out = []
    for e in ENGINES.values():
        try:
            out += e.voices()
        except Exception:
            continue
    return out


def default_voice() -> str:
    want = paths.settings.get("voice", "")
    vs = all_voices()
    if any(v.id == want for v in vs):
        return want
    return vs[0].id if vs else want


def synth(text: str, voice_id: str, speed: float = 1.0) -> np.ndarray:
    """Mono float32 at OUT_SR."""
    engine, _, name = voice_id.partition(":")
    eng = ENGINES.get(engine)
    if eng is None:
        raise ValueError(f"Unknown voice {voice_id}")
    native = min(speed, eng.MAX_SPEED) if speed >= 1 else max(speed, 0.5)
    audio, sr = eng.synth(text, name, native)
    if sr != OUT_SR:
        audio = audio_io.resample(audio, sr, OUT_SR)
    rest = speed / native
    if abs(rest - 1) > 0.02:
        audio = time_stretch(audio, rest)
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak > 0.98:
        audio = audio / peak * 0.95
    return audio.astype(np.float32)


# ===================================================================== Piper voice catalogue (online)
PIPER_CATALOG = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"


def piper_catalog() -> list[dict]:
    import urllib.request
    with urllib.request.urlopen(PIPER_CATALOG, timeout=30) as r:
        data = json.loads(r.read().decode())
    out = []
    for key, v in data.items():
        files = [f for f in v.get("files", {}) if f.endswith((".onnx", ".onnx.json"))]
        lang = v.get("language", {})
        out.append({"key": key, "name": v.get("name", key), "quality": v.get("quality", ""),
                    "language": f"{lang.get('name_english', '')} ({lang.get('country_english', '')})",
                    "files": files, "size_mb": round(sum(v["files"][f].get("size_bytes", 0) for f in files) / 1e6)})
    out.sort(key=lambda d: (d["language"], d["name"]))
    return out


def install_piper_voice(entry: dict, progress=None) -> Path:
    import urllib.request
    dest = paths.PIPER_DIR / entry["key"]
    dest.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(entry["files"]):
        if progress:
            progress(i / len(entry["files"]), f"Downloading {Path(f).name}")
        urllib.request.urlretrieve(PIPER_BASE + f, dest / Path(f).name)
    return dest
