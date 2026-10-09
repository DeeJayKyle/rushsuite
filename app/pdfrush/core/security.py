"""PDF Security: protect (AES-256), unlock, redact (true removal)."""
from __future__ import annotations

import io
import secrets
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium

from . import textlayer
from .registry import PDF, Param, tool
from .util import open_pdf, out_name, parse_pages, save, to_visual, visual_size

SEC = "PDF Security"


@tool(id="protect", name="Protect PDF", category=SEC, icon="lock", color="#4DA3FF", accepts=PDF,
      desc="Protect PDF files with a password. Encrypt PDF documents to prevent unauthorized access.",
      params=[Param("password", "Password to open", "password", ""),
              Param("allow_print", "Allow printing", "bool", True),
              Param("allow_copy", "Allow copying text", "bool", True),
              Param("allow_edit", "Allow editing", "bool", False),
              Param("owner", "Owner password (optional)", "password", "",
                    hint="Needed to change permissions later. Leave empty for a random one.")])
def protect(files, out_dir, p, progress):
    pw = p.get("password") or ""
    if not pw:
        raise ValueError("Type a password.")
    pdf = open_pdf(files[0])
    owner = p.get("owner") or secrets.token_urlsafe(18)
    allow = pikepdf.Permissions(
        print_lowres=bool(p.get("allow_print")), print_highres=bool(p.get("allow_print")),
        extract=bool(p.get("allow_copy")), accessibility=True,
        modify_other=bool(p.get("allow_edit")), modify_annotation=bool(p.get("allow_edit")),
        modify_form=bool(p.get("allow_edit")), modify_assembly=bool(p.get("allow_edit")))
    dest = out_name(files[0], out_dir, "protected")
    pdf.save(str(dest), encryption=pikepdf.Encryption(owner=owner, user=pw, R=6, allow=allow))
    return [dest]


@tool(id="unlock", name="Unlock PDF", category=SEC, icon="unlock", color="#4DA3FF", accepts=PDF,
      desc="Remove PDF password security, giving you the freedom to use your PDFs as you want.",
      params=[Param("password", "Password (if it asks for one)", "password", "",
                    hint="Only unlock files you own or are allowed to unlock.")])
def unlock(files, out_dir, p, progress):
    try:
        pdf = pikepdf.open(str(files[0]), password=p.get("password") or "")
    except pikepdf.PasswordError:
        raise ValueError(f"Wrong or missing password for {files[0].name}.") from None
    dest = out_name(files[0], out_dir, "unlocked")
    pdf.save(str(dest))
    return [dest]


# ===================================================================== redaction
def redact_file(src: Path, dest: Path, areas: dict[int, list[tuple]], dpi: int = 200, keep_text: bool = True,
                clear_metadata: bool = True, password: str = "", progress=None) -> Path:
    """Truly remove content under `areas` ({page_index: [(x0,y0,x1,y1) unrotated PDF coords]}).

    Affected pages are re-rendered as images with black boxes burned in (nothing underneath survives),
    and the remaining visible words are put back as an invisible text layer so the page stays
    searchable. Untouched pages keep their original content."""
    from PIL import ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl

    progress = progress or (lambda f, m: None)
    pdf = open_pdf(src, password)
    doc = pdfium.PdfDocument(str(src), password=password or None)
    todo = sorted(i for i, rs in areas.items() if rs and 0 <= i < len(pdf.pages))
    buf = io.BytesIO()
    c = rl.Canvas(buf)
    scale = dpi / 72
    for k, i in enumerate(todo):
        progress(k / max(1, len(todo)), f"Redacting page {i + 1}")
        page = pdf.pages[i]
        vw, vh = visual_size(page)
        img = doc[i].render(scale=scale, may_draw_forms=True).to_pil().convert("RGB")
        d = ImageDraw.Draw(img)
        sx, sy = img.width / vw, img.height / vh
        vis_rects = []
        for r in areas[i]:
            a = to_visual(page, r[0], r[1])
            b = to_visual(page, r[2], r[3])
            l, bt, rt, tp = min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])
            vis_rects.append((l, bt, rt, tp))
            d.rectangle([l * sx - 1, (vh - tp) * sy - 1, rt * sx + 1, (vh - bt) * sy + 1], fill=(0, 0, 0))
        c.setPageSize((vw, vh))
        c.drawImage(ImageReader(img), 0, 0, vw, vh)
        if keep_text:
            for w in textlayer.words(doc[i]):
                if any(textlayer.intersects(w.rect, r) for r in areas[i]):
                    continue
                vx0, vy0 = to_visual(page, w.rect[0], w.rect[1])
                vx1, vy1 = to_visual(page, w.rect[2], w.rect[3])
                l, bt, rt, tp = min(vx0, vx1), min(vy0, vy1), max(vx0, vx1), max(vy0, vy1)
                size = max(2.0, (tp - bt) * 0.9)
                t = c.beginText()
                t.setTextRenderMode(3)                       # invisible
                t.setFont("Helvetica", size)
                width = c.stringWidth(w.text, "Helvetica", size) or 1
                t.setHorizScale(max(10, min(400, 100 * (rt - l) / width)))
                t.setTextOrigin(l, bt + (tp - bt) * 0.18)
                try:
                    t.textOut(w.text)
                except Exception:
                    continue
                c.drawText(t)
        c.showPage()
    c.save()
    doc.close()
    if todo:
        buf.seek(0)
        flat = pikepdf.open(buf)
        for k, i in enumerate(todo):
            pdf.pages[i] = flat.pages[k]
    if clear_metadata:
        try:
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                for key in list(meta.keys()):
                    del meta[key]
        except Exception:
            pass
        if "/Info" in pdf.trailer:
            del pdf.trailer["/Info"]
    progress(0.95, "Saving")
    save(pdf, dest)
    return dest


def find_matches(src: Path, terms: list[str], presets: list[str], pages: str = "all", ignore_case=True,
                 password: str = "") -> dict[int, list[tuple]]:
    doc = pdfium.PdfDocument(str(src), password=password or None)
    pats = [textlayer.PRESETS[k] for k in presets if k in textlayer.PRESETS]
    out = {}
    for i in parse_pages(pages, len(doc)):
        rs = textlayer.search(doc[i], terms, pats, ignore_case)
        if rs:
            out[i] = rs
    doc.close()
    return out


@tool(id="redact", name="Redact PDF", category=SEC, icon="redact", color="#4DA3FF", accepts=PDF, page="redact",
      desc="Redact text and graphics to permanently remove sensitive information from a PDF.",
      params=[Param("terms", "Words or phrases to redact (one per line)", "multiline", ""),
              Param("emails", "Email addresses", "bool", False),
              Param("phones", "Phone numbers", "bool", False),
              Param("numbers", "Long numbers (IDs, accounts, cards)", "bool", False),
              Param("pages", "Pages", "pages", "all"),
              Param("keep_text", "Keep the rest of the page searchable", "bool", True)])
def redact(files, out_dir, p, progress):
    presets = [k for k, on in (("Email addresses", p.get("emails")), ("Phone numbers", p.get("phones")),
                               ("Long numbers (IDs, accounts, cards)", p.get("numbers"))) if on]
    terms = [t for t in str(p.get("terms", "")).splitlines() if t.strip()]
    if not terms and not presets:
        raise ValueError("Type something to redact or tick at least one category.")
    areas = find_matches(files[0], terms, presets, p.get("pages", "all"))
    if not areas:
        raise ValueError("Nothing matching was found - the PDF may be a scan (run OCR PDF first).")
    return [redact_file(files[0], out_name(files[0], out_dir, "redacted"), areas, keep_text=p.get("keep_text", True),
                        progress=progress)]

