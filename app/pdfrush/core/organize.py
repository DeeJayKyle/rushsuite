"""Organize PDF: merge, split, rotate, remove/extract pages, reorder (Organize page)."""
from __future__ import annotations

import math
from pathlib import Path

import pikepdf

from .registry import PDF, Param, tool
from .util import open_pdf, out_name, parse_pages, save, unique

ORG = "Organize PDF"


@tool(id="merge", name="Merge PDF", category=ORG, icon="merge", color="#FF6B6B", accepts=PDF + [".jpg", ".jpeg", ".png"],
      combine=True, min_files=2,
      desc="Combine PDFs in the order you want with the easiest PDF merger available.",
      params=[Param("name", "Output name", "text", "merged"),
              Param("bookmarks", "Add a bookmark for each file", "bool", True)])
def merge(files, out_dir, p, progress):
    out = pikepdf.new()
    outline_items = []
    keep = []                      # keep sources open until saved
    for i, f in enumerate(files):
        progress(i / len(files), f"Adding {f.name}")
        if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
            from .convert import images_to_pdf_bytes
            src = pikepdf.open(images_to_pdf_bytes([f]))
        else:
            src = open_pdf(f)
        keep.append(src)
        start = len(out.pages)
        out.pages.extend(src.pages)
        outline_items.append((f.stem, start))
    if p.get("bookmarks"):
        with out.open_outline() as ol:
            for title, start in outline_items:
                ol.root.append(pikepdf.OutlineItem(title, start))
    dest = unique(Path(out_dir) / f"{(p.get('name') or 'merged').removesuffix('.pdf')}.pdf")
    progress(0.95, "Saving")
    return [save(out, dest)]


@tool(id="split", name="Split PDF", category=ORG, icon="split", color="#FF6B6B", accepts=PDF,
      desc="Separate one page or a whole set for easy conversion into independent PDF files.",
      params=[Param("mode", "Split", "choice", "Custom ranges",
                    ["Custom ranges", "Every N pages", "Extract every page", "Into equal parts", "By file size"]),
              Param("ranges", "Ranges (one file each)", "text", "1-3, 4-6",
                    hint="Each comma-separated range becomes its own PDF", show_if=("mode", "Custom ranges")),
              Param("every", "Pages per file", "int", 2, minimum=1, maximum=1000, show_if=("mode", "Every N pages")),
              Param("parts", "Number of parts", "int", 2, minimum=2, maximum=500, show_if=("mode", "Into equal parts")),
              Param("max_mb", "Max size per file (MB)", "float", 5.0, minimum=0.1, maximum=2000,
                    show_if=("mode", "By file size"))])
def split(files, out_dir, p, progress):
    src = open_pdf(files[0])
    n = len(src.pages)
    mode = p["mode"]
    if mode == "Custom ranges":
        groups = [parse_pages(r, n) for r in str(p.get("ranges", "")).split(",") if r.strip()]
    elif mode == "Every N pages":
        k = max(1, int(p.get("every", 1)))
        groups = [list(range(i, min(n, i + k))) for i in range(0, n, k)]
    elif mode == "Into equal parts":
        parts = max(1, min(n, int(p.get("parts", 2))))
        size = math.ceil(n / parts)
        groups = [list(range(i, min(n, i + size))) for i in range(0, n, size)]
    elif mode == "By file size":
        return _split_by_size(src, files[0], out_dir, float(p.get("max_mb", 5)), progress)
    else:
        groups = [[i] for i in range(n)]
    outs = []
    for gi, g in enumerate(g for g in groups if g):
        progress(gi / max(1, len(groups)), f"Writing part {gi + 1}")
        part = pikepdf.new()
        for i in g:
            part.pages.append(src.pages[i])
        label = f"p{g[0] + 1}" if len(g) == 1 else f"p{g[0] + 1}-{g[-1] + 1}"
        outs.append(save(part, out_name(files[0], out_dir, label)))
    return outs


def _split_by_size(src, f, out_dir, max_mb, progress):
    import io
    limit = max_mb * 1e6
    outs, cur, n = [], [], len(src.pages)

    def size_of(idxs):
        tmp = pikepdf.new()
        for i in idxs:
            tmp.pages.append(src.pages[i])
        b = io.BytesIO()
        tmp.save(b, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        return b.tell()

    def flush():
        if cur:
            part = pikepdf.new()
            for i in cur:
                part.pages.append(src.pages[i])
            outs.append(save(part, out_name(f, out_dir, f"part{len(outs) + 1}")))

    for i in range(n):
        progress(i / n, f"Page {i + 1}/{n}")
        if cur and size_of(cur + [i]) > limit:
            flush()
            cur = []
        cur.append(i)
    flush()
    return outs


@tool(id="rotate", name="Rotate PDF", category=ORG, icon="rotate", color="#FF6B6B", accepts=PDF,
      desc="Rotate your PDFs the way you need them. You can even rotate multiple PDFs at once!",
      params=[Param("angle", "Rotate", "choice", "90° clockwise", ["90° clockwise", "180°", "90° counter-clockwise"]),
              Param("pages", "Pages", "pages", "all", hint="all, odd, even or e.g. 1-3, 7")])
def rotate(files, out_dir, p, progress):
    deg = {"90° clockwise": 90, "180°": 180, "90° counter-clockwise": 270}[p["angle"]]
    pdf = open_pdf(files[0])
    for i in parse_pages(p.get("pages"), len(pdf.pages)):
        pdf.pages[i].rotate(deg, relative=True)
    return [save(pdf, out_name(files[0], out_dir, "rotated"))]


@tool(id="remove_pages", name="Remove pages", category=ORG, icon="trash", color="#FF6B6B", accepts=PDF,
      desc="Delete the pages you don't need and keep the rest.",
      params=[Param("pages", "Pages to remove", "pages", "1", hint="e.g. 2, 5-7, last")])
def remove_pages(files, out_dir, p, progress):
    pdf = open_pdf(files[0])
    drop = set(parse_pages(p.get("pages"), len(pdf.pages)))
    if len(drop) >= len(pdf.pages):
        raise ValueError("That would remove every page.")
    for i in sorted(drop, reverse=True):
        del pdf.pages[i]
    return [save(pdf, out_name(files[0], out_dir, "trimmed"))]


@tool(id="extract_pages", name="Extract pages", category=ORG, icon="extract", color="#FF6B6B", accepts=PDF,
      desc="Pull selected pages into a new PDF.",
      params=[Param("pages", "Pages to keep", "pages", "1-3", hint="order is kept as typed, e.g. 5, 1-3")])
def extract_pages(files, out_dir, p, progress):
    src = open_pdf(files[0])
    idx = parse_pages(p.get("pages"), len(src.pages))
    if not idx:
        raise ValueError("No pages selected.")
    out = pikepdf.new()
    for i in idx:
        out.pages.append(src.pages[i])
    return [save(out, out_name(files[0], out_dir, "extract"))]


def build_from_refs(refs: list[tuple], out: Path) -> Path:
    """Organize page: refs = [(source_path or None for blank, page_index, extra_rotation, (w, h))]."""
    srcs: dict[str, pikepdf.Pdf] = {}
    pdf = pikepdf.new()
    for src, idx, rot, size in refs:
        if src is None:
            w, h = size or (595, 842)
            pdf.add_blank_page(page_size=(w, h))
        else:
            if src not in srcs:
                srcs[src] = open_pdf(src)
            pdf.pages.append(srcs[src].pages[idx])
        if rot:
            pdf.pages[-1].rotate(rot, relative=True)
    return save(pdf, unique(Path(out)))


@tool(id="organize", name="Organize PDF", category=ORG, icon="organize", color="#FF6B6B", accepts=PDF,
      page="organize", workflow=False,
      desc="Sort pages of your PDF file however you like. Delete PDF pages or add PDF pages to your document at "
           "your convenience.")
def organize(files, out_dir, p, progress):  # handled by the interactive page
    raise RuntimeError("Use the Organize screen")
