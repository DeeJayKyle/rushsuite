"""Compare two PDFs: word-level text differences and pixel-level visual differences."""
from __future__ import annotations

import difflib
import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pikepdf
import pypdfium2 as pdfium

from . import textlayer
from .registry import PDF, Param, tool
from .util import rect_to_visual, unique, visual_size

RED = (234, 67, 53)
GREEN = (46, 194, 126)


@dataclass
class Change:
    kind: str            # 'removed' | 'added' | 'changed'
    old: str
    new: str
    page_a: int | None
    page_b: int | None


@dataclass
class Diff:
    changes: list[Change] = field(default_factory=list)
    marks_a: dict = field(default_factory=dict)     # page -> [visual rects (l, b, r, t)]
    marks_b: dict = field(default_factory=dict)
    pages_a: int = 0
    pages_b: int = 0
    similarity: float = 1.0


def _doc_words(path: Path):
    doc = pdfium.PdfDocument(str(path))
    pk = pikepdf.open(str(path))
    out = []
    for i in range(len(doc)):
        for w in textlayer.words(doc[i]):
            out.append((w.text, i, rect_to_visual(pk.pages[i], w.rect)))
    n = len(doc)
    doc.close()
    return out, n


def text_diff(a: Path, b: Path, ignore_case: bool = False) -> Diff:
    wa, na = _doc_words(a)
    wb, nb = _doc_words(b)
    norm = (lambda s: s.lower()) if ignore_case else (lambda s: s)
    sm = difflib.SequenceMatcher(None, [norm(w[0]) for w in wa], [norm(w[0]) for w in wb], autojunk=False)
    d = Diff(pages_a=na, pages_b=nb, similarity=sm.ratio() if (wa or wb) else 1.0)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        for w in wa[i1:i2]:
            d.marks_a.setdefault(w[1], []).append(w[2])
        for w in wb[j1:j2]:
            d.marks_b.setdefault(w[1], []).append(w[2])
        kind = {"delete": "removed", "insert": "added", "replace": "changed"}[op]
        d.changes.append(Change(kind, " ".join(w[0] for w in wa[i1:i2]), " ".join(w[0] for w in wb[j1:j2]),
                                wa[i1][1] if i2 > i1 else None, wb[j1][1] if j2 > j1 else None))
    return d


def render_marked(path: Path, page: int, rects, color, scale: float = 1.4):
    """PIL image of a page with translucent highlight boxes (rects in visual points)."""
    from PIL import Image, ImageDraw
    doc = pdfium.PdfDocument(str(path))
    img = doc[page].render(scale=scale).to_pil().convert("RGB")
    doc.close()
    if rects:
        ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(ov)
        H = img.height
        for l, b, r, t in rects:
            dr.rectangle([l * scale - 1, H - t * scale - 1, r * scale + 1, H - b * scale + 1],
                         fill=color + (80,), outline=color + (220,))
        img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    return img


def visual_diff(a: Path, b: Path, page_a: int, page_b: int, scale: float = 1.4, threshold: int = 48):
    """(image_a, image_b_with_magenta_changes, changed_fraction)."""
    from PIL import Image
    da, db = pdfium.PdfDocument(str(a)), pdfium.PdfDocument(str(b))
    ia = da[page_a].render(scale=scale).to_pil().convert("RGB")
    ib = db[page_b].render(scale=scale).to_pil().convert("RGB")
    da.close()
    db.close()
    if ib.size != ia.size:
        ib_cmp = ib.resize(ia.size)
    else:
        ib_cmp = ib
    xa = np.asarray(ia, dtype=np.int16)
    xb = np.asarray(ib_cmp, dtype=np.int16)
    mask = np.abs(xa - xb).max(axis=2) > threshold
    out = xb.astype(np.uint8).copy()
    out[mask] = (0.35 * out[mask] + 0.65 * np.array([230, 0, 180])).astype(np.uint8)
    return ia, Image.fromarray(out), float(mask.mean())


def _report(a: Path, b: Path, d: Diff | None, mode: str, dest: Path, progress) -> Path:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from .util import unicode_font
    font = unicode_font()
    bold = unicode_font(bold=True)
    c = canvas.Canvas(str(dest), pagesize=A4)
    W, H = A4
    c.setFont(bold, 20)
    c.drawString(50, H - 70, "PDF comparison")
    c.setFont(font, 10)
    c.setFillColor(HexColor("#555555"))
    c.drawString(50, H - 92, f"Original:  {a.name}")
    c.drawString(50, H - 106, f"Changed:  {b.name}")
    y = H - 140
    c.setFillColor(HexColor("#111111"))
    if d is not None:
        added = sum(1 for x in d.changes if x.kind == "added")
        removed = sum(1 for x in d.changes if x.kind == "removed")
        changed = sum(1 for x in d.changes if x.kind == "changed")
        c.setFont(bold, 12)
        c.drawString(50, y, f"Text similarity {d.similarity * 100:.1f}%   -   {changed} changed, {added} added, "
                            f"{removed} removed")
        y -= 26
        c.setFont(font, 9)
        for ch in d.changes:
            if y < 60:
                c.showPage()
                c.setFont(font, 9)
                y = H - 60
            pg = f"p{(ch.page_a if ch.page_a is not None else ch.page_b) + 1}"
            if ch.kind == "removed":
                parts = [("#EA4335", f"- {ch.old}")]
            elif ch.kind == "added":
                parts = [("#2EC27E", f"+ {ch.new}")]
            else:
                parts = [("#EA4335", f"- {ch.old}"), ("#2EC27E", f"   + {ch.new}")]
            c.setFillColor(HexColor("#777777"))
            c.drawString(50, y, pg)
            x = 80
            for col, txt in parts:
                txt = txt if len(txt) < 110 else txt[:107] + "..."
                c.setFillColor(HexColor(col))
                c.drawString(x, y, txt)
                x += c.stringWidth(txt, font, 9) + 6
                if x > W - 60:
                    y -= 13
                    x = 80
            y -= 14
        if not d.changes:
            c.drawString(50, y, "No text differences found.")
    c.showPage()
    # side-by-side pages
    n = max(d.pages_a if d else 0, d.pages_b if d else 0) if d else 0
    if d is None:
        n = max(len(pdfium.PdfDocument(str(a))), len(pdfium.PdfDocument(str(b))))
    na = len(pdfium.PdfDocument(str(a)))
    nb = len(pdfium.PdfDocument(str(b)))
    LW, LH = landscape(A4)
    for i in range(n):
        progress(0.3 + 0.65 * i / max(1, n), f"Page {i + 1}")
        c.setPageSize((LW, LH))
        imgs = []
        if mode == "Visual" and i < na and i < nb:
            ia, ib, frac = visual_diff(a, b, i, i)
            imgs = [ia, ib]
            label = f"Page {i + 1}  -  {frac * 100:.2f}% of pixels differ"
        else:
            imgs = [render_marked(a, i, d.marks_a.get(i, []), RED) if i < na else None,
                    render_marked(b, i, d.marks_b.get(i, []), GREEN) if i < nb else None]
            label = f"Page {i + 1}"
        c.setFont(bold, 11)
        c.setFillColor(HexColor("#111111"))
        c.drawString(30, LH - 30, label)
        c.setFont(font, 9)
        for k, im in enumerate(imgs):
            x0 = 30 + k * (LW - 60) / 2
            bw, bh = (LW - 60) / 2 - 10, LH - 70
            c.setFillColor(HexColor("#777777"))
            c.drawString(x0, LH - 46, (a if k == 0 else b).name)
            if im is None:
                c.drawString(x0, LH / 2, "(no page)")
                continue
            s = min(bw / im.width, bh / im.height)
            w, h = im.width * s, im.height * s
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            buf.seek(0)
            c.drawImage(ImageReader(buf), x0, LH - 55 - h, w, h)
            c.setStrokeColor(HexColor("#CCCCCC"))
            c.rect(x0, LH - 55 - h, w, h)
        c.showPage()
    c.save()
    return dest


@tool(id="compare", name="Compare PDF", category="PDF Intelligence", icon="compare", color="#7C5CFF", accepts=PDF,
      combine=True, min_files=2, max_files=2, page="compare", workflow=False, new=True,
      desc="Show a side-by-side document comparison and easily spot changes between different file versions.",
      params=[Param("mode", "Compare", "choice", "Text", ["Text", "Visual"],
                    hint="Text = words added/removed/changed.  Visual = any pixel difference (images, layout)."),
              Param("ignore_case", "Ignore upper/lower case", "bool", False, show_if=("mode", "Text"))])
def compare(files, out_dir, p, progress):
    if len(files) != 2:
        raise ValueError("Add exactly two PDFs: the original first, then the changed version.")
    a, b = files
    progress(0.05, "Reading text")
    d = text_diff(a, b, bool(p.get("ignore_case")))
    dest = unique(Path(out_dir) / f"compare_{a.stem}_vs_{b.stem}.pdf")
    _report(a, b, d, p.get("mode", "Text"), dest, progress)
    return [dest]


def page_count(path: Path) -> int:
    doc = pdfium.PdfDocument(str(path))
    n = len(doc)
    doc.close()
    return n


__all__ = ["text_diff", "visual_diff", "render_marked", "compare", "page_count", "visual_size"]
