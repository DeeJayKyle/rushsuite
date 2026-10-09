"""PDF engine. Call load_all() once to register every tool."""
import importlib

MODULES = ["organize", "optimize", "convert", "edit", "security", "ocr", "compare", "ai", "workflow"]
_loaded = False


def load_all() -> dict:
    global _loaded
    from .registry import TOOLS
    if not _loaded:
        for m in MODULES:
            try:
                importlib.import_module(f"{__name__}.{m}")
            except ModuleNotFoundError as e:
                if e.name and e.name.startswith(__name__):
                    continue            # module not present in this build
                raise
        _loaded = True
    return TOOLS
