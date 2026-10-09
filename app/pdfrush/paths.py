"""Folders + settings for PDFRush."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = APP_DIR.parent
ASSETS_DIR = APP_DIR / "assets"
MODELS_DIR = Path(os.environ.get("PDFRUSH_MODELS", ROOT_DIR / "models"))
LLM_DIR = ROOT_DIR / "llm"
GGUF_DIR = MODELS_DIR / "llm"
GS_DIR = ROOT_DIR / "ghostscript"


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def config_dir() -> Path:
    d = Path(os.environ.get("APPDATA") or (_home() / ".config")) / "PDFRush"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULTS = {
    "out_dir": "",                  # "" = Documents/PDFRush
    "save_next_to_input": False,
    "open_folder_after": True,
    "office_engine": "Auto",        # Auto | Microsoft Office | LibreOffice
    "ai_mode": "Auto",
    "ai_provider": "Google Gemini",
    "ai_model": "",
    "ai_keys": {},
    "ai_base_url": "",
    "local_model": "",
    "signatures": [],               # saved signature PNG paths
    "recent": [],
}


class Settings(dict):
    path = config_dir() / "settings.json"

    def __init__(self):
        super().__init__({k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in DEFAULTS.items()})
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


def out_dir() -> Path:
    p = Path(settings.get("out_dir") or "")
    if not str(p) or str(p) == ".":
        docs = _home() / "Documents"
        p = (docs if docs.exists() else _home()) / "PDFRush"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sub(name: str) -> Path:
    d = config_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def ghostscript() -> str | None:
    for name in ("gswin64c.exe", "gswin32c.exe", "gs"):
        if GS_DIR.exists():
            hit = next(iter(GS_DIR.rglob(name)), None)
            if hit:
                return str(hit)
    found = shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")
    if found:
        return found
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            if base and Path(base, "gs").exists():
                hits = sorted(Path(base, "gs").glob("gs*/bin/gswin64c.exe"))
                if hits:
                    return str(hits[-1])
    return None


def setup_environment() -> None:
    for d in (MODELS_DIR, GGUF_DIR):
        d.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(MODELS_DIR / "hf"))
