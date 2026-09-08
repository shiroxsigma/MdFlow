"""条件（プリセット）登録のテスト."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdflow import mapping, webapi, mermaid  # noqa: E402
from mdflow.document import Document  # noqa: E402

SAMPLE = (Path(__file__).resolve().parents[1] / "samples" / "login.md").read_text("utf-8")


def test_node_ids_ordered():
    doc = Document(SAMPLE)
    nodes = mermaid.node_ids_ordered(doc.blocks[0].code)
    assert nodes[0] == "A"                 # 初出順（開始ノード）
    assert set(nodes) == set("ABCDEFG")


def test_upsert_adds_preset_to_existing_block():
    md2 = mapping.upsert_preset(
        SAMPLE, "flow-login", "ロック", 'error_count > 3', ["A", "B", "E"])
    doc = Document(md2)
    mp = doc.get_mapping("flow-login")
    assert "ロック" in mp.preset_names()
    # 既存プリセットも保持されている
    assert "管理者・正常" in mp.preset_names()
    # ルールが実際に効く
    rr = doc.render("flow-login", {"error_count": 5}, "ロック")
    assert "class A,B,E mdflowActive" in rr.injected_code


def test_upsert_creates_block_when_absent():
    md = "```mermaid\n%% id: f2\nflowchart TD\n X-->Y\n```\n"
    md2 = mapping.upsert_preset(md, "f2", "経路X", "", ["X", "Y"])
    doc = Document(md2)
    mp = doc.get_mapping("f2")
    assert mp is not None and "経路X" in mp.preset_names()


def test_webapi_add_preset_requires_id():
    res = webapi.add_preset("```mermaid\nflowchart TD\n X-->Y\n```\n", "#0", "p", "", ["X"])
    assert "error" in res


def test_webapi_add_preset_roundtrip():
    res = webapi.add_preset(SAMPLE, "flow-login", "監査", 'role == "auditor"', ["A", "G"])
    assert "md" in res
    info = webapi.parse_doc(res["md"])
    assert "監査" in info["diagrams"][0]["presets"]
    assert "A" in info["diagrams"][0]["nodes"]
