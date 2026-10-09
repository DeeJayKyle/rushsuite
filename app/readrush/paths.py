"""Folders + settings for ReadRush.

    ReadRush/ (portable)  ReadRush.exe  runtime/  app/  models/  llm/  ffmpeg/  extension/
    Documents/ReadRush/   Library (documents, notes, meetings), Audio (exports, podcasts)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = APP_DIR.parent
ASSETS_DIR = APP_DIR / "assets"
MODELS_DIR = Path(os.environ.get("READRUSH_MODELS", ROOT_DIR / "models"))
LLM_DIR = ROOT_DIR / "llm"                       # llama-server.exe (llama.cpp)
FFMPEG_DIR = ROOT_DIR / "ffmpeg"
EXTENSION_DIR = ROOT_DIR / "extension"

KOKORO_DIR = MODELS_DIR / "kokoro"
PIPER_DIR = MODELS_DIR / "piper"
WHISPER_DIR = MODELS_DIR / "whisper"
GGUF_DIR = MODELS_DIR / "llm"
CLONE_DIR = MODELS_DIR / "cloned_voices"
TTS_HOME = MODELS_DIR / "tts"
HF_HOME = MODELS_DIR / "hf"


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def config_dir() -> Path:
    d = Path(os.environ.get("APPDATA") or (_home() / ".config")) / "ReadRush"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULTS = {
    "data_root": "",
    "voice": "kokoro:af_heart",
    "speed": 1.0,
    "reader_font_size": 17,
    "reader_theme": "Dark",         # Dark | Light | Sepia
    "skip_citations": True,
    "ai_mode": "Auto",              # Auto | Offline | Online
    "ai_provider": "Google Gemini",
    "ai_model": "",
    "ai_keys": {},                  # provider -> key (stored only on this PC)
    "ai_base_url": "",
    "local_model": "",              # path to a .gguf (empty = first in models/llm)
    "stt_model": "small",           # tiny | base | small | medium
    "stt_language": "auto",
    "dictation_hotkey": "<ctrl>+<alt>+<space>",
    "read_hotkey": "<ctrl>+<alt>+r",
    "dictation_polish": False,
    "dictation_enabled": True,
    "bridge_enabled": True,
}


class Settings(dict):
    path = config_dir() / "settings.json"

    def __init__(self):
        super().__init__({k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()})
        try:
            self.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass

    def save(self):
        try:
            self.path.write_text(json.dumps(self, indent=2), encoding="utf-8")
        except Exception:
            pass


settings = Settings()


def data_root() -> Path:
    p = Path(settings.get("data_root") or "")
    if not str(p) or str(p) == ".":
        docs = _home() / "Documents"
        p = (docs if docs.exists() else _home()) / "ReadRush"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sub(name: str) -> Path:
    d = data_root() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_environment() -> None:
    for d in (MODELS_DIR, KOKORO_DIR, PIPER_DIR, WHISPER_DIR, GGUF_DIR, CLONE_DIR, TTS_HOME, HF_HOME):
        d.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["TTS_HOME"] = str(TTS_HOME)
    os.environ["COQUI_TOS_AGREED"] = "1"
    ff = FFMPEG_DIR / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if ff.exists():
        os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")
