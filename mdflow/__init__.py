"""MdFlow - Markdown・図・ローカルLLM統合エディタ.

推奨構成:
- 表示      : NiceGUI/FastAPI + Monaco Editor + Mermaid.js
- 画像化    : ブラウザSVG/PNG（表示・エクスポート）
- 条件定義  : 本文中の ```mdflow-mapping``` ブロック（図ごと）
- 選択状態  : Frontmatter を正とする単一ソース
- PPT埋込   : カスタムXMLパート（主）＋ ノート（副）、gzip+base64＋hash＋version
- 整合性    : 復元時に mermaid の hash を照合し、不一致は警告
"""

__version__ = "0.3.2"
SCHEMA_VERSION = 1
PAYLOAD_PREFIX = "MDFLOW:v1:"
