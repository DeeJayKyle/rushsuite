"""Build-time self test: every engine end-to-end on this PC.  runtime\\python.exe tools\\selftest.py"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from readrush import paths  # noqa: E402

paths.setup_environment()
import numpy as np  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="readrush_test_"))
results = []
SHARED = {}


class Skip(Exception):
    pass


def check(name):
    def deco(fn):
        t = time.time()
        try:
            fn()
            results.append((name, True, f"{time.time() - t:.1f}s"))
        except Skip as e:
            results.append((name, None, str(e)))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            results.append((name, False, str(e)[:200]))
        return fn
    return deco


@check("Imports (Qt, audio, PDF)")
def _imports():
    import lameenc  # noqa: F401
    import pypdfium2  # noqa: F401
    import PySide6.QtWidgets  # noqa: F401
    import sounddevice  # noqa: F401
    import soundfile  # noqa: F401


@check("Documents: text segmentation + DOCX/EPUB parsing")
def _docs():
    import zipfile

    from readrush.engines import docs, textproc
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(tmp / "a.docx", "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>Hello Dr. Smith. '
                   f'How are you?</w:t></w:r></w:p></w:body></w:document>')
    d = docs.from_file(str(tmp / "a.docx"))
    assert len(textproc.segment(d.text)) == 2, d.text


@check("Natural voice (Kokoro)")
def _kokoro():
    from readrush.engines import tts
    if not tts.ENGINES["kokoro"].available():
        raise RuntimeError("Kokoro voice files or kokoro-onnx missing")
    vid = next(v.id for v in tts.all_voices() if v.engine == "kokoro")
    t0 = time.time()
    a = tts.synth("Hello! This is ReadRush, reading your documents out loud.", vid, 1.0)
    dur = len(a) / tts.OUT_SR
    assert dur > 1.0, dur
    SHARED["speech"] = a
    print(f"     {dur:.1f}s of speech in {time.time() - t0:.1f}s ({dur / max(1e-3, time.time() - t0):.1f}x real time)")
    fast = tts.synth("Speed test at three times.", vid, 3.0)
    assert len(fast) > 1000


@check("Speech recognition (Whisper) - hears the Kokoro voice")
def _stt():
    from readrush.engines import audio_io, stt
    if not stt.available():
        raise RuntimeError("faster-whisper not installed")
    if "speech" not in SHARED:
        raise Skip("needs the voice test")
    a16 = audio_io.resample(SHARED["speech"], 24000, 16000)
    t0 = time.time()
    text = stt.transcribe(a16, language="en").lower()
    print(f"     heard: {text!r} ({time.time() - t0:.1f}s)")
    assert "readrush" in text.replace(" ", "") or "documents" in text or "reading" in text, text


@check("Scan & listen (OCR)")
def _ocr():
    from PIL import Image, ImageDraw, ImageFont

    from readrush.engines import ocr
    if not ocr.available():
        raise RuntimeError("RapidOCR not installed")
    img = Image.new("RGB", (900, 200), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("arial.ttf", 48)
    except Exception:
        f = ImageFont.load_default()
    d.text((30, 60), "Paracetamol 500 mg tablets", fill="black", font=f)
    text = ocr.image_to_text(img)
    print(f"     read: {text!r}")
    assert "paracetamol" in text.lower(), text


@check("Offline AI (llama.cpp + local model)")
def _llm():
    from readrush.engines import llm
    if not llm.LOCAL.available():
        raise RuntimeError("llama-server.exe or the .gguf model is missing")
    old = paths.settings.get("ai_mode")
    paths.settings["ai_mode"] = "Offline"
    try:
        t0 = time.time()
        r = llm.chat([{"role": "user", "content": "Reply with just the word OK."}], max_tokens=10)
        print(f"     replied {r!r} in {time.time() - t0:.1f}s (includes start-up)")
        assert r.strip()
    finally:
        paths.settings["ai_mode"] = old
        llm.LOCAL.stop()


@check("Extra voices (Piper engine)")
def _piper():
    if importlib.util.find_spec("piper") is None:
        raise Skip("piper-tts not installed (optional)")


@check("Browser extension bridge")
def _bridge():
    import json
    import urllib.request

    from readrush.engines import bridge, voice_input
    assert bridge.start(47999)
    req = urllib.request.Request("http://127.0.0.1:47999/read", data=json.dumps({"title": "T", "text": "Hi"}).encode(),
                                 headers={"Content-Type": "application/json"})
    assert urllib.request.urlopen(req, timeout=5).status == 200
    assert voice_input.events.get(timeout=2)[0] == "bridge_read"
    bridge.stop()


@check("User interface (all pages, off-screen)")
def _ui():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from readrush.ui.theme import STYLE
    app.setStyleSheet(STYLE)
    from readrush.engines import library
    it = library.Item("text", "Self-test", "First sentence. Second sentence!")
    from readrush.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    for k in w.pages:
        w.go(k)
        app.processEvents()
    w.pages["reader"].open_item(it, False)
    w.pages["reader"]._highlight(1, None)
    app.processEvents()
    w.grab().save(str(tmp / "ui.png"))
    w.dictation.stop_hotkeys()
    w.tray.hide()
    w.hide()


if __name__ == "__main__":
    print("\n================ ReadRush self-test ================")
    ok = True
    for name, passed, info in results:
        ok &= passed is not False
        tag = "SKIP" if passed is None else ("PASS" if passed else "FAIL")
        print(f"  [{tag}] {name}  ({info})")
    print("====================================================")
    os._exit(0 if ok else 1)
