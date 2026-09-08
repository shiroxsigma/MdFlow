"""Deterministic protection and repair for LLM-authored Markdown."""
from __future__ import annotations

import re

_DIAGRAM_RE = re.compile(r"^```(?:mermaid|plantuml|puml)\s*\n.*?^```", re.MULTILINE | re.DOTALL)
_MAPPING_RE = re.compile(r"^```mdflow-mapping\s*\n.*?^```", re.MULTILINE | re.DOTALL)
_ID_RE = re.compile(r"^\s*%%\s*id\s*:\s*\S+", re.MULTILINE)


def repair(original: str, candidate: str, policy: str = "all") -> tuple[str, list[str]]:
    warnings: list[str] = []
    if policy == "text":
        candidate = _preserve_blocks(original, candidate, _DIAGRAM_RE, "図", warnings)
        candidate = _preserve_blocks(original, candidate, _MAPPING_RE, "mapping", warnings)
    elif policy == "diagram":
        diagrams = _DIAGRAM_RE.findall(candidate)
        if not diagrams:
            return original, ["編集案に図がなかったため元の内容を保持しました"]
        iterator = iter(diagrams)
        candidate = _DIAGRAM_RE.sub(lambda _: next(iterator, _.group(0)), original)
        warnings.append("図以外の文章とmappingを元の内容から復元しました")

    candidate = _restore_ids(original, candidate, warnings)
    candidate = _preserve_blocks(original, candidate, _MAPPING_RE, "mapping", warnings)
    return candidate, warnings


def _preserve_blocks(original: str, candidate: str, pattern: re.Pattern, label: str,
                     warnings: list[str]) -> str:
    originals = pattern.findall(original)
    matches = list(pattern.finditer(candidate))
    if not originals:
        return candidate
    if len(matches) < len(originals):
        warnings.append(f"不足した{label}ブロックを復元しました")
        candidate = candidate.rstrip() + "\n\n" + "\n\n".join(originals[len(matches):]) + "\n"
        matches = list(pattern.finditer(candidate))
    for match, value in reversed(list(zip(matches, originals))):
        candidate = candidate[:match.start()] + value + candidate[match.end():]
    return candidate


def _restore_ids(original: str, candidate: str, warnings: list[str]) -> str:
    original_blocks = _DIAGRAM_RE.findall(original)
    candidate_blocks = list(_DIAGRAM_RE.finditer(candidate))
    for old, match in reversed(list(zip(original_blocks, candidate_blocks))):
        old_id = _ID_RE.search(old)
        if old_id and not _ID_RE.search(match.group(0)):
            block = match.group(0)
            newline = block.find("\n") + 1
            repaired = block[:newline] + old_id.group(0).strip() + "\n" + block[newline:]
            candidate = candidate[:match.start()] + repaired + candidate[match.end():]
            warnings.append(f"図ID {old_id.group(0).split(':', 1)[1].strip()} を復元しました")
    return candidate
