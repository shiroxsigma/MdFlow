"""WebEngine プレビュー用の HTML 生成（純ロジック・PyQt非依存）.

- Markdown 本文を HTML 化し、各 ```mermaid``` ブロックを `<pre class="mermaid">` に置換。
- 選択中の図には注入済みコードを、その他は素のコードを埋め込む。
- Mermaid.js はローカル同梱（外部通信なし）。securityLevel='strict'。
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional

from .document import Document

try:  # 任意依存: あればMarkdownを整形、無くても図は描画できる
    import markdown as _md
except Exception:  # pragma: no cover
    _md = None

_FENCE_RE = re.compile(r"```[ \t]*mermaid[ \t]*\n(.*?)```", re.DOTALL)

_TEMPLATE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Segoe UI', 'Meiryo', sans-serif; margin: 24px; color: #222; }}
  pre.mermaid {{ background: #fff; text-align: center; }}
  code, pre {{ background: #f6f8fa; padding: 2px 4px; border-radius: 4px; }}
  table {{ border-collapse: collapse; }} td, th {{ border: 1px solid #ccc; padding: 4px 8px; }}
  .mdflow-selected {{ outline: 2px dashed #ff9999; outline-offset: 6px; }}
</style>
<script>{mermaid_js}</script>
</head><body>
{content}
<script>
  mermaid.initialize({{ startOnLoad: true, securityLevel: 'strict', theme: 'default' }});
</script>
</body></html>
"""


def _mermaid_js_source(resources_dir: Path) -> str:
    """同梱の mermaid.min.js を読み込む。無ければプレースホルダ（要セットアップ）."""
    js = resources_dir / "mermaid.min.js"
    if js.exists():
        return js.read_text(encoding="utf-8")
    notice = (
        "document.body.insertAdjacentHTML('afterbegin',"
        "'<p style=\\'color:#b00\\'>mermaid.min.js が未配置です。"
        "scripts/fetch_mermaid.py を実行してください。</p>');"
    )
    return "window.mermaid={initialize:function(){" + notice + "},run:function(){}};"


def build_html(
    doc: Document,
    selected_id: str,
    injected_code: str,
    resources_dir: Optional[Path] = None,
) -> str:
    """プレビュー用 HTML 全文を返す."""
    resources_dir = resources_dir or (Path(__file__).parent / "resources")
    body = doc.body

    # 各 mermaid ブロックを <pre class="mermaid"> に置換（選択図は注入済みコード）
    counter = {"i": 0}
    blocks = doc.blocks

    def repl(m: re.Match) -> str:
        idx = counter["i"]
        counter["i"] += 1
        block = blocks[idx] if idx < len(blocks) else None
        code = m.group(1).rstrip("\n")
        cls = "mermaid"
        if block is not None and block.label == selected_id:
            code = injected_code
            cls = "mermaid mdflow-selected"
        return f'<pre class="{cls}">{html.escape(code)}</pre>'

    replaced = _FENCE_RE.sub(repl, body)

    if _md is not None:
        content = _md.markdown(replaced, extensions=["tables", "fenced_code"])
    else:
        content = f"<pre>{replaced}</pre>"

    return _TEMPLATE.format(mermaid_js=_mermaid_js_source(resources_dir), content=content)
