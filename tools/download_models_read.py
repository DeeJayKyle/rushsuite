"""Download ReadRush's offline models into ReadRush/models (run once, with internet).

  voices:  Kokoro-82M (ONNX)                         ~340 MB   essential
  speech:  Whisper base + small (faster-whisper)     ~620 MB
  AI:      Qwen3-4B-Instruct (GGUF, Q4_K_M)          ~2.5 GB
  clone:   XTTS v2 (only with --clone)               ~1.9 GB
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from readrush import paths  # noqa: E402

paths.setup_environment()

KOKORO = [("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
           "kokoro-v1.0.onnx"),
          ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
           "voices-v1.0.bin")]
GGUF = [("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
        ("Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf"),
        ("bartowski/Qwen2.5-3B-Instruct-GGUF", "Qwen2.5-3B-Instruct-Q4_K_M.gguf")]


def fetch(url: str, dest: Path):
    if dest.exists() and dest.stat().st_size > 1000:
        print(f"  ✓ {dest.name} (already there)")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  ↓ {url}", flush=True)
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done, last = 0, -10
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and done * 100 // total >= last + 10:
                last = done * 100 // total
                print(f"    {last}%  ({done / 1e6:.0f} MB)", flush=True)
    tmp.replace(dest)


def kokoro():
    for url, name in KOKORO:
        fetch(url, paths.KOKORO_DIR / name)


def whisper():
    from faster_whisper import download_model
    for size in ("base", "small"):
        out = paths.WHISPER_DIR / size
        if (out / "model.bin").exists():
            print(f"  ✓ whisper {size} (already there)")
            continue
        print(f"  ↓ whisper {size}", flush=True)
        download_model(size, output_dir=str(out))


def llm_model():
    if any(paths.GGUF_DIR.glob("*.gguf")):
        print("  ✓ offline AI model already there")
        return
    from huggingface_hub import hf_hub_download
    last = None
    for repo, fname in GGUF:
        try:
            print(f"  ↓ {repo}/{fname} (~2.5 GB, be patient)", flush=True)
            p = hf_hub_download(repo, fname, local_dir=str(paths.GGUF_DIR))
            print("  ✓", p)
            return
        except Exception as e:  # noqa: BLE001
            last = e
            print("    not available:", e)
    raise RuntimeError(f"no offline AI model could be downloaded ({last})")


def xtts():
    from readrush.engines.voiceclone import XTTS_MODEL
    try:
        from TTS.utils.manage import ModelManager
        ModelManager(progress_bar=True).download_model(XTTS_MODEL)
    except Exception as e:  # noqa: BLE001
        print("ModelManager failed, trying TTS():", e)
        from TTS.api import TTS
        TTS(XTTS_MODEL)


if __name__ == "__main__":
    os.environ.pop("HF_HUB_OFFLINE", None)
    print("Models folder:", paths.MODELS_DIR)
    print("Free disk:", round(shutil.disk_usage(paths.MODELS_DIR).free / 1e9, 1), "GB")
    jobs = [("Kokoro voices", kokoro, True)]
    if importlib.util.find_spec("faster_whisper"):
        jobs.append(("Speech recognition (Whisper)", whisper, False))
    if "--no-llm" not in sys.argv:
        jobs.append(("Offline AI model", llm_model, False))
    if "--clone" in sys.argv and importlib.util.find_spec("TTS"):
        jobs.append(("Voice cloning model (XTTS v2)", xtts, False))
    fatal = False
    for name, fn, required in jobs:
        print(f"\n=== {name} ===", flush=True)
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            print("  FAILED:", e, flush=True)
            fatal |= required
    sys.exit(1 if fatal else 0)
