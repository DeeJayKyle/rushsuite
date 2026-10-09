"""Optimize PDF: compress, repair, PDF/A."""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pikepdf

from .. import paths
from .registry import PDF, Param, tool
from .util import open_pdf, out_name

OPT = "Optimize PDF"
LEVELS = {  # name: (max image side px, jpeg quality, ghostscript preset)
    "Extreme compression": (1100, 45, "/screen"),
    "Recommended compression": (1650, 65, "/ebook"),
    "Less compression": (2400, 82, "/printer"),
}
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _recompress_images(pdf: pikepdf.Pdf, max_side: int, quality: int, progress) -> int:
    from PIL import Image
    images = [o for o in pdf.objects if isinstance(o, pikepdf.Stream) and o.get("/Subtype") == "/Image"]
    changed = 0
    for k, obj in enumerate(images):
        if k % 5 == 0:
            progress(0.05 + 0.75 * k / max(1, len(images)), f"Optimizing image {k + 1}/{len(images)}")
        try:
            if obj.get("/ImageMask", False) or int(obj.get("/BitsPerComponent", 8)) < 8 or "/Decode" in obj:
                continue
            filt = obj.get("/Filter")
            filters = [str(f) for f in (filt if isinstance(filt, pikepdf.Array) else [filt])] if filt else []
            if any(f in ("/JBIG2Decode", "/CCITTFaxDecode", "/JPXDecode") for f in filters):
                continue
            raw_len = len(obj.read_raw_bytes())
            if raw_len < 20_000:
                continue
            pil = pikepdf.PdfImage(obj).as_pil_image()
            if pil.mode in ("1", "P", "LA", "RGBA", "CMYK", "I", "I;16", "F"):
                pil = pil.convert("L" if pil.mode in ("1", "LA", "I", "I;16", "F") else "RGB")
            w, h = pil.size
            scale = min(1.0, max_side / max(w, h))
            if scale < 1.0:
                pil = pil.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
            buf = io.BytesIO()
            pil.save(buf, "JPEG", quality=quality, optimize=True, progressive=False)
            data = buf.getvalue()
            if len(data) >= raw_len * 0.92:
                continue
            obj.write(data, filter=pikepdf.Name.DCTDecode)
            obj.Width, obj.Height = pil.size[0], pil.size[1]
            obj.ColorSpace = pikepdf.Name.DeviceGray if pil.mode == "L" else pikepdf.Name.DeviceRGB
            obj.BitsPerComponent = 8
            for key in ("/DecodeParms", "/Intent"):
                if key in obj:
                    del obj[key]
            changed += 1
        except Exception:
            continue
    return changed


def ghostscript_pdfwrite(src: Path, dest: Path, extra: list[str]) -> bool:
    gs = paths.ghostscript()
    if not gs:
        return False
    cmd = [gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", *extra, f"-sOutputFile={dest}", str(src)]
    r = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW, timeout=1800)
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0


@tool(id="compress", name="Compress PDF", category=OPT, icon="compress", color="#3DDC97", accepts=PDF,
      desc="Reduce file size while optimizing for maximal PDF quality.",
      params=[Param("level", "Compression level", "choice", "Recommended compression", list(LEVELS)),
              Param("gray", "Convert to grayscale", "bool", False)])
def compress(files, out_dir, p, progress):
    src = files[0]
    max_side, q, preset = LEVELS[p["level"]]
    progress(0.02, "Reading")
    pdf = open_pdf(src)
    _recompress_images(pdf, max_side, q, progress)
    try:
        pdf.remove_unreferenced_resources()
    except Exception:
        pass
    progress(0.85, "Saving")
    dest = out_name(src, out_dir, "compressed")
    pdf.save(str(dest), compress_streams=True, recompress_flate=True,
             object_stream_mode=pikepdf.ObjectStreamMode.generate)
    pdf.close()
    if p.get("gray") or paths.ghostscript():
        tmp = Path(tempfile.mkdtemp()) / "gs.pdf"
        extra = [f"-dPDFSETTINGS={preset}", "-dCompatibilityLevel=1.6", "-dDetectDuplicateImages=true"]
        if p.get("gray"):
            extra += ["-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray"]
        progress(0.9, "Extra pass with Ghostscript")
        if ghostscript_pdfwrite(dest, tmp, extra) and (p.get("gray") or tmp.stat().st_size < dest.stat().st_size):
            shutil.move(str(tmp), dest)
    if dest.stat().st_size >= src.stat().st_size and not p.get("gray"):
        shutil.copyfile(src, dest)            # never return a bigger file
    return [dest]


def describe_saving(src: Path, dest: Path) -> str:
    a, b = src.stat().st_size, dest.stat().st_size
    return f"{a / 1e6:.2f} MB → {b / 1e6:.2f} MB ({100 * (a - b) / max(1, a):.0f}% smaller)"


@tool(id="repair", name="Repair PDF", category=OPT, icon="repair", color="#3DDC97", accepts=PDF,
      desc="Repair a damaged PDF and recover data from corrupt PDF. Fix PDF files with our Repair tool.")
def repair(files, out_dir, p, progress):
    src = files[0]
    dest = out_name(src, out_dir, "repaired")
    errors = []

    def valid(path) -> bool:
        try:
            with pikepdf.open(str(path)) as chk:
                return len(chk.pages) > 0
        except Exception:
            return False

    progress(0.1, "Rebuilding with qpdf")
    try:
        with pikepdf.open(str(src), attempt_recovery=True) as pdf:
            pdf.save(str(dest), fix_metadata_version=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        if valid(dest):
            return [dest]
        errors.append("qpdf: rebuilt file was not usable")
    except Exception as e:  # noqa: BLE001
        errors.append(f"qpdf: {e}")
    progress(0.25, "Rebuilding the document catalogue")
    try:   # trailer lost (e.g. truncated download): point a new trailer at the catalogue object
        import re
        raw = src.read_bytes()
        m = None
        for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\s*<<(?:(?!endobj).){0,400}?/Type\s*/Catalog", raw, re.S):
            pass
        if m:
            patched = raw + (b"\nendstream\nendobj\n" if raw.rstrip().endswith(b"stream") is False and
                             raw.count(b"stream") > raw.count(b"endstream") else b"\n")
            patched += b"trailer\n<< /Root %s %s R /Size 100000 >>\n%%%%EOF\n" % (m.group(1), m.group(2))
            with pikepdf.open(io.BytesIO(patched), attempt_recovery=True) as pdf:
                pdf.save(str(dest), fix_metadata_version=True)
            if valid(dest):
                return [dest]
    except Exception as e:  # noqa: BLE001
        errors.append(f"catalogue: {e}")
    progress(0.4, "Rebuilding with PDFium")
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(src))
        doc.save(str(dest))
        doc.close()
        if valid(dest):
            return [dest]
        errors.append("pdfium: rebuilt file was not usable")
    except Exception as e:  # noqa: BLE001
        errors.append(f"pdfium: {e}")
    progress(0.7, "Salvaging pages")
    try:
        from pypdf import PdfReader, PdfWriter
        r = PdfReader(str(src), strict=False)
        w = PdfWriter()
        for pg in r.pages:
            try:
                w.add_page(pg)
            except Exception:
                continue
        with open(dest, "wb") as f:
            w.write(f)
        if len(w.pages) and valid(dest):
            return [dest]
    except Exception as e:  # noqa: BLE001
        errors.append(f"pypdf: {e}")
    raise RuntimeError("This PDF is too damaged to recover.\n\n" + "\n".join(errors))


def _srgb_icc() -> bytes:
    from PIL import ImageCms
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@tool(id="pdfa", name="PDF to PDF/A", category=OPT, icon="archive", color="#3DDC97", accepts=PDF,
      desc="Transform your PDF to PDF/A, the ISO-standardized version of PDF for long-term archiving.",
      params=[Param("level", "Conformance", "choice", "PDF/A-2b", ["PDF/A-1b", "PDF/A-2b", "PDF/A-3b"])])
def pdfa(files, out_dir, p, progress):
    src = files[0]
    part = p["level"][6]
    dest = out_name(src, out_dir, f"pdfa{part}")
    progress(0.1, "Converting")
    if paths.ghostscript():
        ok = ghostscript_pdfwrite(src, dest, [f"-dPDFA={part}", "-dPDFACompatibilityPolicy=1",
                                              "-sColorConversionStrategy=RGB", "-dEmbedAllFonts=true"])
        if ok:
            return [dest]
    # Built-in fallback: PDF/A identification, sRGB output intent, no encryption/JavaScript.
    pdf = open_pdf(src)
    root = pdf.Root
    for k in ("/OpenAction", "/AA"):
        if k in root:
            del root[k]
    if "/Names" in root and "/JavaScript" in root.Names:
        del root.Names["/JavaScript"]
    icc = pdf.make_stream(_srgb_icc())
    icc.N = 3
    root.OutputIntents = pikepdf.Array([pikepdf.Dictionary(
        Type=pikepdf.Name.OutputIntent, S=pikepdf.Name.GTS_PDFA1, OutputConditionIdentifier="sRGB IEC61966-2.1",
        Info="sRGB IEC61966-2.1", DestOutputProfile=icc)])
    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta["pdfaid:part"] = part
        meta["pdfaid:conformance"] = "B"
    pdf.save(str(dest), fix_metadata_version=True, object_stream_mode=pikepdf.ObjectStreamMode.disable)
    return [dest]

