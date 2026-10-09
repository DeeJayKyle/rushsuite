"""Edit PDF: watermark, page numbers, crop, add text/images/shapes/freehand/signatures, forms."""
from __future__ import annotations

import math
from pathlib import Path

import pikepdf

from .registry import IMAGES, PDF, Param, tool
from .util import (hex_to_rgb, open_pdf, out_name, overlay_pages, page_size, parse_pages, rotation, save,
                   script_of, unicode_font, visual_size)

EDIT = "Edit PDF"
POSITIONS = ["Center", "Top left", "Top center", "Top right", "Middle left", "Middle right", "Bottom left",
             "Bottom center", "Bottom right", "Tiled (mosaic)"]


def _anchor(pos: str, W: float, H: float, w: float, h: float, margin: float) -> tuple[float, float]:
    """Bottom-left corner for an object of size w x h at a named position (visual coords)."""
    col = 0 if "left" in pos.lower() else (2 if "right" in pos.lower() else 1)
    row = 2 if pos.lower().startswith("top") else (0 if pos.lower().startswith("bottom") else 1)
    x = [margin, (W - w) / 2, W - w - margin][col]
    y = [margin, (H - h) / 2, H - h - margin][row]
    return x, y


# ===================================================================== watermark
@tool(id="watermark", name="Watermark", category=EDIT, icon="watermark", color="#9B7BFF", accepts=PDF,
      desc="Stamp an image or text over your PDF in seconds. Choose the typography, transparency and position.",
      params=[Param("mode", "Watermark", "choice", "Text", ["Text", "Image"]),
              Param("text", "Text", "text", "CONFIDENTIAL", show_if=("mode", "Text")),
              Param("size", "Font size", "int", 60, minimum=6, maximum=300, show_if=("mode", "Text")),
              Param("bold", "Bold", "bool", True, show_if=("mode", "Text")),
              Param("color", "Color", "color", "#D62828", show_if=("mode", "Text")),
              Param("image", "Image file", "file", "", options=IMAGES, show_if=("mode", "Image")),
              Param("scale", "Image size (% of page width)", "int", 40, minimum=5, maximum=100,
                    show_if=("mode", "Image")),
              Param("opacity", "Transparency (opacity %)", "int", 25, minimum=5, maximum=100),
              Param("angle", "Rotation (degrees)", "int", 45, minimum=-180, maximum=180),
              Param("position", "Position", "choice", "Center", POSITIONS),
              Param("layer", "Layer", "choice", "Over the content", ["Over the content", "Below the content"]),
              Param("pages", "Pages", "pages", "all")])
def watermark(files, out_dir, p, progress):
    pdf = open_pdf(files[0])
    idx = parse_pages(p.get("pages"), len(pdf.pages))
    alpha = max(0.03, min(1.0, int(p.get("opacity", 25)) / 100))
    angle = float(p.get("angle", 0))
    pos = p.get("position", "Center")
    img_reader = None
    if p["mode"] == "Image":
        from reportlab.lib.utils import ImageReader
        if not p.get("image") or not Path(p["image"]).exists():
            raise ValueError("Choose an image for the watermark.")
        img_reader = ImageReader(str(p["image"]))
        iw, ih = img_reader.getSize()
    text = str(p.get("text", ""))
    font = unicode_font(script_of(text), bold=bool(p.get("bold")))
    size = float(p.get("size", 60))

    def draw(c, i, W, H):
        c.setFillAlpha(alpha)
        c.setStrokeAlpha(alpha)
        if img_reader is not None:
            w = W * int(p.get("scale", 40)) / 100
            h = w * ih / iw
        else:
            r, g, b = hex_to_rgb(p.get("color"))
            c.setFillColorRGB(r, g, b)
            c.setFont(font, size)
            w, h = c.stringWidth(text, font, size), size * 0.75

        def stamp(cx, cy):
            c.saveState()
            c.translate(cx, cy)
            c.rotate(angle)
            if img_reader is not None:
                c.drawImage(img_reader, -w / 2, -h / 2, w, h, mask="auto")
            else:
                c.drawString(-w / 2, -h / 2 + size * 0.1, text)
            c.restoreState()

        if pos.startswith("Tiled"):
            step_x, step_y = w * 1.3 + 40, max(h * 3, 120)
            for row in range(int(H / step_y) + 2):
                for col in range(int(W / step_x) + 2):
                    stamp(col * step_x + (step_x / 2 if row % 2 else 0), row * step_y)
        else:
            rad = math.radians(angle)
            bw = abs(w * math.cos(rad)) + abs(h * math.sin(rad))
            bh = abs(w * math.sin(rad)) + abs(h * math.cos(rad))
            x, y = _anchor(pos, W, H, bw, bh, 24)
            stamp(x + bw / 2, y + bh / 2)

    overlay_pages(pdf, draw, idx, under=p.get("layer", "").startswith("Below"))
    return [save(pdf, out_name(files[0], out_dir, "watermarked"))]


# ===================================================================== page numbers
@tool(id="page_numbers", name="Page numbers", category=EDIT, icon="numbers", color="#9B7BFF", accepts=PDF,
      desc="Add page numbers into PDFs with ease. Choose your positions, dimensions, typography.",
      params=[Param("position", "Position", "choice", "Bottom center",
                    ["Bottom center", "Bottom right", "Bottom left", "Top center", "Top right", "Top left"]),
              Param("format", "Text", "choice", "{n}", ["{n}", "Page {n}", "Page {n} of {total}", "{n} / {total}",
                                                       "- {n} -"]),
              Param("start", "First number", "int", 1, minimum=0, maximum=100000),
              Param("from_page", "Start numbering on page", "int", 1, minimum=1, maximum=100000),
              Param("size", "Font size", "int", 11, minimum=5, maximum=72),
              Param("color", "Color", "color", "#222222"),
              Param("margin", "Margin (pt)", "int", 28, minimum=0, maximum=200),
              Param("mirror", "Mirror left/right on even pages (books)", "bool", False)])
def page_numbers(files, out_dir, p, progress):
    pdf = open_pdf(files[0])
    n = len(pdf.pages)
    first = max(1, int(p.get("from_page", 1))) - 1
    idx = list(range(first, n))
    total = int(p.get("start", 1)) + len(idx) - 1
    size = float(p.get("size", 11))
    r, g, b = hex_to_rgb(p.get("color"))
    margin = float(p.get("margin", 28))

    def draw(c, i, W, H):
        num = int(p.get("start", 1)) + (i - first)
        text = p.get("format", "{n}").replace("{n}", str(num)).replace("{total}", str(total))
        c.setFont("Helvetica", size)
        c.setFillColorRGB(r, g, b)
        pos = p.get("position", "Bottom center")
        if p.get("mirror") and (i % 2 == 1):
            pos = pos.replace("right", "LEFT").replace("left", "right").replace("LEFT", "left")
        w = c.stringWidth(text, "Helvetica", size)
        x, y = _anchor(pos, W, H, w, size * 0.75, margin)
        c.drawString(x, y, text)

    overlay_pages(pdf, draw, idx)
    return [save(pdf, out_name(files[0], out_dir, "numbered"))]


# ===================================================================== crop
def from_visual(page: pikepdf.Page, vx: float, vy: float) -> tuple[float, float]:
    x0, y0, w, h = page_size(page)
    r = rotation(page)
    if r == 90:
        u, v = w - vy, vx
    elif r == 180:
        u, v = w - vx, h - vy
    elif r == 270:
        u, v = vy, h - vx
    else:
        u, v = vx, vy
    return x0 + u, y0 + v


def set_visual_crop(page: pikepdf.Page, left: float, bottom: float, right: float, top: float) -> None:
    """Crop to a rectangle given in visual coordinates (origin bottom-left as displayed)."""
    a = from_visual(page, left, bottom)
    b = from_visual(page, right, top)
    mb = [float(v) for v in page.mediabox]
    x0, x1 = max(min(a[0], b[0]), min(mb[0], mb[2])), min(max(a[0], b[0]), max(mb[0], mb[2]))
    y0, y1 = max(min(a[1], b[1]), min(mb[1], mb[3])), min(max(a[1], b[1]), max(mb[1], mb[3]))
    if x1 - x0 > 5 and y1 - y0 > 5:
        page.obj.CropBox = pikepdf.Array([float(x0), float(y0), float(x1), float(y1)])


def content_bbox(src: Path, i: int, pad: float = 10) -> tuple[float, float, float, float] | None:
    """Visual (left, bottom, right, top) of non-white content on page i."""
    import numpy as np
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(src))
    page = doc[i]
    W, H = page.get_size()
    if page.get_rotation() in (90, 270):
        W, H = H, W
    img = page.render(scale=0.6).to_pil().convert("L")
    doc.close()
    a = np.asarray(img)
    ys, xs = np.nonzero(a < 235)
    if not len(xs):
        return None
    sx, sy = img.width / W, img.height / H
    left, right = xs.min() / sx - pad, (xs.max() + 1) / sx + pad
    top, bottom = H - ys.min() / sy + pad, H - (ys.max() + 1) / sy - pad
    return float(max(0, left)), float(max(0, bottom)), float(min(W, right)), float(min(H, top))


@tool(id="crop", name="Crop PDF", category=EDIT, icon="crop", color="#9B7BFF", accepts=PDF, page="crop",
      desc="Crop margins of PDF documents or select specific areas, then apply the changes to one page or the "
           "whole document.",
      params=[Param("mode", "Crop", "choice", "Auto-trim white margins", ["Auto-trim white margins", "Margins"]),
              Param("top", "Top (mm)", "float", 10, maximum=500, show_if=("mode", "Margins")),
              Param("bottom", "Bottom (mm)", "float", 10, maximum=500, show_if=("mode", "Margins")),
              Param("left", "Left (mm)", "float", 10, maximum=500, show_if=("mode", "Margins")),
              Param("right", "Right (mm)", "float", 10, maximum=500, show_if=("mode", "Margins")),
              Param("pages", "Pages", "pages", "all")])
def crop(files, out_dir, p, progress):
    pdf = open_pdf(files[0])
    mm = 72 / 25.4
    idx = parse_pages(p.get("pages"), len(pdf.pages))
    for k, i in enumerate(idx):
        progress(k / max(1, len(idx)), f"Page {i + 1}")
        page = pdf.pages[i]
        W, H = visual_size(page)
        if p["mode"].startswith("Auto"):
            bb = content_bbox(files[0], i)
            if bb:
                set_visual_crop(page, *bb)
        else:
            set_visual_crop(page, float(p["left"]) * mm, float(p["bottom"]) * mm, W - float(p["right"]) * mm,
                            H - float(p["top"]) * mm)
    return [save(pdf, out_name(files[0], out_dir, "cropped"))]


# ===================================================================== free editing (editor + sign)
def apply_edits(src: Path, dest: Path, ops: list[dict], password: str = "") -> Path:
    """ops use *visual top-left* coordinates in points (like the screen): x, y, w, h.
    types: text, image, rect, ellipse, line, ink, highlight, whiteout."""
    from reportlab.lib.utils import ImageReader
    pdf = open_pdf(src, password)
    by_page: dict[int, list] = {}
    for op in ops:
        by_page.setdefault(int(op["page"]), []).append(op)

    def draw(c, i, W, H):
        for op in by_page.get(i, []):
            t = op["type"]
            x, y = float(op.get("x", 0)), float(op.get("y", 0))
            w, h = float(op.get("w", 0)), float(op.get("h", 0))
            by = H - y - h                       # bottom-left y
            c.saveState()
            c.setFillAlpha(float(op.get("opacity", 1)))
            c.setStrokeAlpha(float(op.get("opacity", 1)))
            if t == "text":
                text = str(op.get("text", ""))
                size = float(op.get("size", 14))
                font = unicode_font(script_of(text), bold=bool(op.get("bold")))
                c.setFont(font, size)
                c.setFillColorRGB(*hex_to_rgb(op.get("color", "#000000")))
                for k, line in enumerate(text.split("\n")):
                    c.drawString(x, H - y - size * (k + 1) * 1.0 + size * 0.2, line)
            elif t == "image":
                img = ImageReader(op["path"])
                c.drawImage(img, x, by, w, h, mask="auto", preserveAspectRatio=bool(op.get("keep_ratio", True)),
                            anchor="c")
            elif t in ("rect", "ellipse", "highlight", "whiteout"):
                if t == "highlight":
                    c.setFillColorRGB(*hex_to_rgb(op.get("color", "#FFE14D")))
                    c.setFillAlpha(float(op.get("opacity", 0.4)))
                    c.rect(x, by, w, h, stroke=0, fill=1)
                elif t == "whiteout":
                    c.setFillColorRGB(1, 1, 1)
                    c.setFillAlpha(1)
                    c.rect(x, by, w, h, stroke=0, fill=1)
                else:
                    fill = op.get("fill")
                    c.setStrokeColorRGB(*hex_to_rgb(op.get("color", "#D62828")))
                    c.setLineWidth(float(op.get("width", 2)))
                    if fill:
                        c.setFillColorRGB(*hex_to_rgb(fill))
                    if t == "rect":
                        c.rect(x, by, w, h, stroke=1, fill=1 if fill else 0)
                    else:
                        c.ellipse(x, by, x + w, by + h, stroke=1, fill=1 if fill else 0)
            elif t == "line":
                c.setStrokeColorRGB(*hex_to_rgb(op.get("color", "#D62828")))
                c.setLineWidth(float(op.get("width", 2)))
                c.line(float(op["x1"]), H - float(op["y1"]), float(op["x2"]), H - float(op["y2"]))
            elif t == "ink":
                c.setStrokeColorRGB(*hex_to_rgb(op.get("color", "#1D4ED8")))
                c.setLineWidth(float(op.get("width", 2)))
                c.setLineCap(1)
                c.setLineJoin(1)
                for stroke in op.get("points", []):
                    if len(stroke) < 2:
                        continue
                    path = c.beginPath()
                    path.moveTo(stroke[0][0], H - stroke[0][1])
                    for px, py in stroke[1:]:
                        path.lineTo(px, H - py)
                    c.drawPath(path, stroke=1, fill=0)
            c.restoreState()

    overlay_pages(pdf, draw, sorted(by_page))
    return save(pdf, dest)


@tool(id="edit", name="Edit PDF", category=EDIT, icon="edit", color="#9B7BFF", accepts=PDF, page="edit",
      workflow=False, desc="Add text, images, shapes or freehand annotations to a PDF document. Edit the size, font, "
                           "and color of the added content.")
def edit(files, out_dir, p, progress):
    raise RuntimeError("Use the Edit screen")


@tool(id="sign", name="Sign PDF", category="PDF Security", icon="sign", color="#4DA3FF", accepts=PDF, page="sign",
      workflow=False, desc="Sign yourself: draw, type or upload your signature and place it anywhere, with date and "
                           "initials.")
def sign(files, out_dir, p, progress):
    raise RuntimeError("Use the Sign screen")


# ===================================================================== forms
def list_fields(src: Path, password: str = "") -> list[dict]:
    from pypdf import PdfReader
    r = PdfReader(str(src))
    if r.is_encrypted:
        r.decrypt(password or "")
    out = []
    for pi, page in enumerate(r.pages):
        for a in page.get("/Annots", []) or []:
            a = a.get_object()
            if a.get("/Subtype") != "/Widget":
                continue
            node, names = a, []
            ft = a.get("/FT")
            while node is not None:
                if "/T" in node:
                    names.append(str(node["/T"]))
                ft = ft or node.get("/FT")
                node = node.get("/Parent").get_object() if node.get("/Parent") is not None else None
            name = ".".join(reversed(names))
            if not name:
                continue
            kind = {"/Tx": "text", "/Btn": "checkbox", "/Ch": "choice", "/Sig": "signature"}.get(str(ft), "text")
            flags = int((a.get("/Ff") or (a.get("/Parent").get_object().get("/Ff") if a.get("/Parent") else 0)) or 0)
            if kind == "checkbox" and flags & (1 << 15):
                kind = "radio"
            holder = a if "/V" in a or "/Parent" not in a else a["/Parent"].get_object()
            val = holder.get("/V")
            opts = []
            if kind == "choice":
                for o in (holder.get("/Opt") or a.get("/Opt") or []):
                    o = o.get_object() if hasattr(o, "get_object") else o
                    opts.append(str(o[1] if isinstance(o, list) and len(o) > 1 else o))
            if kind in ("checkbox", "radio"):
                ap = a.get("/AP", {}).get("/N", {}) if a.get("/AP") else {}
                on = [str(k) for k in ap.keys() if str(k) != "/Off"]
                opts = on or ["/Yes"]
            rect = [float(v) for v in a.get("/Rect", [0, 0, 0, 0])]
            if any(f["name"] == name for f in out) and kind != "radio":
                continue
            out.append({"name": name, "type": kind, "value": "" if val is None else str(val), "options": opts,
                        "page": pi, "rect": rect})
    return out


def fill_fields(src: Path, dest: Path, values: dict, flatten: bool = False, password: str = "") -> Path:
    import logging

    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, NameObject
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    r = PdfReader(str(src))
    if r.is_encrypted:
        r.decrypt(password or "")
    w = PdfWriter(clone_from=r)
    fields = {f["name"]: f for f in list_fields(src, password)}
    vals = {}
    for k, v in values.items():
        f = fields.get(k)
        if f and f["type"] in ("checkbox", "radio"):
            vals[k] = (f["options"][0] if (v is True or str(v).lower() in ("1", "true", "yes", "on"))
                       else "/Off") if f["type"] == "checkbox" else v
        else:
            vals[k] = "" if v is None else str(v)
    for page in w.pages:
        try:
            w.update_page_form_field_values(page, vals, auto_regenerate=False, flatten=flatten)
        except TypeError:
            w.update_page_form_field_values(page, vals, auto_regenerate=False)
    if not flatten:
        w.set_need_appearances_writer(True)
    else:
        for page in w.pages:            # drop the now-static widgets
            if "/Annots" in page:
                keep = [a for a in page["/Annots"] if a.get_object().get("/Subtype") != "/Widget"]
                page[NameObject("/Annots")] = ArrayObject(keep)
        if "/AcroForm" in w._root_object:
            del w._root_object["/AcroForm"]
    with open(dest, "wb") as fh:
        w.write(fh)
    return Path(dest)


def _ap_stream(pdf: pikepdf.Pdf, w: float, h: float, content: bytes) -> pikepdf.Stream:
    s = pdf.make_stream(content)
    s.Type = pikepdf.Name.XObject
    s.Subtype = pikepdf.Name.Form
    s.BBox = pikepdf.Array([0, 0, w, h])
    return s


def add_fields(src: Path, dest: Path, fields: list[dict], password: str = "") -> Path:
    """fields: {type: text|checkbox|choice|multiline, name, page, rect: visual top-left (x, y, w, h), options}"""
    pdf = open_pdf(src, password)
    root = pdf.Root
    if "/AcroForm" not in root:
        root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array()))
    af = root.AcroForm
    if "/Fields" not in af:
        af.Fields = pikepdf.Array()
    helv = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.Helvetica,
                                                Encoding=pikepdf.Name.WinAnsiEncoding))
    af.DR = pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=helv))
    af.DA = pikepdf.String("/Helv 0 Tf 0 g")
    af.NeedAppearances = True
    existing = {str(f.get("/T", "")) for f in af.Fields}
    for f in fields:
        page = pdf.pages[int(f["page"])]
        W, H = visual_size(page)
        x, y, w, h = [float(v) for v in f["rect"]]
        a = from_visual(page, x, H - y - h)
        b = from_visual(page, x + w, H - y)
        rect = [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]
        rw, rh = rect[2] - rect[0], rect[3] - rect[1]
        name = f.get("name") or f"{f['type']}{len(af.Fields) + 1}"
        while name in existing:
            name += "_"
        existing.add(name)
        d = pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, T=pikepdf.String(name),
                               Rect=pikepdf.Array(rect), F=4, P=page.obj,
                               MK=pikepdf.Dictionary(BC=pikepdf.Array([0.4, 0.4, 0.4]), BG=pikepdf.Array([1, 1, 1])))
        kind = f["type"]
        if kind in ("text", "multiline"):
            d.FT = pikepdf.Name.Tx
            d.DA = pikepdf.String("/Helv 0 Tf 0 g")
            d.V = pikepdf.String(str(f.get("value", "")))
            if kind == "multiline":
                d.Ff = 4096
        elif kind == "checkbox":
            d.FT = pikepdf.Name.Btn
            d.V = pikepdf.Name.Off
            d.AS = pikepdf.Name.Off
            d.MK.CA = pikepdf.String("4")
            on = _ap_stream(pdf, rw, rh, (f"q 0.1 0.1 0.1 RG 1.5 w {rw * .2:.1f} {rh * .5:.1f} m {rw * .42:.1f} "
                                          f"{rh * .25:.1f} l {rw * .8:.1f} {rh * .8:.1f} l S "
                                          f"0.4 G 0.8 w 0.5 0.5 {rw - 1:.1f} {rh - 1:.1f} re S Q").encode())
            off = _ap_stream(pdf, rw, rh, f"q 0.4 G 0.8 w 0.5 0.5 {rw - 1:.1f} {rh - 1:.1f} re S Q".encode())
            d.AP = pikepdf.Dictionary(N=pikepdf.Dictionary(Yes=on, Off=off))
        elif kind == "choice":
            opts = [o for o in f.get("options", []) if str(o).strip()] or ["Option 1", "Option 2"]
            d.FT = pikepdf.Name.Ch
            d.Ff = 131072                        # combo box
            d.Opt = pikepdf.Array([pikepdf.String(o) for o in opts])
            d.V = pikepdf.String(opts[0])
            d.DA = pikepdf.String("/Helv 0 Tf 0 g")
        ref = pdf.make_indirect(d)
        if "/Annots" not in page.obj:
            page.obj.Annots = pikepdf.Array()
        page.obj.Annots.append(ref)
        af.Fields.append(ref)
    return save(pdf, dest)


def detect_fields(src: Path, password: str = "") -> list[dict]:
    """Guess where fields belong: runs of ____ or ...... become text fields, ☐/[ ] become checkboxes."""
    import re

    import pypdfium2 as pdfium

    from . import textlayer
    doc = pdfium.PdfDocument(str(src), password=password or None)
    out = []
    for i in range(len(doc)):
        page = doc[i]
        W, H = page.get_size()
        if page.get_rotation() in (90, 270):
            W, H = H, W
        text, boxes = textlayer.page_chars(page)
        for m in re.finditer(r"_{3,}|\.{6,}|…{3,}", text):
            bs = [boxes[k] for k in range(m.start(), m.end()) if boxes[k][2] > boxes[k][0]]
            if not bs:
                continue
            x0, x1 = min(b[0] for b in bs), max(b[2] for b in bs)
            base = min(b[1] for b in bs)
            out.append({"type": "text", "page": i, "rect": (x0, H - base - 14, x1 - x0, 15), "name": ""})
        for m in re.finditer(r"☐|□|\[\s?\]", text):
            bs = [boxes[k] for k in range(m.start(), m.end()) if boxes[k][2] > boxes[k][0]]
            if bs:
                x0, y0 = min(b[0] for b in bs), min(b[1] for b in bs)
                out.append({"type": "checkbox", "page": i, "rect": (x0, H - y0 - 11, 11, 11), "name": ""})
    doc.close()
    return out


@tool(id="forms", name="PDF Forms", category=EDIT, icon="form", color="#9B7BFF", accepts=PDF, page="forms",
      workflow=False, new=True,
      desc="Detect form fields automatically, create interactive fillable PDFs, or fill PDF forms yourself. Add text "
           "fields, checkboxes, multiple choice fields, and lists.")
def forms(files, out_dir, p, progress):
    raise RuntimeError("Use the Forms screen")


@tool(id="flatten", name="Flatten PDF", category=EDIT, icon="layers", color="#9B7BFF", accepts=PDF,
      desc="Make form fields and annotations part of the page so they can't be changed.")
def flatten(files, out_dir, p, progress):
    import pypdfium2 as pdfium
    dest = out_name(files[0], out_dir, "flattened")
    doc = pdfium.PdfDocument(str(files[0]))
    try:
        doc.init_forms()
    except Exception:
        pass
    for i in range(len(doc)):
        page = doc[i]
        try:
            page.flatten()
        except Exception:
            pass
    doc.save(str(dest))
    doc.close()
    return [dest]

