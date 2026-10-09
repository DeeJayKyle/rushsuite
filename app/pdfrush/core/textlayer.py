"""Text with positions (via PDFium): words, lines, blocks and search (plain or regex).
All rectangles are (x0, y0, x1, y1) in unrotated PDF user space."""
from __future__ import annotations

import re
from dataclasses import dataclass

import pypdfium2 as pdfium

PRESETS = {
    "Email addresses": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "Phone numbers": r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)",
    "Long numbers (IDs, accounts, cards)": r"(?<!\w)\d[\d -]{6,}\d(?!\w)",
    "Dates": r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",
    "Web links": r"https?://\S+|www\.\S+",
}


@dataclass
class Word:
    text: str
    rect: tuple[float, float, float, float]
    start: int
    end: int
    line: int


def page_chars(page: "pdfium.PdfPage") -> tuple[str, list]:
    tp = page.get_textpage()
    n = tp.count_chars()
    text = tp.get_text_range(0, n) if n else ""
    boxes = [tp.get_charbox(i) for i in range(len(text))]
    tp.close()
    return text, boxes


def words(page: "pdfium.PdfPage") -> list[Word]:
    text, boxes = page_chars(page)
    out: list[Word] = []
    line = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\r\n":
            if ch == "\n":
                line += 1
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        j = i
        while j < n and not text[j].isspace():
            j += 1
        rs = [boxes[k] for k in range(i, j) if boxes[k] and boxes[k][2] > boxes[k][0]]
        if rs:
            out.append(Word(text[i:j], (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs),
                                        max(r[3] for r in rs)), i, j, line))
        i = j
    return out


def lines(page) -> list[tuple[str, tuple]]:
    ws = words(page)
    out, cur = [], []
    for w in ws:
        if cur and w.line != cur[-1].line:
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return [(" ".join(w.text for w in ln), (min(w.rect[0] for w in ln), min(w.rect[1] for w in ln),
                                            max(w.rect[2] for w in ln), max(w.rect[3] for w in ln))) for ln in out]


def blocks(page, gap_factor: float = 1.6) -> list[dict]:
    """Group lines into paragraphs: {'text', 'rect', 'size', 'lines', 'rows'} (size ~ font height)."""
    ls = lines(page)
    out: list[dict] = []
    for text, r in ls:
        h = r[3] - r[1]
        if out:
            b = out[-1]
            prev = b["last"]
            same_col = abs(r[0] - b["rect"][0]) < max(30, h * 3)
            close = 0 <= prev[1] - r[3] < h * gap_factor
            similar = abs(h - b["size"]) < max(1.5, b["size"] * 0.25)
            if same_col and close and similar:
                b["text"] += " " + text
                b["rect"] = (min(b["rect"][0], r[0]), min(b["rect"][1], r[1]), max(b["rect"][2], r[2]),
                             max(b["rect"][3], r[3]))
                b["last"] = r
                b["lines"] += 1
                b["rows"].append(text)
                continue
        out.append({"text": text, "rect": r, "size": h, "last": r, "lines": 1, "rows": [text]})
    for b in out:
        b.pop("last", None)
    return out


def search(page, terms: list[str], patterns: list[str], ignore_case: bool = True) -> list[tuple]:
    """Rectangles (one per line fragment) for every match of plain terms or regex patterns."""
    text, boxes = page_chars(page)
    flags = re.IGNORECASE if ignore_case else 0
    spans = []
    for t in terms:
        t = t.strip()
        if t:
            spans += [(m.start(), m.end()) for m in re.finditer(re.escape(t), text, flags)]
    for p in patterns:
        spans += [(m.start(), m.end()) for m in re.finditer(p, text, flags)]
    rects = []
    for a, b in spans:
        cur = None
        for k in range(a, b):
            bx = boxes[k]
            if not bx or bx[2] <= bx[0] or text[k] in "\r\n":
                if cur:
                    rects.append(cur)
                    cur = None
                continue
            if cur and abs(bx[1] - cur[1]) < (cur[3] - cur[1]) * 0.6:
                cur = (min(cur[0], bx[0]), min(cur[1], bx[1]), max(cur[2], bx[2]), max(cur[3], bx[3]))
            else:
                if cur:
                    rects.append(cur)
                cur = bx
        if cur:
            rects.append(cur)
    return [(r[0] - 1, r[1] - 1, r[2] + 1, r[3] + 1) for r in rects]


def intersects(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
