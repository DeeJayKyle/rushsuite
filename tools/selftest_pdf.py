"""Build-time self test: runs every PDFRush tool end-to-end on this PC.
   runtime\\python.exe tools\\selftest.py"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from pdfrush import paths  # noqa: E402

paths.setup_environment()
from pdfrush.core import load_all  # noqa: E402
from pdfrush.core.registry import run_tool  # noqa: E402

TOOLS = load_all()
tmp = Path(tempfile.mkdtemp(prefix="pdfrush_test_"))
out = tmp / "out"
results = []


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


def make_samples():
    from PIL import Image, ImageDraw
    from reportlab.pdfgen import canvas
    a = tmp / "sample.pdf"
    c = canvas.Canvas(str(a))
    for p in range(3):
        c.setFont("Helvetica-Bold", 20)
        c.drawString(72, 760, f"Sample page {p + 1}")
        c.setFont("Helvetica", 11)
        for k in range(20):
            c.drawString(72, 720 - k * 16, f"Line {k + 1}: contact jane@example.com or +256 772 123456.")
        c.rect(72, 300, 200, 60)
        c.drawString(80, 330, "Name ____________________")
        c.showPage()
    c.save()
    b = tmp / "sample_v2.pdf"
    c = canvas.Canvas(str(b))
    c.drawString(72, 760, "Sample page 1 changed")
    c.showPage()
    c.save()
    img = tmp / "photo.jpg"
    im = Image.new("RGB", (1000, 1400), (235, 232, 225))
    ImageDraw.Draw(im).text((100, 100), "Scanned text 2026", fill="black")
    im.save(img, quality=90)
    return a, b, img


A, B, IMG = make_samples()


def run(tool, files, **params):
    r = run_tool(tool, files, out, params)
    assert r and all(Path(x).exists() and Path(x).stat().st_size > 0 for x in r), f"{tool} made no output"
    return r


@check("Qt user interface")
def _qt():
    from PySide6.QtWidgets import QApplication  # noqa: F401
    import PySide6.QtSvg  # noqa: F401


for tid, files, params in [
    ("merge", [A, B], {}), ("split", [A], {"mode": "Extract every page"}), ("rotate", [A], {}),
    ("remove_pages", [A], {"pages": "2"}), ("extract_pages", [A], {"pages": "1,3"}), ("compress", [A], {}),
    ("repair", [A], {}), ("pdfa", [A], {}), ("pdf_to_jpg", [A], {}), ("jpg_to_pdf", [IMG], {}),
    ("pdf_to_word", [A], {}), ("pdf_to_ppt", [A], {}), ("pdf_to_excel", [A], {}), ("pdf_to_markdown", [A], {}),
    ("pdf_to_text", [A], {}), ("watermark", [A], {"text": "TEST"}), ("page_numbers", [A], {}),
    ("crop", [A], {}), ("flatten", [A], {}), ("protect", [A], {"password": "x"}),
    ("redact", [A], {"terms": "jane@example.com"}), ("compare", [A, B], {}),
    ("ai_summarizer", [A], {"output": "Markdown (.md)"}),
]:
    check(TOOLS[tid].name)(lambda tid=tid, files=files, params=params: run(tid, files, **params))


@check("Unlock PDF")
def _unlock():
    p = run("protect", [A], password="secret")[0]
    run("unlock", [p], password="secret")


@check("Word to PDF (Office / LibreOffice)")
def _office():
    docx = run("pdf_to_word", [A])[0]
    try:
        run("word_to_pdf", [docx])
    except RuntimeError as e:
        if "LibreOffice" in str(e):
            raise Skip("no Microsoft Office or LibreOffice installed") from None
        raise


@check("HTML to PDF (Edge/Chrome)")
def _html():
    from pdfrush.core.convert import _browser
    if not _browser():
        raise Skip("Edge/Chrome not found")
    h = tmp / "page.html"
    h.write_text("<h1>PDFRush</h1><p>web page test</p>", encoding="utf-8")
    run("html_to_pdf", [h], url="")


@check("OCR (scan to searchable PDF)")
def _ocr():
    from pdfrush.core import ocr
    if not ocr.available():
        raise Skip("OCR engine not installed")
    run("scan_to_pdf", [IMG], ocr=True)
    run("ocr_pdf", [A], force=True, pages="1")


@check("Forms: create, detect, fill")
def _forms():
    from pdfrush.core import edit
    f = edit.add_fields(A, out / "form.pdf", [{"type": "text", "name": "Name", "page": 0, "rect": (100, 100, 200, 20)},
                                               {"type": "checkbox", "name": "Ok", "page": 0, "rect": (320, 100, 14, 14)}])
    assert len(edit.list_fields(f)) == 2
    edit.fill_fields(f, out / "filled.pdf", {"Name": "Test", "Ok": True})
    assert edit.detect_fields(A)


@check("Edit & sign")
def _edit():
    from pdfrush.core import edit
    edit.apply_edits(A, out / "edited.pdf", [{"page": 0, "type": "text", "x": 72, "y": 72, "text": "Hello", "size": 14},
                                             {"page": 0, "type": "rect", "x": 60, "y": 60, "w": 100, "h": 40}])


@check("Workflow")
def _wf():
    from pdfrush.core import workflow
    workflow.run({"name": "t", "steps": [{"tool": "compress", "params": {}},
                                         {"tool": "watermark", "params": {"text": "W"}}]}, [A], out)


@check("AI (online or offline)")
def _ai():
    from pdfrush.core import ai, llm
    if not ai.ai_ready():
        raise Skip("no AI key / offline model set up (optional)")
    r = llm.chat([{"role": "user", "content": "Reply with the word OK."}], max_tokens=10)
    assert r.strip()


print("\n================ PDFRush self-test ================")
bad = 0
for name, ok, info in results:
    tag = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    bad += ok is False
    print(f"  {tag:4}  {name:38} {info}")
print("====================================================")
print("All good!" if not bad else f"{bad} check(s) failed.")
sys.stdout.flush()
os._exit(1 if bad else 0)
