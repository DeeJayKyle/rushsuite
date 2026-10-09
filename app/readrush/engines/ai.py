"""AI features built on llm.chat: summaries, Q&A, quizzes, recaps, explanations, polished
voice notes, meeting notes and podcast scripts. Long documents are processed in chunks."""
from __future__ import annotations

import json
import re
from typing import Callable

from .. import paths
from . import llm, retrieval, textproc

ProgressFn = Callable[[float, str], None]

SYSTEM = ("You are ReadRush, a friendly voice reading assistant. Your answers are often read aloud, so write "
          "in clear, natural sentences. Avoid tables and heavy markdown unless asked.")

LENGTHS = {"Short": "in 3-5 sentences", "Medium": "in about 2-3 short paragraphs",
           "Detailed": "as a detailed summary with a short intro and 6-10 bullet points"}


def _ask(prompt: str, system: str = SYSTEM, max_tokens: int = 900, on_token=None, status=None,
         temperature: float = 0.4) -> str:
    return llm.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    max_tokens=max_tokens, on_token=on_token, status=status, temperature=temperature).strip()


def _chunk_budget() -> int:
    # offline models on CPU: smaller chunks keep each step responsive
    return 12000 if llm.online_config() and paths.settings.get("ai_mode") != "Offline" else 5000


def _reduce(text: str, instruction: str, progress: ProgressFn) -> str:
    """Map step for long texts: compress each chunk into notes."""
    chunks = textproc.chunk_text(text, _chunk_budget())
    if len(chunks) == 1:
        return text
    notes = []
    for i, c in enumerate(chunks):
        progress(0.05 + 0.75 * i / len(chunks), f"Reading part {i + 1}/{len(chunks)}")
        notes.append(_ask(f"{instruction}\n\nTEXT (part {i + 1} of {len(chunks)}):\n{c}", max_tokens=500))
    return "\n\n".join(notes)


def summarize(text: str, length: str = "Medium", progress: ProgressFn | None = None, on_token=None) -> str:
    progress = progress or (lambda f, m: None)
    body = _reduce(text, "Write compact notes capturing every important point of this part.", progress)
    progress(0.85, "Writing summary")
    return _ask(f"Summarize the following {LENGTHS.get(length, LENGTHS['Medium'])}. Start directly with the "
                f"content (no preamble).\n\n{body}", on_token=on_token,
                status=lambda m: progress(0.85, m))


def ask(question: str, sources: list[tuple[str, str]], history: list[dict] | None = None, on_token=None,
        status=None) -> str:
    ctx = retrieval.best_context(question, sources, budget=_chunk_budget())
    context = "\n\n".join(f"[{t}]\n{p}" for t, p in ctx) or "(no documents)"
    msgs = [{"role": "system", "content": SYSTEM + " Answer using the provided document excerpts. If the answer "
             "isn't in them, say so briefly and then answer from general knowledge, clearly marked."}]
    for h in (history or [])[-6:]:
        msgs.append(h)
    msgs.append({"role": "user", "content": f"DOCUMENT EXCERPTS:\n{context}\n\nQUESTION: {question}"})
    return llm.chat(msgs, max_tokens=700, on_token=on_token, status=status).strip()


def explain(selection: str, context: str = "", on_token=None) -> str:
    ctx = f"\n\nSurrounding text:\n{context[:2500]}" if context else ""
    return _ask(f"Explain this simply, as if to a smart 15-year-old, in a short paragraph:\n\n\"{selection}\"{ctx}",
                on_token=on_token, max_tokens=400)


def recap(text_read: str, on_token=None) -> str:
    tail = text_read[-14000:]
    return _ask("I'm coming back to a reading. In 3-4 sentences, recap what I've read so far so I can continue. "
                f"Start with 'Previously,'.\n\nWHAT I READ:\n{tail}", on_token=on_token, max_tokens=300)


def _json_block(s: str):
    s = s.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        a, b = s.find(opener), s.rfind(closer)
        if a != -1 and b > a:
            try:
                return json.loads(s[a:b + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("The AI didn't return valid quiz data")


def quiz(text: str, n: int = 5, progress: ProgressFn | None = None) -> list[dict]:
    """[{question, options[4], answer (index), explanation}]"""
    progress = progress or (lambda f, m: None)
    body = _reduce(text, "List the key facts, definitions and ideas in this part as short bullet points.", progress)
    progress(0.85, "Writing questions")
    prompt = (f"Create {n} multiple-choice questions that test understanding of the material below. Return ONLY "
              'JSON: a list of objects {"question": str, "options": [4 strings], "answer": index 0-3, '
              '"explanation": one sentence}. Vary which option is correct.\n\nMATERIAL:\n' + body)
    for attempt in range(2):
        raw = _ask(prompt, system="You write high-quality study quizzes and reply with JSON only.",
                   max_tokens=1600, temperature=0.3 + 0.2 * attempt)
        try:
            data = _json_block(raw)
            if isinstance(data, dict):
                data = data.get("questions") or next(iter(data.values()))
            out = []
            for q in data:
                opts = [str(o) for o in q.get("options", [])][:4]
                ans = q.get("answer", 0)
                if isinstance(ans, str):
                    ans = next((i for i, o in enumerate(opts) if o.strip().lower() == ans.strip().lower()),
                               "ABCD".find(ans.strip()[:1].upper()))
                if len(opts) >= 2 and q.get("question"):
                    out.append({"question": str(q["question"]), "options": opts,
                                "answer": max(0, min(int(ans), len(opts) - 1)),
                                "explanation": str(q.get("explanation", ""))})
            if out:
                return out
        except Exception:
            continue
    raise ValueError("Couldn't build a quiz from this text - try again or use a longer passage.")


def polish_note(transcript: str) -> str:
    return _ask("Turn this voice transcript into a clean, well-organised note. Keep the speaker's meaning and "
                "wording where possible; fix grammar; remove filler. Start with a short title line, then the note "
                f"(use bullet points for lists).\n\nTRANSCRIPT:\n{transcript}", max_tokens=1200)


def polish_dictation(text: str) -> str:
    return _ask("Fix grammar, punctuation and filler words in this dictated text. Keep the meaning and tone. "
                f"Reply with the corrected text only.\n\n{text}",
                system="You are a precise copy editor. Output only the corrected text.", max_tokens=800,
                temperature=0.1)


def meeting_notes(transcript: str, progress: ProgressFn | None = None) -> str:
    progress = progress or (lambda f, m: None)
    body = _reduce(transcript, "Write detailed notes of this part of a meeting: topics, decisions, tasks with "
                               "owners, numbers and dates.", progress)
    progress(0.85, "Writing meeting notes")
    return _ask("Write meeting notes from the material below using these headings:\nSummary\nKey points\n"
                "Decisions\nAction items (who - what - when)\nOpen questions\nKeep it concise and factual."
                f"\n\nMATERIAL:\n{body}", max_tokens=1400, system="You are an expert meeting note taker.")


STYLES = {
    "Friendly chat": "two friends chatting warmly and casually, with humour and everyday examples",
    "Deep dive": "two experts doing a thorough, insightful deep dive with nuance",
    "Debate": "two hosts who take opposing sides and debate respectfully",
    "Lesson": "a teacher explaining clearly to a curious student who asks good questions",
    "News brief": "two news anchors giving a crisp, fast-paced briefing",
}


def podcast_script(source: str, topic: str, style: str, minutes: int, host_a: str, host_b: str,
                   progress: ProgressFn | None = None) -> list[tuple[str, str]]:
    progress = progress or (lambda f, m: None)
    words = int(minutes * 150)
    material = _reduce(source, "Write detailed notes of the interesting facts and ideas in this part.", progress) \
        if source.strip() else ""
    progress(0.8, "Writing the podcast script")
    prompt = (f"Write a podcast episode script of about {words} words between {host_a} and {host_b}, styled as "
              f"{STYLES.get(style, STYLES['Friendly chat'])}. "
              + (f"Topic: {topic}. " if topic else "")
              + "Open with a hook, cover the material in a natural flowing conversation (short turns, reactions, "
              "questions), and close with a quick recap. Format every line exactly as 'NAME: text' using only the two "
              "names. No stage directions, no sound effects, no markdown."
              + (f"\n\nMATERIAL:\n{material}" if material else ""))
    raw = _ask(prompt, system="You are an award-winning podcast writer.", max_tokens=min(4000, words * 2 + 400),
               temperature=0.8)
    lines = []
    for ln in raw.splitlines():
        m = re.match(r"\s*\**\s*([^:*]{1,30}?)\s*\**\s*:\s*(.+)", ln)
        if not m:
            if lines and ln.strip():
                lines[-1] = (lines[-1][0], lines[-1][1] + " " + ln.strip())
            continue
        name, text = m.group(1).strip(), m.group(2).strip()
        speaker = host_b if name.lower().startswith(host_b.lower()[:4]) else host_a
        text = re.sub(r"[\[(][^\])]*[\])]", "", text)
        text = re.sub(r"^[\s*_]+|[*_]+$", "", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text:
            lines.append((speaker, text))
    if len(lines) < 4:
        raise ValueError("The AI didn't produce a usable script - please try again.")
    return lines


def title_for(text: str) -> str:
    try:
        t = _ask(f"Give a short title (max 6 words) for this. Reply with the title only.\n\n{text[:3000]}",
                 max_tokens=24, temperature=0.2)
        return t.strip().strip('"').splitlines()[0][:70]
    except Exception:
        first = text.strip().split("\n", 1)[0]
        return first[:50]
