"""mermaid.min.js を一度だけローカルへ取得する（実行時は完全オフライン動作）.

セットアップ時のみネットワークを使用。取得後は mdflow/resources/ に置かれ、
アプリ実行中は外部通信を一切行わない。

    python scripts/fetch_mermaid.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

VERSION = "10.9.1"
URL = f"https://cdn.jsdelivr.net/npm/mermaid@{VERSION}/dist/mermaid.min.js"
DEST = (Path(__file__).resolve().parents[1] / "mdflow" / "resources"
        / "vendor" / "mermaid" / "mermaid.min.js")


def main() -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"取得中: {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=30) as r:
            data = r.read()
    except Exception as e:
        print(f"取得失敗: {e}", file=sys.stderr)
        print("手動で上記URLを保存し、次に配置してください:\n  " + str(DEST), file=sys.stderr)
        return 1
    DEST.write_bytes(data)
    print(f"配置完了: {DEST} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
