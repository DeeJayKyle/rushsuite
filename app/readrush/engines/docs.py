"""Import anything to listen to: PDF (text or scanned), EPUB, DOCX, XLSX/CSV, TXT/MD, HTML,
web links, images (OCR) and pasted text. EPUB/DOCX/XLSX/HTML are parsed with the standard
library only; PDFs use pypdfium2; scans/photos use RapidOCR."""
from __future__ import annotations

import csv
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

from . import textproc

ProgressFn = Callable[[float, str], None]

DOC_EXT = {".pdf", ".epub", ".docx", ".xlsx", ".csv", ".txt", ".md", ".markdown", ".html", ".htm", ".rtf"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
FILE_FILTER = ("Documents & images (*.pdf *.epub *.docx *.xlsx *.csv *.txt *.md *.html *.htm *.rtf *.png *.jpg "
               "*.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)")


@dataclass
class Imported:
    title: str
    text: str
    source: str = ""
    kind: str = "doc"
    meta: dict = field(default_factory=dict)


# ===================================================================== HTML
class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
             "blockquote", "pre", "header", "footer", "table", "ul", "ol", "dd", "dt", "figcaption"}
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "form", "button", "iframe", "aside"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n\n" if tag in ("p", "h1", "h2", "h3", "h4", "li", "blockquote") else "\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> tuple[str, str]:
    p = _HTMLText()
    try:
        p.feed(markup)
    except Exception:
        pass
    text = "".join(p.parts)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return html.unescape(p.title.strip()), text.strip()


def from_url(url: str, progress: ProgressFn | None = None) -> Imported:
    progress = progress or (lambda f, m: None)
    if not re.match(r"https?://", url):
        url = "https://" + url
    progress(0.1, "Downloading page")
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ReadRush/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        tmp = Path.home() / ".readrush_download.pdf"
        tmp.write_bytes(raw)
        doc = from_file(str(tmp), progress)
        doc.source, doc.title = url, Path(url).stem or doc.title
        return doc
    charset = re.search(r"charset=([\w-]+)", ctype)
    markup = raw.decode(charset.group(1) if charset else "utf-8", errors="replace")
    progress(0.5, "Extracting article")
    text, title = "", ""
    try:   # best article extraction when available
        import trafilatura
        text = trafilatura.extract(markup, include_comments=False, include_tables=False) or ""
        meta = trafilatura.extract_metadata(markup)
        title = (meta.title if meta else "") or ""
    except Exception:
        pass
    if len(text) < 200:
        t2, text2 = html_to_text(markup)
        title = title or t2
        text = text2 if len(text2) > len(text) else text
    return Imported(title or url, textproc.normalize_document(text), url, "web")


# ===================================================================== office / ebooks
def _docx(path: Path) -> str:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paras = []
    for p in root.iter(f"{{{ns['w']}}}p"):
        bits = []
        for node in p.iter():
            tag = node.tag.split("}")[-1]
            if tag == "t" and node.text:
                bits.append(node.text)
            elif tag == "tab":
                bits.append(" ")
            elif tag in ("br", "cr"):
                bits.append("\n")
        paras.append("".join(bits))
    return "\n\n".join(p for p in paras if p.strip())


def _xlsx(path: Path) -> str:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    out = []
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{ns}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))
        sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n))
        for k, name in enumerate(sheets, 1):
            out.append(f"Sheet {k}.")
            for row in ET.fromstring(z.read(name)).iter(f"{ns}row"):
                vals = []
                for c in row.iter(f"{ns}c"):
                    v = c.find(f"{ns}v")
                    t = c.get("t")
                    if t == "s" and v is not None:
                        vals.append(shared[int(v.text)])
                    elif t == "inlineStr":
                        vals.append("".join(x.text or "" for x in c.iter(f"{ns}t")))
                    elif v is not None and v.text:
                        vals.append(v.text)
                if any(x.strip() for x in vals):
                    out.append(", ".join(x for x in vals if x.strip()) + ".")
    return "\n".join(out)


def _epub(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = next(e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile"))
        opf = ET.fromstring(z.read(opf_path))
        base = str(Path(opf_path).parent).replace("\\", "/")
        base = "" if base == "." else base + "/"
        title = next((e.text for e in opf.iter() if e.tag.endswith("}title") and e.text), path.stem)
        manifest = {e.get("id"): e.get("href") for e in opf.iter() if e.tag.endswith("}item")}
        spine = [e.get("idref") for e in opf.iter() if e.tag.endswith("}itemref")]
        parts = []
        for idref in spine:
            href = manifest.get(idref)
            if not href:
                continue
            try:
                markup = z.read(base + href).decode("utf-8", errors="replace")
            except KeyError:
                continue
            parts.append(html_to_text(markup)[1])
    return title, "\n\n".join(p for p in parts if p.strip())


def _rtf(raw: str) -> str:
    raw = re.sub(r"\\par[d]?", "\n", raw)
    raw = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("latin-1"), raw)
    raw = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", raw)
    return raw


# ===================================================================== PDF
def _pdf(path: Path, progress: ProgressFn) -> tuple[str, dict]:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    pages, scanned = [], []
    n = len(pdf)
    for i in range(n):
        progress(0.05 + 0.6 * i / max(1, n), f"Reading page {i + 1}/{n}")
        page = pdf[i]
        tp = page.get_textpage()
        txt = tp.get_text_range() or ""
        tp.close()
        if len(txt.strip()) < 25:
            scanned.append(i)
        pages.append(txt)
    if scanned and len(scanned) >= max(1, n // 3):
        from . import ocr
        for k, i in enumerate(scanned):
            progress(0.65 + 0.33 * k / len(scanned), f"Scanning page {i + 1} (OCR)")
            img = pdf[i].render(scale=2.2).to_pil()
            pages[i] = ocr.image_to_text(img)
    pdf.close()
    text = "\n\n".join(_strip_page_furniture(p) for p in pages)
    return text, {"pages": n, "ocr_pages": len(scanned)}


def _strip_page_furniture(page: str) -> str:
    """Drop lone page numbers / running headers that make listening annoying."""
    lines = page.replace("\r", "").split("\n")
    lines = [ln for ln in lines if not re.fullmatch(r"\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d+)?\s*", ln, re.I)]
    return "\n".join(lines)


# ===================================================================== entry points
def from_file(path: str, progress: ProgressFn | None = None) -> Imported:
    progress = progress or (lambda f, m: None)
    p = Path(path)
    ext = p.suffix.lower()
    title, meta = p.stem, {}
    progress(0.02, f"Opening {p.name}")
    if ext == ".pdf":
        text, meta = _pdf(p, progress)
    elif ext == ".epub":
        title, text = _epub(p)
    elif ext == ".docx":
        text = _docx(p)
    elif ext == ".xlsx":
        text = _xlsx(p)
    elif ext == ".csv":
        rows = csv.reader(io.StringIO(p.read_text(encoding="utf-8", errors="replace")))
        text = "\n".join(", ".join(r) + "." for r in rows if any(c.strip() for c in r))
    elif ext in (".html", ".htm"):
        t, text = html_to_text(p.read_text(encoding="utf-8", errors="replace"))
        title = t or title
    elif ext == ".rtf":
        text = _rtf(p.read_text(encoding="latin-1", errors="replace"))
    elif ext in IMG_EXT:
        from . import ocr
        progress(0.2, "Scanning text (OCR)")
        text = ocr.image_to_text(str(p))
        meta = {"ocr": True}
        return Imported(title, textproc.normalize_document(text), str(p), "scan", meta)
    else:
        raw = p.read_bytes()
        for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if ext in (".md", ".markdown"):
            text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
            text = re.sub(r"[*_`]{1,3}([^*_`]+)[*_`]{1,3}", r"\1", text)
            text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    progress(0.99, "Preparing")
    text = textproc.normalize_document(text)
    if not text.strip():
        raise ValueError(f"No readable text found in {p.name}. If it's a scan, try importing it as images.")
    return Imported(title, text, str(p), "doc", meta)


def from_text(text: str, title: str = "") -> Imported:
    text = textproc.normalize_document(text)
    if not title:
        first = text.strip().split("\n", 1)[0]
        title = (first[:60] + "…") if len(first) > 60 else first
    return Imported(title or "Pasted text", text, "", "text")
