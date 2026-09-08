"""webapi 層（フロントエンドが受け取る JSON）のテスト（PyQt非依存）."""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdflow import pptx_io, webapi  # noqa: E402

SAMPLE = (Path(__file__).resolve().parent / "fixtures" / "login.md").read_text("utf-8")
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_parse_doc():
    info = webapi.parse_doc(SAMPLE)
    assert info["diagrams"][0]["id"] == "flow-login"
    assert "管理者・正常" in info["diagrams"][0]["presets"]
    assert info["selected"]["flow-login"] == "管理者・正常"


def test_parse_doc_accepts_browser_preserved_windows_crlf():
    info = webapi.parse_doc(SAMPLE.replace("\n", "\r\n"))
    assert info["diagrams"][0]["id"] == "flow-login"
    assert "管理者・正常" in info["diagrams"][0]["presets"]


def test_render_diagram_by_conditions():
    res = webapi.render_diagram(SAMPLE, "flow-login",
                               '{"role":"user","error_count":0}', "")
    assert res["preset"] == "一般・正常"
    assert "class A,B,C,F,G mdflowActive" in res["injected"]
    assert res["missing"] == []


def test_render_diagram_bad_json_is_safe():
    res = webapi.render_diagram(SAMPLE, "flow-login", "{not json", "")
    # 条件は空扱い -> 最初にマッチするプリセット（管理者・正常: when 評価は False, ...）
    assert "warnings" in res


def test_apply_selection_persists_to_frontmatter():
    md2 = webapi.apply_selection(SAMPLE, "flow-login", "認証エラー")
    info = webapi.parse_doc(md2)
    assert info["selected"]["flow-login"] == "認証エラー"


def test_generate_all_paths_preserves_manual_presets():
    result = webapi.generate_all_paths(SAMPLE, "flow-login")
    assert result["count"] == 3
    assert result["paths"][0][0] == "A"
    info = webapi.parse_doc(result["md"])
    presets = info["diagrams"][0]["presets"]
    assert "管理者・正常" in presets
    assert len([name for name in presets if name.startswith("自動経路 ")]) == 3


def test_import_result_roundtrip(tmp_path):
    payload = webapi.build_payload(SAMPLE, "flow-login",
                                  '{"role":"admin","error_count":0}', "")
    png = tmp_path / "f.png"
    png.write_bytes(_PNG)
    out = tmp_path / "o.pptx"
    pptx_io.export_ppt(payload, png, out, title="flow-login")

    res = pptx_io.import_ppt(out)
    d = webapi.import_result_to_dict(res)
    assert d["hash_ok"] is True
    assert d["preset"] == "管理者・正常"
    assert d["conditions"] == {"role": "admin", "error_count": 0}
    # 復元 md を再パースすると図が1件取れる
    info = webapi.parse_doc(d["md"])
    assert info["diagrams"][0]["id"] == "flow-login"
