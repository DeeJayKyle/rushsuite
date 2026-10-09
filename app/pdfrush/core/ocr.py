"""OCR (offline, RapidOCR = PaddleOCR models on ONNX Runtime): make scanned PDFs searchable/selectable,
and turn photos/scans into clean PDFs."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pypdfium2 as pdfium

from .registry import IMAGES, PDF, Param, tool
from .util import draw_invisible_text, open_pdf, out_name, overlay_pages, parse_pages, save, unique

_engine = None


def available() -> bool:
    import importlib.util
    return any(importlib.util.find_spec(m) for m in ("rapidocr_onnxruntime", "rapidocr"))


def _get():
    global _engine
    if _engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            try:
                from rapidocr import RapidOCR
            except ImportError:
                raise RuntimeError("The OCR engine isn't installed. Re-run build.bat to add it.") from None
        _engine = RapidOCR()
    return _engine


def _lines(result) -> list[tuple[list, str]]:
    if result is None:
        return []
    if hasattr(result, "txts"):                 # rapidocr >= 2
        boxes = result.boxes if result.boxes is not None else []
        return [(list(map(list, b)), t) for b, t in zip(boxes, result.txts or [])]
    if isinstance(result, tuple):               # rapidocr_onnxruntime: (result, elapse)
        result = result[0]
    return [(r[0], r[1]) for r in (result or [])]


def recognize(img) -> list[tuple[tuple[float, float, float, float], str]]:
    """OCR a PIL image -> [((left, top, right, bottom) in pixels, text)]."""
    arr = np.asarray(img.convert("RGB"))[:, :, ::-1].copy()
    out = []
    for box, text in _lines(_get()(arr)):
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        if text and text.strip():
            out.append(((min(xs), min(ys), max(xs), max(ys)), text.strip()))
    return out


def image_text(img) -> str:
    """Reading-order text of an image (rows top->bottom, items left->right)."""
    items = recognize(img)
    if not items:
        return ""
    items.sort(key=lambda it: ((it[0][1] + it[0][3]) / 2, it[0][0]))
    h = sorted(r[3] - r[1] for r, _ in items)[len(items) // 2] or 10
    rows, cur, cy = [], [], None
    for r, t in items:
        y = (r[1] + r[3]) / 2
        if cur and abs(y - cy) > h * 0.6:
            rows.append(cur)
            cur = []
        cur.append((r, t))
        cy = y
    if cur:
        rows.append(cur)
    return "\n".join(" ".join(t for _, t in sorted(row, key=lambda it: it[0][0])) for row in rows)


def ocr_pdf_file(src: Path, dest: Path, pages: str = "all", dpi: int = 220, force: bool = False,
                 password: str = "", progress=None) -> tuple[Path, int]:
    """Add an invisible, selectable text layer to scanned pages. Returns (dest, pages_done)."""
    progress = progress or (lambda f, m: None)
    pdf = open_pdf(src, password)
    doc = pdfium.PdfDocument(str(src), password=password or None)
    idx = parse_pages(pages, len(doc))
    found: dict[int, tuple] = {}
    scale = dpi / 72
    for k, i in enumerate(idx):
        page = doc[i]
        if not force:
            tp = page.get_textpage()
            existing = tp.get_text_range().strip()
            tp.close()
            if len(existing) > 30:              # already has real text
                continue
        progress(0.05 + 0.85 * k / max(1, len(idx)), f"Reading page {i + 1} of {len(doc)}")
        img = page.render(scale=scale).to_pil()    # rendered as displayed (rotation applied)
        found[i] = (img.width, img.height, recognize(img))
    doc.close()

    def draw(c, i, vw, vh):
        iw, ih, items = found[i]
        sx, sy = vw / iw, vh / ih
        for (l, t, r, b), text in items:
            draw_invisible_text(c, text, l * sx, vh - b * sy, r * sx, vh - t * sy)

    if found:
        overlay_pages(pdf, draw, sorted(found))
    progress(0.95, "Saving")
    save(pdf, dest)
    return dest, len(found)


@tool(id="ocr_pdf", name="OCR PDF", category="Optimize PDF", icon="ocr", color="#2EC27E", accepts=PDF,
      desc="Easily convert scanned PDF into searchable and selectable documents.",
      params=[Param("pages", "Pages", "pages", "all"),
              Param("quality", "Accuracy", "choice", "High", ["Fast", "High", "Best"],
                    hint="Higher accuracy is slower."),
              Param("force", "Also re-read pages that already have text", "bool", False)])
def ocr_pdf(files, out_dir, p, progress):
    dpi = {"Fast": 150, "High": 220, "Best": 300}[p.get("quality", "High")]
    dest = out_name(files[0], out_dir, "ocr")
    _d, n = ocr_pdf_file(files[0], dest, p.get("pages"), dpi, bool(p.get("force")), progress=progress)
    if n == 0:
        if p.get("_workflow"):                      # already searchable: pass it through unchanged
            return [dest]
        dest.unlink(missing_ok=True)
        raise ValueError("This PDF already contains selectable text. Tick 're-read pages' to OCR it anyway.")
    return [dest]


# ===================================================================== scan to PDF
def enhance(img, mode: str):
    """Clean up a photo of a document: auto-contrast, whiten paper, optional B&W."""
    from PIL import Image, ImageFilter, ImageOps
    img = ImageOps.exif_transpose(img).convert("RGB")
    if mode == "Original":
        return img
    g = ImageOps.autocontrast(img.convert("L"), cutoff=1)
    if mode in ("Auto", "Grayscale", "Black & white"):
        # flatten uneven lighting: divide by a heavily blurred background estimate
        bg = g.filter(ImageFilter.GaussianBlur(max(8, min(g.size) // 40)))
        a = np.asarray(g, dtype=np.float32)
        b = np.maximum(np.asarray(bg, dtype=np.float32), 1)
        flat = np.clip(a / b * 235, 0, 255).astype(np.uint8)
        g = Image.fromarray(flat)
    if mode == "Black & white":
        return g.point(lambda v: 255 if v > 170 else 0, mode="1")
    if mode == "Grayscale":
        return g
    if mode == "Color":
        return ImageOps.autocontrast(img, cutoff=1)
    # Auto: colour photo stays colour (contrast boosted), otherwise clean grayscale
    arr = np.asarray(img.resize((64, 64)), dtype=np.int16)
    sat = (arr.max(axis=2) - arr.min(axis=2)).mean()
    return ImageOps.autocontrast(img, cutoff=1) if sat > 25 else g


@tool(id="scan_to_pdf", name="Scan to PDF", category="Convert to PDF", icon="scan", color="#FFC857",
      accepts=IMAGES, combine=True,
      desc="Turn photos or scans of paper documents into clean, sharp PDFs (with optional searchable text).",
      params=[Param("enhance", "Enhance", "choice", "Auto", ["Auto", "Black & white", "Grayscale", "Color",
                                                              "Original"]),
              Param("page", "Page size", "choice", "A4", ["A4", "Letter", "Fit to image"]),
              Param("ocr", "Make text searchable (OCR)", "bool", True),
              Param("name", "Output name", "text", "scan")])
def scan_to_pdf(files, out_dir, p, progress):
    from PIL import Image

    from .convert import _image_pages
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    cleaned = []
    for k, f in enumerate(files):
        progress(0.4 * k / len(files), f"Enhancing {f.name}")
        im = enhance(Image.open(f), p.get("enhance", "Auto"))
        t = tmp / f"{k:04d}.png"
        im.save(t, "PNG", optimize=True) if im.mode == "1" else im.convert("RGB").save(t.with_suffix(".jpg"),
                                                                                         "JPEG", quality=88)
        cleaned.append(t if im.mode == "1" else t.with_suffix(".jpg"))
    buf = _image_pages(cleaned, p.get("page", "A4"), "Auto", 0)
    dest = unique(Path(out_dir) / f"{p.get('name') or 'scan'}.pdf")
    raw = tmp / "raw.pdf"
    raw.write_bytes(buf.getvalue())
    if p.get("ocr") and available():
        ocr_pdf_file(raw, dest, progress=lambda f, m: progress(0.4 + 0.6 * f, m))
    else:
        dest.write_bytes(raw.read_bytes())
    return [dest]
