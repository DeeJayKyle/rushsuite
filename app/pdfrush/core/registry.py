"""Tool registry: every PDF tool declares its inputs and options once; the UI builds its
screen from that and workflows can chain any 'file in -> file out' tool."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ProgressFn = Callable[[float, str], None]

CATEGORIES = ["Organize PDF", "Optimize PDF", "Convert to PDF", "Convert from PDF", "Edit PDF", "PDF Security",
              "PDF Intelligence"]

PDF = [".pdf"]
IMAGES = [".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".gif"]
OFFICE_WORD = [".doc", ".docx", ".odt", ".rtf", ".txt"]
OFFICE_PPT = [".ppt", ".pptx", ".odp"]
OFFICE_XLS = [".xls", ".xlsx", ".ods", ".csv"]


@dataclass
class Param:
    key: str
    label: str
    kind: str = "choice"          # choice | int | float | text | password | bool | color | pages | file | multiline
    default: object = None
    options: list = field(default_factory=list)
    hint: str = ""
    minimum: float = 0
    maximum: float = 100
    show_if: tuple | None = None  # (other_key, value or tuple of values)


@dataclass
class Tool:
    id: str
    name: str
    category: str
    desc: str
    icon: str
    color: str
    accepts: list[str]
    run: Callable | None = None   # run(files, out_dir, params, progress) -> list[Path]
    params: list[Param] = field(default_factory=list)
    combine: bool = False         # all files go into one run (merge, images->pdf, compare)
    min_files: int = 1
    max_files: int = 0            # 0 = unlimited
    page: str = ""                # custom interactive page key ('' = generic form)
    workflow: bool = True
    url_input: bool = False
    new: bool = False

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.params}


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    TOOLS[tool.id] = tool
    return tool


def tool(**kw):
    """Decorator form: @tool(id=..., name=..., ...) def run(files, out_dir, params, progress)."""
    def deco(fn):
        register(Tool(run=fn, **kw))
        return fn
    return deco


def run_tool(tool_id: str, files: list[Path], out_dir: Path, params: dict | None = None,
             progress: ProgressFn | None = None) -> list[Path]:
    t = TOOLS[tool_id]
    p = t.defaults()
    p.update(params or {})
    progress = progress or (lambda f, m: None)
    files = [Path(f) for f in files]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if t.combine or t.url_input:
        return list(t.run(files, out_dir, p, progress))
    results: list[Path] = []
    for i, f in enumerate(files):
        sub = (lambda fr, m, i=i, f=f: progress((i + fr) / len(files), f"{f.name}: {m}" if len(files) > 1 else m))
        results += list(t.run([f], out_dir, p, sub))
    progress(1.0, "Done")
    return results
