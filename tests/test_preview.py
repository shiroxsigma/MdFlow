"""プレビューHTML生成のテスト（PyQt非依存）."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdflow.document import Document  # noqa: E402
from mdflow.preview import build_html  # noqa: E402

SAMPLE = (Path(__file__).resolve().parents[1] / "samples" / "login.md").read_text(
    encoding="utf-8"
)


def test_build_html_marks_selected_block_and_injects():
    doc = Document(SAMPLE)
    rr = doc.render("flow-login", {"role": "user", "error_count": 0})
    html = build_html(doc, "flow-login", rr.injected_code)

    assert "<!doctype html>" in html
    assert "mermaid.initialize" in html
    assert "securityLevel: 'strict'" in html
    # 選択図には注入クラスと mdflow-selected が付く
    assert "mdflow-selected" in html
    assert "classDef mdflowActive" in html  # html.escape 後も文字列として残る


def test_build_html_without_mapping_is_safe():
    doc = Document("```mermaid\nflowchart TD\n A-->B\n```\n")
    rr = doc.render("#0")
    html = build_html(doc, "#0", rr.injected_code)
    assert "flowchart TD" in html
