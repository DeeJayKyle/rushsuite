"""Scan & listen: offline OCR with RapidOCR (PaddleOCR models on ONNX Runtime)."""
from __future__ import annotations

import numpy as np

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
            from rapidocr import RapidOCR          # newer package name
        _engine = RapidOCR()
    return _engine


def _to_array(img) -> np.ndarray:
    from PIL import Image, ImageOps
    if isinstance(img, np.ndarray):
        return img
    if not isinstance(img, Image.Image):
        img = Image.open(img)
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    if max(w, h) > 3000:                        # keep it fast
        s = 3000 / max(w, h)
        img = img.resize((int(w * s), int(h * s)))
    return np.asarray(img)[:, :, ::-1].copy()   # RGB -> BGR (OpenCV order)


def _lines(result) -> list[tuple[list, str]]:
    """Normalise RapidOCR outputs across versions to [(box, text)]."""
    if result is None:
        return []
    if hasattr(result, "txts"):                 # rapidocr >= 2
        boxes = result.boxes if result.boxes is not None else []
        return [(list(map(list, b)), t) for b, t in zip(boxes, result.txts or [])]
    if isinstance(result, tuple):               # rapidocr_onnxruntime: (result, elapse)
        result = result[0]
    return [(r[0], r[1]) for r in (result or [])]


def image_to_text(img) -> str:
    """OCR an image path / PIL image / array and rebuild reading order (lines -> paragraphs)."""
    arr = _to_array(img)
    lines = _lines(_get()(arr))
    if not lines:
        return ""
    items = []
    for box, text in lines:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((min(ys), max(ys), min(xs), text.strip()))
    heights = sorted(b - a for a, b, _, _ in items)
    h = heights[len(heights) // 2] or 10
    # group into rows, then sort rows top->bottom and items left->right
    items.sort(key=lambda t: (t[0] + t[1]) / 2)
    rows, cur, cur_y = [], [], None
    for it in items:
        y = (it[0] + it[1]) / 2
        if cur and abs(y - cur_y) > h * 0.6:
            rows.append(cur)
            cur = []
        cur.append(it)
        cur_y = y if len(cur) == 1 else (cur_y * (len(cur) - 1) + y) / len(cur)
    if cur:
        rows.append(cur)
    out, prev_bottom = [], None
    for row in rows:
        row.sort(key=lambda t: t[2])
        text = " ".join(t[3] for t in row if t[3])
        top = min(t[0] for t in row)
        if prev_bottom is not None and top - prev_bottom > h * 1.2:
            out.append("")                      # paragraph gap
        out.append(text)
        prev_bottom = max(t[1] for t in row)
    return "\n".join(out)
