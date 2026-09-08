"""コアロジックとPPT往復のテスト（GUI非依存）."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdflow import frontmatter, mapping, mermaid  # noqa: E402
from mdflow.document import Document  # noqa: E402
from mdflow.payload import Payload, decode, encode  # noqa: E402

SAMPLE = (Path(__file__).resolve().parent / "fixtures" / "login.md").read_text(
    encoding="utf-8"
)


# --------------------------------------------------------------------------- #
# payload
# --------------------------------------------------------------------------- #
def test_payload_roundtrip_and_hash():
    p = Payload(mermaid="flowchart TD\n A-->B", diagram_id="d1",
                conditions={"role": "admin"}, active_nodes=["A", "B"])
    text = encode(p)
    assert text.startswith("MDFLOW:v1:")
    back = decode(text)
    assert back.mermaid == p.mermaid
    assert back.conditions == {"role": "admin"}
    assert back.active_nodes == ["A", "B"]
    assert back.hash_ok()


def test_payload_hash_detects_tamper():
    p = Payload(mermaid="flowchart TD\n A-->B").with_hash()
    p.mermaid = "flowchart TD\n A-->C"  # 画像だけ差し替わった想定
    assert not p.hash_ok()


def test_marker_found_inside_text():
    p = Payload(mermaid="graph LR\n X-->Y").with_hash()
    text = encode(p)
    embedded = f"[MdFlow] note\n{text}\n(以下略)"
    assert decode(embedded).mermaid == "graph LR\n X-->Y"


# --------------------------------------------------------------------------- #
# rule evaluation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("expr,ctx,expected", [
    ('role == "admin" && error_count == 0', {"role": "admin", "error_count": 0}, True),
    ('role == "admin" && error_count == 0', {"role": "admin", "error_count": 2}, False),
    ('error_count > 0', {"error_count": 3}, True),
    ('error_count > 0 || role == "admin"', {"error_count": 0, "role": "admin"}, True),
    ('!(role == "user")', {"role": "admin"}, True),
    ('', {}, True),  # 無条件
    ('role == "x"', {}, False),  # 未定義は None -> False
])
def test_evaluate(expr, ctx, expected):
    assert mapping.evaluate(expr, ctx) is expected


def test_evaluate_rejects_calls():
    with pytest.raises(mapping.RuleError):
        mapping.evaluate("__import__('os')", {})


# --------------------------------------------------------------------------- #
# mermaid parse / inject
# --------------------------------------------------------------------------- #
def test_extract_and_ids():
    blocks = mermaid.extract_blocks(SAMPLE)
    assert len(blocks) == 1
    assert blocks[0].diagram_id == "flow-login"
    ids = mermaid.parse_node_ids(blocks[0].code)
    assert {"A", "B", "C", "D", "E", "F", "G"} <= ids


def test_extract_and_mapping_accept_windows_crlf():
    windows_text = SAMPLE.replace("\n", "\r\n")
    blocks = mermaid.extract_blocks(windows_text)
    assert len(blocks) == 1
    assert blocks[0].diagram_id == "flow-login"
    mappings = mapping.extract_mappings(windows_text)
    assert mappings[0].diagram_id == "flow-login"
    assert mappings[0].preset_names()


def test_inject_validates_missing():
    code = "flowchart TD\n A-->B\n B-->C"
    res = mermaid.inject_style(code, ["A", "B", "Z"], "fill:#f99")
    assert "classDef mdflowActive" in res.code
    assert "class A,B mdflowActive" in res.code
    assert res.missing == ["Z"]


def test_enumerate_all_flowchart_paths_with_shapes_and_labels():
    code = """flowchart TD
 A[Start] --> B{Allowed?}
 B -->|Yes| C[Dashboard]
 B -->|No| D[Denied]
 C --> E[End]
 D --> E
"""
    result = mermaid.enumerate_flow_paths(code)
    assert result.paths == [["A", "B", "C", "E"], ["A", "B", "D", "E"]]
    assert result.truncated is False
    assert result.has_cycle is False

    assert mermaid.flow_edges("flowchart LR\n A -- success --> B") == [("A", "B")]


def test_enumerate_paths_stops_cycles_and_honours_limit():
    cycle = mermaid.enumerate_flow_paths("flowchart LR\n A-->B\n B-->A")
    assert cycle.paths == []
    assert cycle.has_cycle is True
    limited = mermaid.enumerate_flow_paths("flowchart TD\n A-->B\n A-->C\n B-->D\n C-->D", limit=1)
    assert limited.paths == [["A", "B", "D"]]
    assert limited.truncated is True
    assert mermaid.enumerate_flow_paths("flowchart TD\n A[Only node]").paths == []


def test_enumerate_state_diagram_paths_with_japanese_ids():
    code = """stateDiagram-v2
 [*] --> 初期状態
 初期状態 --> 機能有効状態: 有効
 初期状態 --> 出力無効状態: 無効
 機能有効状態 --> [*]
 出力無効状態 --> [*]
"""
    result = mermaid.enumerate_flow_paths(code)
    assert result.paths == [
        ["初期状態", "機能有効状態"],
        ["初期状態", "出力無効状態"],
    ]
    assert mermaid.node_ids_ordered(code) == ["初期状態", "機能有効状態", "出力無効状態"]
    injected = mermaid.inject_style(code, ["初期状態", "機能有効状態"], "fill:#f99")
    assert 'state "初期状態" as mdflowState0' in injected.code
    assert "class mdflowState0,mdflowState1 mdflowActive" in injected.code


# --------------------------------------------------------------------------- #
# frontmatter
# --------------------------------------------------------------------------- #
def test_frontmatter_roundtrip():
    meta, body = frontmatter.parse(SAMPLE)
    assert meta["title"] == "ログイン仕様"
    assert frontmatter.get_selected(meta) == {"flow-login": "管理者・正常"}
    frontmatter.set_selected(meta, "flow-login", "認証エラー")
    out = frontmatter.dump(meta, body)
    meta2, _ = frontmatter.parse(out)
    assert frontmatter.get_selected(meta2)["flow-login"] == "認証エラー"


# --------------------------------------------------------------------------- #
# document integration
# --------------------------------------------------------------------------- #
def test_document_render_by_conditions():
    doc = Document(SAMPLE)
    rr = doc.render("flow-login", {"role": "user", "error_count": 0})
    assert rr.preset == "一般・正常"
    assert "class A,B,C,F,G mdflowActive" in rr.injected_code
    assert not rr.missing_nodes


def test_document_render_by_selected_preset():
    doc = Document(SAMPLE)
    # 条件を渡さず Frontmatter の選択（管理者・正常）を使う
    rr = doc.render("flow-login", selected_preset="認証エラー")
    assert rr.preset == "認証エラー"
    assert "class A,B,E,G mdflowActive" in rr.injected_code
