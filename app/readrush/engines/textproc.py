"""Text preparation for listening: sentence segmentation with character offsets (for
highlighting), cleanup of things that sound bad when read aloud, and word timing estimates."""
from __future__ import annotations

import re
from dataclasses import dataclass

ABBREV = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "fig", "no", "vol",
          "pp", "ca", "approx", "dept", "inc", "ltd", "co", "jan", "feb", "mar", "apr", "jun", "jul", "aug",
          "sep", "sept", "oct", "nov", "dec", "al", "u.s", "u.k", "mt", "gen", "col", "lt", "sgt", "rev"}

_CITATION = re.compile(r"\s?\[(?:\d+(?:[–,\-–\s]*\d+)*|[a-z])\]|\s?\((?:[A-Z][A-Za-z'\-]+(?: et al\.)?(?:,| and| &)?\s?)+\d{4}[a-z]?\)")
_URL = re.compile(r"https?://\S+|www\.\S+")
_WORD = re.compile(r"[\w'’\-]+|[^\w\s]", re.UNICODE)


@dataclass
class Sentence:
    start: int
    end: int
    text: str            # original text slice

    def words(self) -> list[tuple[int, int]]:
        """Absolute (start, end) offsets of the words in this sentence."""
        return [(self.start + m.start(), self.start + m.end())
                for m in re.finditer(r"[\w'’\-]+", self.text, re.UNICODE)]


def normalize_document(text: str) -> str:
    """Clean extracted text: join hyphenated line breaks, unwrap hard-wrapped lines,
    keep paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)             # infor-\nmation
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    # a single newline inside a paragraph -> space (when the line doesn't end a sentence)
    text = re.sub(r"(?<![.!?:;\"”’)\]])\n(?!\n)(?=[a-z0-9(“\"'])", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def speakable(s: str, skip_citations: bool = True) -> str:
    """Version of a sentence that is sent to the voice engine."""
    if skip_citations:
        s = _CITATION.sub("", s)
    s = _URL.sub(" link ", s)
    s = s.replace("&", " and ").replace("•", " ").replace("|", " ")
    s = re.sub(r"[_*#~^=<>]{2,}", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _is_abbrev(text: str, dot_index: int) -> bool:
    m = re.search(r"([A-Za-z.]+)$", text[:dot_index])
    if not m:
        return False
    w = m.group(1).lower().rstrip(".")
    return w in ABBREV or (len(w) == 1 and w.isalpha())      # initials: "J. K. Rowling"


def segment(text: str, max_len: int = 280) -> list[Sentence]:
    """Split into sentences (and paragraph lines); long sentences are cut at , ; : — ."""
    out: list[Sentence] = []
    n = len(text)
    i = 0
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        j = i
        end = None
        while j < n:
            c = text[j]
            if c == "\n":
                end = j
                break
            if c in ".!?…。！？":
                k = j + 1
                while k < n and text[k] in ".!?…\"”’')]":
                    k += 1
                if k >= n or text[k].isspace():
                    nxt = k
                    while nxt < n and text[nxt] == " ":
                        nxt += 1
                    lower_next = nxt < n and (text[nxt].islower() or text[nxt].isdigit())
                    if (c == "." and _is_abbrev(text, j)) or (lower_next and c in ".…"):
                        j = k
                        continue
                    end = k
                    break
                j = k
                continue
            j += 1
        if end is None:
            end = n
        chunk = text[i:end]
        if chunk.strip():
            out.extend(_split_long(i, chunk, max_len))
        i = end
    return out


def _split_long(start: int, chunk: str, max_len: int) -> list[Sentence]:
    stripped = chunk.rstrip()
    if len(stripped) <= max_len:
        return [Sentence(start, start + len(stripped), stripped)]
    parts: list[Sentence] = []
    s = 0
    while len(stripped) - s > max_len:
        window = stripped[s:s + max_len]
        cut = max(window.rfind(", "), window.rfind("; "), window.rfind(": "), window.rfind(" — "),
                  window.rfind(" - "))
        if cut < max_len // 3:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = max_len
        cut += 1
        piece = stripped[s:s + cut].rstrip()
        parts.append(Sentence(start + s, start + s + len(piece), piece))
        s += cut
        while s < len(stripped) and stripped[s] == " ":
            s += 1
    if s < len(stripped):
        parts.append(Sentence(start + s, start + len(stripped), stripped[s:]))
    return parts


def word_times(sentence: Sentence, duration: float) -> list[tuple[float, int, int]]:
    """Estimated (start_time, char_start, char_end) for each word, proportional to word length
    plus small pauses after punctuation. Good enough for smooth follow-along highlighting."""
    words = sentence.words()
    if not words or duration <= 0:
        return []
    weights = []
    for k, (a, b) in enumerate(words):
        w = (b - a) + 1.5
        nxt = sentence.text[b - sentence.start: b - sentence.start + 2]
        if nxt[:1] in ",;:":
            w += 3
        elif nxt[:1] in ".!?":
            w += 4
        weights.append(w)
    total = sum(weights)
    lead = 0.04 * duration
    usable = duration * 0.94
    t = lead
    out = []
    for (a, b), w in zip(words, weights):
        out.append((t, a, b))
        t += usable * w / total
    return out


def chunk_text(text: str, max_chars: int = 6000, overlap: int = 200) -> list[str]:
    """Paragraph-aware chunks for AI processing."""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= max_chars:
            cur = f"{cur}\n\n{p}" if cur else p
            continue
        if cur:
            chunks.append(cur)
        while len(p) > max_chars:
            chunks.append(p[:max_chars])
            p = p[max_chars - overlap:]
        cur = p
    if cur:
        chunks.append(cur)
    return chunks or [text[:max_chars]]


def clean_dictation(text: str) -> str:
    """Remove filler words / stutters and tidy capitalisation for voice typing."""
    t = " " + text.strip() + " "
    t = re.sub(r"(?i)(?<=[\s,])(um+|uh+|erm+|er|ah+|hmm+|mm+|uh-huh)(?=[\s,.!?])[,]?", " ", t)
    t = re.sub(r"(?i)\b(you know|i mean|kind of|sort of),\s", " ", t)
    t = re.sub(r"(?i)\b(\w+)(\s+\1\b)+", r"\1", t)              # "the the" -> "the"
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    t = re.sub(r"\bi\b", "I", t)
    if t and t[-1] not in ".!?…":
        t += "."
    return t
