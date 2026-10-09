"""Tiny BM25 search to find the passages that answer a question (works offline, no models)."""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""a an the and or but if then else of to in on at by for with from as is are was were be been being
this that these those it its it's i you he she we they them his her our your their my me us do does did
what which who whom whose when where why how not no yes can could should would will shall may might
about into over under than so very just also there here have has had more most some any all each""".split())


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9À-ɏ]+", text.lower()) if w not in STOP and len(w) > 1]


def passages(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) < size:
            cur = f"{cur}\n{p}" if cur else p
            continue
        if cur:
            out.append(cur)
        while len(p) > size:
            cut = p.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 3 else size
            out.append(p[:cut])
            p = p[max(0, cut - overlap):]
        cur = p
    if cur:
        out.append(cur)
    return out


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.toks = [tokens(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(len(t) for t in self.toks) / max(1, len(self.toks))
        df = Counter()
        for t in self.toks:
            df.update(set(t))
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.tf = [Counter(t) for t in self.toks]

    def search(self, query: str, k: int = 5) -> list[tuple[float, int]]:
        q = tokens(query)
        scores = []
        for i, (tf, t) in enumerate(zip(self.tf, self.toks)):
            s = 0.0
            for w in q:
                if w in tf:
                    f = tf[w]
                    s += self.idf.get(w, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(t) / self.avg))
            scores.append((s, i))
        scores.sort(reverse=True)
        return [x for x in scores[:k] if x[0] > 0] or scores[:min(k, 2)]


def best_context(question: str, sources: list[tuple[str, str]], budget: int = 6000) -> list[tuple[str, str]]:
    """sources: [(title, text)] -> [(title, passage)] most relevant first, within budget chars."""
    items = [(title, p) for title, text in sources for p in passages(text)]
    if not items:
        return []
    total = sum(len(p) for _, p in items)
    if total <= budget:
        return items
    idx = BM25([p for _, p in items])
    out, used = [], 0
    for _, i in idx.search(question, k=20):
        if used + len(items[i][1]) > budget:
            continue
        out.append(items[i])
        used += len(items[i][1])
    return out
