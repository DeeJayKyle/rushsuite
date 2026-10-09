"""Build-time downloads for PDFRush (run by build.ps1 with the bundled runtime).

  OCR:  RapidOCR (PaddleOCR models, bundled in the wheel - warmed up here)
  AI:   optional offline model, Qwen3-4B-Instruct GGUF (~2.5 GB) - only with  --ai
"""
from __future__ import annotations

import os
import shutil
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from pdfrush import paths  # noqa: E402

paths.setup_environment()

GGUF = [("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
        ("Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf"),
        ("bartowski/Qwen2.5-3B-Instruct-GGUF", "Qwen2.5-3B-Instruct-Q4_K_M.gguf")]


def ocr():
    from PIL import Image, ImageDraw

    from pdfrush.core import ocr as O
    if not O.available():
        raise RuntimeError("OCR package not installed")
    im = Image.new("RGB", (600, 120), "white")
    ImageDraw.Draw(im).text((20, 40), "PDFRush OCR warm-up 123", fill="black")
    O.recognize(im.resize((1200, 240)))
    print("  ✓ OCR models ready")


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


if __name__ == "__main__":
    os.environ.pop("HF_HUB_OFFLINE", None)
    print("Models folder:", paths.MODELS_DIR)
    print("Free disk:", round(shutil.disk_usage(paths.MODELS_DIR).free / 1e9, 1), "GB")
    jobs = [("OCR", ocr, False)]
    if "--ai" in sys.argv:
        jobs.append(("Offline AI model", llm_model, False))
    failed_essential = False
    for name, fn, essential in jobs:
        print(f"\n== {name}", flush=True)
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            print(f"  ✗ {name} failed: {e}", flush=True)
            failed_essential |= essential
    sys.exit(1 if failed_essential else 0)
