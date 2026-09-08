"""markdown-it.min.js を一度だけローカルへ取得する（実行時はオフライン動作）.

    python scripts/fetch_markdown_it.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

VERSION = "14.1.0"
URL = f"https://cdn.jsdelivr.net/npm/markdown-it@{VERSION}/dist/markdown-it.min.js"
DEST = (Path(__file__).resolve().parents[1] / "mdflow" / "resources"
        / "vendor" / "markdown-it" / "markdown-it.min.js")


def main() -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"取得中: {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=30) as r:
            data = r.read()
    except Exception as e:
        print(f"取得失敗: {e}", file=sys.stderr)
        return 1
    DEST.write_bytes(data)
    print(f"配置完了: {DEST} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
