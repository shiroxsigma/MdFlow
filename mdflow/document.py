"""ドキュメント統合レイヤ: Markdown 本文と条件から、描画用コードとPPTペイロードを組む.

GUI・CLI・テストの共通入口。PyQt に依存しない純ロジックに保つ。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from . import frontmatter, mapping, mermaid
from .mermaid import MermaidBlock
from .payload import Payload


@dataclass
class RenderResult:
    block: MermaidBlock
    injected_code: str            # スタイル注入済み（WebEngineへ渡すコード）
    preset: str = ""
    active_nodes: list[str] = field(default_factory=list)
    missing_nodes: list[str] = field(default_factory=list)  # 実在しない指定ID
    warnings: list[str] = field(default_factory=list)


class Document:
    """1つの Markdown ドキュメントの状態を保持する."""

    def __init__(self, md_text: str):
        self.raw = md_text
        self.meta, self.body = frontmatter.parse(md_text)
        self.blocks = mermaid.extract_blocks(self.body)
        self.mappings = mapping.extract_mappings(self.body)
        self.selected = frontmatter.get_selected(self.meta)

    # -- 参照系 -----------------------------------------------------------
    def diagram_ids(self) -> list[str]:
        return [b.label for b in self.blocks]

    def get_block(self, diagram_id: str) -> Optional[MermaidBlock]:
        for b in self.blocks:
            if b.diagram_id == diagram_id or b.label == diagram_id:
                return b
        if not diagram_id and self.blocks:
            return self.blocks[0]
        return None

    def get_mapping(self, diagram_id: str) -> Optional[mapping.Mapping]:
        return mapping.find_mapping(self.mappings, diagram_id)

    # -- レンダリング -----------------------------------------------------
    def render(
        self,
        diagram_id: str,
        conditions: Optional[dict[str, Any]] = None,
        selected_preset: Optional[str] = None,
    ) -> RenderResult:
        """条件（またはプリセット選択）に基づきハイライト済みコードを返す."""
        block = self.get_block(diagram_id)
        if block is None:
            raise KeyError(f"diagram '{diagram_id}' が見つかりません")

        mp = self.get_mapping(block.diagram_id)
        warnings: list[str] = []
        if mp is None:
            return RenderResult(block=block, injected_code=block.code)

        # 明示された selected_preset が最優先。無ければ conditions からルール評価する。
        # （Frontmatter の保存済み選択は「初期表示状態」であり、GUI が起動時に
        #  selected_preset として明示的に渡す。render 内で暗黙参照はしない。）
        res = mapping.resolve(mp, conditions or {}, selected_preset)
        if res is None:
            warnings.append("一致するプリセットがありません（ハイライトなし）")
            return RenderResult(block=block, injected_code=block.code, warnings=warnings)

        inj = mermaid.inject_style(block.code, res.active_nodes, res.style)
        if inj.missing:
            warnings.append(
                "図に存在しないノードIDが指定されています: " + ", ".join(inj.missing)
            )
        return RenderResult(
            block=block,
            injected_code=inj.code,
            preset=res.preset,
            active_nodes=[n for n in res.active_nodes if n not in inj.missing],
            missing_nodes=inj.missing,
            warnings=warnings,
        )

    # -- PPT 連携 ---------------------------------------------------------
    def build_payload(
        self,
        diagram_id: str,
        conditions: Optional[dict[str, Any]] = None,
        selected_preset: Optional[str] = None,
    ) -> Payload:
        """PPTに埋め込む Payload を構築する（元コード＝非注入コードを保存）."""
        rr = self.render(diagram_id, conditions, selected_preset)
        return Payload(
            mermaid=rr.block.code,
            diagram_id=rr.block.diagram_id,
            preset=rr.preset,
            conditions=conditions or {},
            active_nodes=rr.active_nodes,
        ).with_hash()

    # -- 選択状態の保存（Frontmatter が正）--------------------------------
    def set_selected_preset(self, diagram_id: str, preset: str) -> None:
        self.selected[diagram_id] = preset
        frontmatter.set_selected(self.meta, diagram_id, preset)

    def to_markdown(self) -> str:
        """現在の meta（選択状態）を反映した Markdown 全文を返す."""
        return frontmatter.dump(self.meta, self.body)
