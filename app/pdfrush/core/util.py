"""Shared helpers: page-range parsing, output naming, opening PDFs, overlays."""
from __future__ import annotations

import io
import re
import threading
from pathlib import Path
from typing import Callable

import pikepdf


# PDFium is not thread-safe: background jobs hold this lock; the UI only *tries* to take it for previews.
PDFIUM_LOCK = threading.RLock()


class Busy(RuntimeError):
    pass


def pdfium_lock(timeout: float = 3.0):
    """Context manager for UI code: waits up to `timeout` s, else raises Busy."""
    from contextlib import contextmanager

    @contextmanager
    def cm():
        if not PDFIUM_LOCK.acquire(timeout=timeout):
            raise Busy("PDFRush is busy finishing another task - try again in a moment.")
        try:
            yield
        finally:
            PDFIUM_LOCK.release()
    return cm()


class PasswordRequired(Exception):
    pass


def parse_pages(spec: str | None, n: int) -> list[int]:
    """'1-3, 5, 8-' -> zero-based indices. Empty/'all' = all pages. Supports 'odd', 'even', 'last'."""
    spec = (spec or "").strip().lower()
    if spec in ("", "all", "*"):
        return list(range(n))
    if spec == "odd":
        return list(range(0, n, 2))
    if spec == "even":
        return list(range(1, n, 2))
    out: list[int] = []
    for part in re.split(r"[,\s;]+", spec):
        if not part:
            continue
        part = part.replace("last", str(n)).replace("end", str(n))
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m:
            a = int(m.group(1) or 1)
            b = int(m.group(2) or n)
            step = 1 if b >= a else -1
            out += [i - 1 for i in range(a, b + step, step) if 1 <= i <= n]
        elif part.isdigit():
            i = int(part)
            if 1 <= i <= n:
                out.append(i - 1)
        else:
            raise ValueError(f"Can't understand page range '{part}'. Use e.g. 1-3, 5, 8-")
    return out


def unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    k = 2
    while True:
        p = path.with_name(f"{stem} ({k}){ext}")
        if not p.exists():
            return p
        k += 1


def out_name(src: Path, out_dir: Path, suffix: str, ext: str = ".pdf") -> Path:
    stem = re.sub(r'[\\/:*?"<>|]+', "_", src.stem)
    return unique(Path(out_dir) / f"{stem}{('_' + suffix) if suffix else ''}{ext}")


def open_pdf(path, password: str = "", allow_overwriting_input: bool = False) -> pikepdf.Pdf:
    try:
        return pikepdf.open(str(path), password=password or "", allow_overwriting_input=allow_overwriting_input)
    except pikepdf.PasswordError:
        raise PasswordRequired(f"'{Path(path).name}' is password-protected. Enter its password (Unlock PDF), "
                               "then try again.") from None


def page_size(page: pikepdf.Page) -> tuple[float, float, float, float]:
    """(x0, y0, width, height) of the visible box (CropBox, else MediaBox)."""
    box = page.obj.get("/CropBox", None) or page.mediabox
    x0, y0, x1, y1 = [float(v) for v in box]
    return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)


def rotation(page: pikepdf.Page) -> int:
    return int(page.obj.get("/Rotate", 0)) % 360


def overlay_pages(pdf: pikepdf.Pdf, draw: Callable, indices: list[int] | None = None, under: bool = False) -> None:
    """Draw on pages with reportlab and stamp the result on top (or underneath).

    draw(canvas, page_index, width, height) draws in the page's *visual* coordinate system
    (origin bottom-left as the reader sees the page). pikepdf's add_overlay takes care of the
    page's /Rotate, so the overlay is drawn upright at the visual size."""
    from reportlab.pdfgen import canvas as rl_canvas
    indices = list(range(len(pdf.pages))) if indices is None else indices
    if not indices:
        return
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf)
    meta = []
    for i in indices:
        page = pdf.pages[i]
        x0, y0, w, h = page_size(page)
        vw, vh = (h, w) if rotation(page) in (90, 270) else (w, h)
        c.setPageSize((vw, vh))
        draw(c, i, vw, vh)
        c.showPage()
        meta.append((i, x0, y0, w, h))
    c.save()
    buf.seek(0)
    ov = pikepdf.open(buf)
    for k, (i, x0, y0, w, h) in enumerate(meta):
        target = pdf.pages[i]
        rect = pikepdf.Rectangle(x0, y0, x0 + w, y0 + h)
        if under:
            target.add_underlay(ov.pages[k], rect)
        else:
            target.add_overlay(ov.pages[k], rect)
    pdf._pdfrush_keep = getattr(pdf, "_pdfrush_keep", []) + [ov]   # keep overlay source alive until save


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    color = (color or "#000000").lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    return tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))


def save(pdf: pikepdf.Pdf, out: Path, linearize: bool = False) -> Path:
    out = Path(out)
    pdf.save(str(out), compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate,
             linearize=linearize)
    return out


FONT_CANDIDATES = {
    "latin": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "cjk": ["msyh.ttc", "simsun.ttc", "msgothic.ttc", "NotoSansCJK-Regular.ttc"],
    "indic": ["Nirmala.ttf", "Nirmala.ttc"],
    "arabic": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
}


def unicode_font(script: str = "latin", bold: bool = False) -> str:
    """Register and return a reportlab font name that can draw non-Latin text (Windows fonts first)."""
    import os

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts", Path("/usr/share/fonts/truetype/dejavu"),
            Path("/usr/share/fonts/truetype"), Path("/Library/Fonts")]
    names = FONT_CANDIDATES.get(script, FONT_CANDIDATES["latin"])
    if bold:
        names = [n.replace("segoeui.ttf", "segoeuib.ttf").replace("arial.ttf", "arialbd.ttf")
                 .replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf") for n in names] + names
    for n in names:
        for d in dirs:
            p = d / n
            if p.exists():
                fname = f"U_{p.stem}"
                if fname not in pdfmetrics.getRegisteredFontNames():
                    try:
                        pdfmetrics.registerFont(TTFont(fname, str(p), subfontIndex=0) if p.suffix == ".ttc"
                                                else TTFont(fname, str(p)))
                    except Exception:
                        continue
                return fname
    return "Helvetica-Bold" if bold else "Helvetica"


def script_of(text: str) -> str:
    for ch in text:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF:
            return "cjk"
        if 0x0900 <= o <= 0x0DFF:
            return "indic"
        if 0x0600 <= o <= 0x06FF:
            return "arabic"
    return "latin"


def to_visual(page: pikepdf.Page, x: float, y: float) -> tuple[float, float]:
    """Unrotated PDF user-space point -> visual point (origin bottom-left of the page as displayed)."""
    x0, y0, w, h = page_size(page)
    u, v = x - x0, y - y0
    r = rotation(page)
    if r == 90:
        return v, w - u
    if r == 180:
        return w - u, h - v
    if r == 270:
        return h - v, u
    return u, v


def visual_size(page: pikepdf.Page) -> tuple[float, float]:
    _x0, _y0, w, h = page_size(page)
    return (h, w) if rotation(page) in (90, 270) else (w, h)


def rect_to_visual(page: pikepdf.Page, r) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) unrotated -> visual (left, bottom, right, top)."""
    a = to_visual(page, r[0], r[1])
    b = to_visual(page, r[2], r[3])
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def draw_invisible_text(c, text: str, left: float, bottom: float, right: float, top: float) -> None:
    """Draw searchable-but-invisible text stretched over a box (render mode 3), e.g. for OCR layers."""
    text = (text or "").strip()
    if not text or right <= left or top <= bottom:
        return
    font = unicode_font(script_of(text))
    size = max(2.0, (top - bottom) * 0.85)
    width = c.stringWidth(text, font, size) or 1
    t = c.beginText()
    t.setTextRenderMode(3)
    t.setFont(font, size)
    t.setHorizScale(max(5, min(500, 100 * (right - left) / width)))
    t.setTextOrigin(left, bottom + (top - bottom) * 0.2)
    try:
        t.textOut(text)
    except Exception:
        return
    c.drawText(t)
