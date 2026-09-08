"""条件マッピング（```mdflow-mapping``` ブロック）のパースと安全なルール評価.

ブロック例::

    ```mdflow-mapping
    diagram: flow-login
    presets:
      管理者・正常:
        when: 'role == "admin" && error_count == 0'
        active_nodes: [A, B, D]
      一般・エラー:
        when: 'role == "user" && error_count > 0'
        active_nodes: [A, C, E]
    style:
      active: 'fill:#ff9999,stroke:#333'
    ```

ルール式は eval を使わず、ast を安全に手評価する（コード実行を許さない）。
サポート演算子: ``&& || ! == != < <= > >=`` と数値/文字列/真偽リテラル。
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

_BLOCK_RE = re.compile(
    r"^```[ \t]*(?:yaml[ \t]+)?mdflow-mapping[ \t]*\r?\n(.*?)^```",
    re.DOTALL | re.MULTILINE,
)

DEFAULT_ACTIVE_STYLE = "fill:#ff9999,stroke:#333,stroke-width:2px"


class RuleError(ValueError):
    """ルール式が不正・評価不能なときに送出."""


@dataclass
class Preset:
    name: str
    when: str = ""
    active_nodes: list[str] = field(default_factory=list)
    active_edges: list[Any] = field(default_factory=list)


@dataclass
class Mapping:
    diagram_id: str
    presets: dict[str, Preset] = field(default_factory=dict)
    active_style: str = DEFAULT_ACTIVE_STYLE

    def preset_names(self) -> list[str]:
        return list(self.presets.keys())


def extract_mappings(md_text: str) -> list[Mapping]:
    """Markdown 本文からすべての mdflow-mapping ブロックを取り出す."""
    mappings: list[Mapping] = []
    for m in _BLOCK_RE.finditer(md_text):
        body = m.group(1)
        data = yaml.safe_load(body) or {}
        mappings.append(_parse_mapping(data))
    return mappings


def _parse_mapping(data: dict[str, Any]) -> Mapping:
    diagram_id = str(data.get("diagram", "") or "")
    presets: dict[str, Preset] = {}
    for name, spec in (data.get("presets") or {}).items():
        spec = spec or {}
        presets[str(name)] = Preset(
            name=str(name),
            when=str(spec.get("when", "") or ""),
            active_nodes=[str(x) for x in (spec.get("active_nodes") or [])],
            active_edges=list(spec.get("active_edges") or []),
        )
    style = (data.get("style") or {}).get("active", DEFAULT_ACTIVE_STYLE)
    return Mapping(diagram_id=diagram_id, presets=presets, active_style=str(style))


def find_mapping(mappings: list[Mapping], diagram_id: str) -> Optional[Mapping]:
    for mp in mappings:
        if mp.diagram_id == diagram_id:
            return mp
    return None


def _preset_spec(when: str, active_nodes: list[str],
                 active_edges: Optional[list] = None) -> dict[str, Any]:
    spec: dict[str, Any] = {}
    if when:
        spec["when"] = when
    spec["active_nodes"] = list(active_nodes)
    if active_edges:
        spec["active_edges"] = list(active_edges)
    return spec


def _dump_block(data: dict[str, Any]) -> str:
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip("\n")
    return "```mdflow-mapping\n" + body + "\n```"


def upsert_preset(
    md_text: str,
    diagram_id: str,
    name: str,
    when: str,
    active_nodes: list[str],
    active_edges: Optional[list] = None,
    style: Optional[str] = None,
) -> str:
    """mdflow-mapping ブロックにプリセットを追加/更新した Markdown 全文を返す.

    - 対象 diagram のブロックがあれば、その YAML を読み直して presets を更新し再直列化。
    - 無ければ新しいブロックを末尾に追記する。
    既存設計どおり「テキストとして残す（grep可能・バージョン管理容易）」を維持する。
    """
    if not name:
        raise ValueError("プリセット名は必須です")

    for m in _BLOCK_RE.finditer(md_text):
        data = yaml.safe_load(m.group(1)) or {}
        if str(data.get("diagram", "")) != diagram_id:
            continue
        presets = data.get("presets") or {}
        presets[name] = _preset_spec(when, active_nodes, active_edges)
        data["presets"] = presets
        if style:
            data.setdefault("style", {})["active"] = style
        return md_text[: m.start()] + _dump_block(data) + md_text[m.end():]

    # 見つからなければ新規ブロックを末尾へ
    data = {"diagram": diagram_id, "presets": {name: _preset_spec(when, active_nodes, active_edges)}}
    if style:
        data["style"] = {"active": style}
    sep = "" if md_text.endswith("\n") else "\n"
    return f"{md_text}{sep}\n{_dump_block(data)}\n"


def replace_generated_paths(
    md_text: str,
    diagram_id: str,
    paths: list[list[str]],
    *,
    prefix: str = "自動経路 ",
) -> str:
    """対象図の自動経路プリセットだけを置換し、手動プリセットは保持する."""
    generated = {
        f"{prefix}{index:02d}: {' → '.join(path)}": _preset_spec("", path)
        for index, path in enumerate(paths, 1)
    }
    for match in _BLOCK_RE.finditer(md_text):
        data = yaml.safe_load(match.group(1)) or {}
        if str(data.get("diagram", "")) != diagram_id:
            continue
        manual = {
            str(name): spec for name, spec in (data.get("presets") or {}).items()
            if not str(name).startswith(prefix)
        }
        data["presets"] = {**manual, **generated}
        return md_text[:match.start()] + _dump_block(data) + md_text[match.end():]

    data = {"diagram": diagram_id, "presets": generated}
    separator = "" if md_text.endswith("\n") else "\n"
    return f"{md_text}{separator}\n{_dump_block(data)}\n"


# --------------------------------------------------------------------------- #
# ルール式評価（安全な ast 手評価）
# --------------------------------------------------------------------------- #
_ALLOWED_CMP = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}


def _normalize(expr: str) -> str:
    """C風演算子を Python 風に変換（!= を壊さないよう順序に注意）."""
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)  # ! だが != ではないもの
    return expr.strip()  # 先頭に not 等が来たときの unexpected indent を防ぐ


def evaluate(expr: str, conditions: dict[str, Any]) -> bool:
    """ルール式を条件辞書に対して評価する.

    未定義の識別子は None として扱い、比較は例外にせず False に倒す。
    空文字の式は常に True（無条件プリセット）。
    """
    expr = (expr or "").strip()
    if not expr:
        return True
    try:
        tree = ast.parse(_normalize(expr), mode="eval")
    except SyntaxError as e:
        raise RuleError(f"ルール式の構文エラー: {expr!r} ({e})") from e
    return bool(_eval_node(tree.body, conditions))


def _eval_node(node: ast.AST, ctx: dict[str, Any]) -> Any:
    if isinstance(node, ast.BoolOp):
        vals = [_eval_node(v, ctx) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(vals)
        return any(vals)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, ctx)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, ctx)
            fn = _ALLOWED_CMP.get(type(op))
            if fn is None:
                raise RuleError(f"未対応の比較演算子: {type(op).__name__}")
            try:
                if not fn(left, right):
                    return False
            except TypeError:
                return False  # 型不一致（None 比較など）は False に倒す
            left = right
        return True
    if isinstance(node, ast.Name):
        return ctx.get(node.id, None)
    if isinstance(node, ast.Constant):
        return node.value
    raise RuleError(f"許可されていない式要素: {type(node).__name__}")


@dataclass
class Resolution:
    preset: str
    active_nodes: list[str]
    active_edges: list[Any]
    style: str


def resolve(
    mapping: Mapping,
    conditions: dict[str, Any],
    selected_preset: Optional[str] = None,
) -> Optional[Resolution]:
    """適用すべきプリセットを決定する.

    selected_preset があればそれを優先（Frontmatter の選択状態＝正）。
    無ければ presets を上から評価し、最初に when が真になったものを採用。
    """
    if selected_preset and selected_preset in mapping.presets:
        p = mapping.presets[selected_preset]
        return Resolution(p.name, p.active_nodes, p.active_edges, mapping.active_style)
    for p in mapping.presets.values():
        if evaluate(p.when, conditions):
            return Resolution(p.name, p.active_nodes, p.active_edges, mapping.active_style)
    return None
