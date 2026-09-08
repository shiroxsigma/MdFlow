"""Local relevance search for Markdown context selection."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    title: str
    text: str
    start_line: int
    score: float = 0


def chunks(markdown: str) -> list[Chunk]:
    lines = markdown.splitlines()
    starts = [(i, line.lstrip("# ").strip()) for i, line in enumerate(lines)
              if re.match(r"^#{1,6}\s+", line)]
    if not starts:
        return [Chunk("文書全体", markdown, 1)]
    result: list[Chunk] = []
    if starts[0][0] > 0:
        result.append(Chunk("前書き", "\n".join(lines[:starts[0][0]]), 1))
    for index, (start, title) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        result.append(Chunk(title, "\n".join(lines[start:end]), start + 1))
    return result


def _terms(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    words = set(re.findall(r"[a-z0-9_\-]{2,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", text.lower()))
    words.update(normalized[i:i + 2] for i in range(max(0, len(normalized) - 1)))
    return words


def retrieve(markdown: str, query: str, limit: int = 4, max_chars: int = 24_000) -> list[Chunk]:
    query_terms = _terms(query)
    ranked = []
    for chunk in chunks(markdown):
        body_terms = _terms(chunk.title + "\n" + chunk.text)
        overlap = len(query_terms & body_terms)
        title_overlap = len(query_terms & _terms(chunk.title))
        ranked.append(Chunk(chunk.title, chunk.text, chunk.start_line, overlap + title_overlap * 3))
    ranked.sort(key=lambda item: (-item.score, item.start_line))
    selected, total = [], 0
    for chunk in ranked[:max(1, limit)]:
        if selected and total + len(chunk.text) > max_chars:
            continue
        selected.append(chunk)
        total += len(chunk.text)
    return selected
