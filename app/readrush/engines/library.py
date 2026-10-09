"""Everything you read, write, record or create - stored as small JSON files in
Documents/ReadRush/Library so it's easy to back up."""
from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import paths

KINDS = {"doc": "Document", "web": "Web page", "scan": "Scan", "text": "Text", "note": "Note",
         "meeting": "Meeting", "podcast": "Podcast"}


@dataclass
class Item:
    kind: str
    title: str
    text: str
    source: str = ""
    id: str = field(default_factory=lambda: time.strftime("%Y%m%d%H%M%S") + f"{random.randint(0, 9999):04d}")
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    progress: int = 0                  # sentence index reached while listening
    extra: dict = field(default_factory=dict)

    @property
    def words(self) -> int:
        return len(self.text.split())

    @property
    def minutes(self) -> float:
        return self.words / 170.0


def folder() -> Path:
    return paths.sub("Library")


def save(item: Item) -> Item:
    item.updated = time.time()
    p = folder() / f"{item.id}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(item), ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return item


def load(item_id: str) -> Item | None:
    try:
        return Item(**json.loads((folder() / f"{item_id}.json").read_text(encoding="utf-8")))
    except Exception:
        return None


def all_items(kinds: set[str] | None = None, query: str = "") -> list[Item]:
    out = []
    q = query.lower().strip()
    for p in folder().glob("*.json"):
        try:
            it = Item(**json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
        if kinds and it.kind not in kinds:
            continue
        if q and q not in it.title.lower() and q not in it.text[:20000].lower():
            continue
        out.append(it)
    out.sort(key=lambda i: i.updated, reverse=True)
    return out


def delete(item: Item):
    (folder() / f"{item.id}.json").unlink(missing_ok=True)
    audio = item.extra.get("audio")
    if audio:
        Path(audio).unlink(missing_ok=True)


def add_imported(imp) -> Item:
    return save(Item(imp.kind, imp.title, imp.text, imp.source, extra=dict(imp.meta)))
