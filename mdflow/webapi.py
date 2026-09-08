"""フロントエンド(ui.js)へ返す JSON を組む純ロジック層（PyQt非依存・テスト可能）.

app_bridge.Bridge がこれを呼び、ダイアログ等のGUI副作用だけを担当する。
"""
from __future__ import annotations

import json
from typing import Any

from . import mapping, mermaid
from .document import Document
from .payload import Payload
from .pptx_io import ImportResult


def parse_doc(md: str) -> dict[str, Any]:
    """図一覧・各図のノードID・プリセット名・保存済み選択状態を返す."""
    doc = Document(md)
    diagrams = []
    for b in doc.blocks:
        mp = doc.get_mapping(b.diagram_id)
        diagrams.append({
            "id": b.label,
            "nodes": mermaid.node_ids_ordered(b.code),
            "presets": mp.preset_names() if mp else [],
        })
    return {"diagrams": diagrams, "selected": doc.selected}


def add_preset(md: str, diagram_id: str, name: str, when: str,
               active_nodes: list[str]) -> dict[str, Any]:
    """条件（プリセット）を mdflow-mapping ブロックに登録した Markdown を返す."""
    if not diagram_id or diagram_id.startswith("#"):
        return {"error": "図に『%% id: 名前』を付けてから条件を登録してください"}
    try:
        new_md = mapping.upsert_preset(md, diagram_id, name, when, active_nodes)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    return {"md": new_md, "message": f"条件を登録: {name}"}


def render_diagram(md: str, diagram_id: str, conditions_json: str, preset: str) -> dict[str, Any]:
    """選択図の注入済みコードとメタ情報を返す."""
    doc = Document(md)
    conditions = _loads(conditions_json)
    if not diagram_id and doc.blocks:
        diagram_id = doc.blocks[0].label
    try:
        rr = doc.render(diagram_id, conditions, preset or None)
    except KeyError as e:
        return {"injected": "", "preset": "", "warnings": [str(e)],
                "active_nodes": [], "missing": []}
    return {
        "injected": rr.injected_code,
        "preset": rr.preset,
        "warnings": rr.warnings,
        "active_nodes": rr.active_nodes,
        "missing": rr.missing_nodes,
    }


def build_payload(md: str, diagram_id: str, conditions_json: str, preset: str) -> Payload:
    doc = Document(md)
    conditions = _loads(conditions_json)
    if not diagram_id and doc.blocks:
        diagram_id = doc.blocks[0].label
    return doc.build_payload(diagram_id, conditions, preset or None)


def apply_selection(md: str, diagram_id: str, preset: str) -> str:
    """選択プリセットを Frontmatter に保存した Markdown 全文を返す（正の更新）."""
    doc = Document(md)
    if preset and diagram_id:
        doc.set_selected_preset(diagram_id, preset)
        return doc.to_markdown()
    return md


def import_result_to_dict(res: ImportResult) -> dict[str, Any]:
    """PPT取込結果を、エディタ復元用の Markdown 付き dict に変換."""
    pl = res.payload
    return {
        "md": _payload_to_markdown(pl),
        "conditions": pl.conditions,
        "preset": pl.preset,
        "diagram_id": pl.diagram_id,
        "source": res.source,
        "hash_ok": res.hash_ok,
    }


def _payload_to_markdown(pl: Payload) -> str:
    """復元ペイロードから最小構成の Markdown を組み立てる."""
    did = pl.diagram_id or "restored"
    lines = ["```mermaid", pl.mermaid, "```", ""]
    if pl.active_nodes:
        lines += [
            "```mdflow-mapping",
            f"diagram: {did}",
            "presets:",
            f"  {pl.preset or '復元'}:",
            f"    active_nodes: [{', '.join(pl.active_nodes)}]",
            "```",
            "",
        ]
    return "\n".join(lines)


def _loads(s: str) -> dict[str, Any]:
    try:
        v = json.loads(s or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}
