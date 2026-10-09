"""Workflows: chain tools (e.g. Merge -> Compress -> Watermark -> Protect) and replay them on any files."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .. import paths
from .registry import TOOLS, run_tool

PRESETS = [
    {"name": "Shrink & lock", "steps": [{"tool": "compress", "params": {}},
                                        {"tool": "protect", "params": {"password": ""}}]},
    {"name": "Scanned paper -> searchable, small PDF", "steps": [{"tool": "ocr_pdf", "params": {}},
                                                                 {"tool": "compress", "params": {}}]},
    {"name": "Merge, number & compress", "steps": [{"tool": "merge", "params": {}},
                                                   {"tool": "page_numbers", "params": {}},
                                                   {"tool": "compress", "params": {}}]},
    {"name": "Confidential copy", "steps": [{"tool": "watermark", "params": {"text": "CONFIDENTIAL"}},
                                            {"tool": "flatten", "params": {}},
                                            {"tool": "protect", "params": {"password": ""}}]},
]


def _file() -> Path:
    return paths.config_dir() / "workflows.json"


def load() -> list[dict]:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return [dict(w) for w in PRESETS]


def save_all(flows: list[dict]) -> None:
    _file().write_text(json.dumps(flows, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def chainable() -> list:
    """Tools that can be a workflow step (file in -> file out, no interactive page needed)."""
    return [t for t in TOOLS.values() if t.workflow and not t.url_input and (not t.page or t.params)]


def needs(flow: dict) -> list[tuple[int, str]]:
    """Steps whose required inputs are still empty (e.g. a password)."""
    miss = []
    for k, st in enumerate(flow.get("steps", [])):
        t = TOOLS.get(st.get("tool"))
        if t is None:
            miss.append((k, f"Unknown tool '{st.get('tool')}'"))
        elif any(p.kind == "password" and p.key == "password" for p in t.params) and t.id == "protect" \
                and not st.get("params", {}).get("password"):
            miss.append((k, "Protect PDF needs a password"))
    return miss


def run(flow: dict, files: list[Path], out_dir: Path, progress=None, overrides: dict | None = None) -> list[Path]:
    """Run each step on the previous step's outputs. Only the final files land in out_dir."""
    progress = progress or (lambda f, m: None)
    steps = flow.get("steps", [])
    if not steps:
        raise ValueError("This workflow has no steps.")
    work = Path(tempfile.mkdtemp(prefix="pdfrush_wf_"))
    cur = [Path(f) for f in files]
    try:
        for k, st in enumerate(steps):
            t = TOOLS[st["tool"]]
            params = dict(st.get("params", {}))
            params.update((overrides or {}).get(k, {}))
            params["_workflow"] = True
            inputs = [f for f in cur if f.suffix.lower() in t.accepts] or cur
            last = k == len(steps) - 1
            dest = Path(out_dir) if last else work / f"step{k + 1}"
            dest.mkdir(parents=True, exist_ok=True)

            def sub(fr, m, k=k, name=t.name):
                progress((k + fr) / len(steps), f"Step {k + 1}/{len(steps)} - {name}: {m}")
            cur = run_tool(t.id, inputs, dest, params, sub)
            if not cur:
                raise RuntimeError(f"Step {k + 1} ({t.name}) produced no files.")
        progress(1.0, "Done")
        return cur
    finally:
        shutil.rmtree(work, ignore_errors=True)
