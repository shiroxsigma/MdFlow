"""Markdown 内の Mermaid ブロック抽出、ノードID解析、動的スタイル注入.

方針:
- 元コードは書き換えず、末尾に classDef/class を付与して描画する（非破壊）。
- ノードIDの実在を検証し、存在しないIDへの適用は呼び出し側で警告できるよう返す。
- 対応図は flowchart（graph/flowchart）。他種別はノードclassが効かないため対象外。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ```mermaid ... ``` ブロック（インデントフェンス非対応・素直な形のみ）
_FENCE_RE = re.compile(
    r"^```[ \t]*mermaid[ \t]*\n(.*?)^```", re.DOTALL | re.MULTILINE
)
_ID_COMMENT_RE = re.compile(r"^\s*%%\s*id\s*:\s*(\S+)", re.MULTILINE)

# flowchart のノードID抽出用
_SHAPE_RE = re.compile(r"\b([A-Za-z_][\w-]*)\s*[\[\(\{]")
_ARROW_RE = re.compile(
    r"([A-Za-z_][\w-]*)\s*(?:-{2,3}>|-{2,3}|={2,3}>|-\.->|-\.-)\s*"
    r"(?:\|[^|]*\|\s*)?([A-Za-z_][\w-]*)"
)
_FLOWCHART_HEAD_RE = re.compile(r"^\s*(graph|flowchart)\b", re.IGNORECASE)
_NODE_SHAPE_RE = re.compile(
    r"\b([A-Za-z_][\w-]*)\s*(?:\[\[[^]]*\]\]|\[\([^)]*\)\]|\[[^]]*\]|\([^)]*\)|\{[^}]*\})"
)
_EDGE_RE = re.compile(
    r"(?=\b([A-Za-z_][\w-]*)\s*(?:-->|---|==>|-\.->)\s*"
    r"(?:\|[^|]*\|\s*)?([A-Za-z_][\w-]*)\b)"
)

_RESERVED = {
    "graph", "flowchart", "subgraph", "end", "classDef", "class",
    "style", "linkStyle", "click", "direction", "TB", "TD", "BT", "LR", "RL",
}


@dataclass
class MermaidBlock:
    """Markdown 内の 1 つの mermaid コードブロック."""

    diagram_id: str
    code: str            # フェンス内の生コード（末尾スタイル注入前）
    start: int           # フェンス開始（```）の文字オフセット
    end: int             # フェンス終端（```）直後の文字オフセット
    index: int = 0       # 出現順（id が無いブロックの識別に使う）

    @property
    def label(self) -> str:
        return self.diagram_id or f"#{self.index}"


def extract_blocks(md_text: str) -> list[MermaidBlock]:
    """本文中のすべての mermaid ブロックを抽出する."""
    blocks: list[MermaidBlock] = []
    for i, m in enumerate(_FENCE_RE.finditer(md_text)):
        code = m.group(1)
        idm = _ID_COMMENT_RE.search(code)
        diagram_id = idm.group(1) if idm else ""
        blocks.append(
            MermaidBlock(
                diagram_id=diagram_id,
                code=code.rstrip("\n"),
                start=m.start(),
                end=m.end(),
                index=i,
            )
        )
    return blocks


def is_flowchart(code: str) -> bool:
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        return bool(_FLOWCHART_HEAD_RE.match(stripped))
    return False


def parse_node_ids(code: str) -> set[str]:
    """flowchart コードから宣言されているノードIDの集合を返す（ヒューリスティック）."""
    return set(node_ids_ordered(code))


def node_ids_ordered(code: str) -> list[str]:
    """ノードIDを初出順で返す（登録フォームのチェックボックス列挙用）."""
    seen: dict[str, None] = {}
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        for m in _ARROW_RE.finditer(stripped):
            for gid in (m.group(1), m.group(2)):
                if gid not in _RESERVED:
                    seen.setdefault(gid, None)
        for m in _SHAPE_RE.finditer(stripped):
            gid = m.group(1)
            if gid not in _RESERVED:
                seen.setdefault(gid, None)
    return list(seen.keys())


@dataclass
class FlowPaths:
    """flowchart の開始ノードから終了ノードまでの有限な単純経路."""

    paths: list[list[str]] = field(default_factory=list)
    truncated: bool = False
    has_cycle: bool = False


def flow_edges(code: str) -> list[tuple[str, str]]:
    """Mermaid flowchart の辺を記述順で抽出する.

    ノード形状、``-->|label|``、連結記法 ``A-->B-->C`` を扱う。
    Mermaid 全文法のパーサではなく、経路プリセット生成用の安全な
    ヒューリスティックとして未知の記法は無視する。
    """
    edges: list[tuple[str, str]] = []
    for raw in code.splitlines():
        line = raw.split("%%", 1)[0].strip()
        if not line or _FLOWCHART_HEAD_RE.match(line):
            continue
        # A[Start] --> B{Choice} の表示文字を除き、IDだけに正規化する。
        normalized = _NODE_SHAPE_RE.sub(r"\1", line)
        # Mermaidの旧形式ラベル: A -- label --> B
        normalized = re.sub(r"--\s+[^-\n]+?\s+-->", "-->", normalized)
        for match in _EDGE_RE.finditer(normalized):
            edge = (match.group(1), match.group(2))
            if edge[0] not in _RESERVED and edge[1] not in _RESERVED and edge not in edges:
                edges.append(edge)
    return edges


def enumerate_flow_paths(code: str, *, limit: int = 100) -> FlowPaths:
    """開始から終了までの全単純経路を列挙する（最大 ``limit`` 件）."""
    if not is_flowchart(code):
        return FlowPaths()
    edges = flow_edges(code)
    nodes = node_ids_ordered(code)
    if not nodes:
        return FlowPaths()
    outgoing: dict[str, list[str]] = {node: [] for node in nodes}
    incoming: dict[str, int] = {node: 0 for node in nodes}
    for source, target in edges:
        outgoing.setdefault(source, []).append(target)
        outgoing.setdefault(target, [])
        incoming.setdefault(source, 0)
        incoming[target] = incoming.get(target, 0) + 1
    roots = [node for node in outgoing if incoming.get(node, 0) == 0]
    result = FlowPaths()
    # 循環だけの図にも診断可能な経路を返す。
    if not roots:
        roots = [next(iter(outgoing))]
        result.has_cycle = True

    def visit(node: str, path: list[str]) -> None:
        if len(result.paths) >= limit:
            result.truncated = True
            return
        next_nodes = outgoing.get(node, [])
        unvisited = [target for target in next_nodes if target not in path]
        if len(unvisited) != len(next_nodes):
            result.has_cycle = True
        if not unvisited:
            result.paths.append(path)
            return
        for target in unvisited:
            visit(target, [*path, target])

    for root in roots:
        visit(root, [root])
        if result.truncated:
            break
    return result


@dataclass
class InjectionResult:
    code: str                       # スタイル注入済みコード
    missing: list[str] = field(default_factory=list)  # 実在しない指定ID


def inject_style(
    code: str,
    active_nodes: list[str],
    style: str,
    *,
    class_name: str = "mdflowActive",
    validate: bool = True,
) -> InjectionResult:
    """末尾に classDef/class を付与してハイライトする（元コードは非破壊）.

    validate=True かつ flowchart のとき、実在しないノードIDは適用対象から除外し
    missing に積んで返す（呼び出し側で UI 警告に使う）。
    """
    base = code.rstrip("\n")
    if not active_nodes:
        return InjectionResult(code=base, missing=[])

    missing: list[str] = []
    targets = list(dict.fromkeys(active_nodes))  # 重複除去・順序維持
    if validate and is_flowchart(code):
        present = parse_node_ids(code)
        applied = [n for n in targets if n in present]
        missing = [n for n in targets if n not in present]
        targets = applied

    if not targets:
        return InjectionResult(code=base, missing=missing)

    lines = [base, "", f"classDef {class_name} {style};", f"class {','.join(targets)} {class_name};"]
    return InjectionResult(code="\n".join(lines), missing=missing)


def block_by_id(blocks: list[MermaidBlock], diagram_id: str) -> Optional[MermaidBlock]:
    for b in blocks:
        if b.diagram_id == diagram_id:
            return b
    return None
