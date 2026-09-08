"""YAML Frontmatter の読み書き（選択中プリセット状態＝単一ソースの正）.

Frontmatter 例::

    ---
    title: ログイン仕様
    mdflow:
      selected:
        flow-login: 管理者・正常
    ---

本文の mdflow-mapping にプリセット定義を置き、「今どれを選択中か」だけを
ここに保持する（役割分担でFrontmatterの肥大化を避ける）。
"""
from __future__ import annotations

import re
from typing import Any

import yaml

_FM_RE = re.compile(r"^﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)


def parse(md_text: str) -> tuple[dict[str, Any], str]:
    """(meta, body) を返す。Frontmatter が無ければ ({}, 元テキスト)."""
    m = _FM_RE.match(md_text)
    if not m:
        return {}, md_text
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        meta = {}
    body = md_text[m.end():]
    return meta, body


def dump(meta: dict[str, Any], body: str) -> str:
    """meta を Frontmatter として付与した Markdown 文字列を返す."""
    if not meta:
        return body
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).rstrip("\n")
    return f"---\n{fm}\n---\n{body}"


def get_selected(meta: dict[str, Any]) -> dict[str, str]:
    """diagram_id -> 選択プリセット名 の辞書を返す."""
    sel = (meta.get("mdflow") or {}).get("selected") or {}
    return {str(k): str(v) for k, v in sel.items()}


def set_selected(meta: dict[str, Any], diagram_id: str, preset: str) -> dict[str, Any]:
    """選択プリセットを meta に反映して返す（in-place かつ返り値でも）."""
    mdflow = meta.setdefault("mdflow", {})
    selected = mdflow.setdefault("selected", {})
    selected[diagram_id] = preset
    return meta
