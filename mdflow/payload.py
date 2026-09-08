"""PPTに埋め込む不可視ペイロードのエンコード/デコードと整合性検証.

フォーマット: ``MDFLOW:v1:<base64(gzip(json))>``
- grep可能なマーカー接頭辞
- gzipで圧縮、base64で単一行テキスト化（Alt Text/ノート/XMLパートに載る）
- json本文に mermaid コードの sha256 を持たせ、画像とコードの不一致を検知
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import PAYLOAD_PREFIX, SCHEMA_VERSION

_MARKER_RE = re.compile(r"MDFLOW:v1:[A-Za-z0-9+/=]+")


def mermaid_hash(code: str) -> str:
    """mermaid コードの正規化ハッシュ（改行差異を吸収）."""
    normalized = "\n".join(line.rstrip() for line in code.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class Payload:
    """PPTと相互変換するペイロード本体."""

    mermaid: str
    diagram_id: str = ""
    preset: str = ""
    conditions: dict[str, Any] = field(default_factory=dict)
    active_nodes: list[str] = field(default_factory=list)
    active_edges: list[Any] = field(default_factory=list)
    schema: int = SCHEMA_VERSION
    hash: str = ""

    def with_hash(self) -> "Payload":
        self.hash = mermaid_hash(self.mermaid)
        return self

    def hash_ok(self) -> bool:
        return bool(self.hash) and self.hash == mermaid_hash(self.mermaid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "diagram_id": self.diagram_id,
            "preset": self.preset,
            "conditions": self.conditions,
            "active_nodes": self.active_nodes,
            "active_edges": self.active_edges,
            "mermaid": self.mermaid,
            "hash": self.hash or mermaid_hash(self.mermaid),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Payload":
        return cls(
            mermaid=d.get("mermaid", ""),
            diagram_id=d.get("diagram_id", ""),
            preset=d.get("preset", ""),
            conditions=d.get("conditions", {}) or {},
            active_nodes=list(d.get("active_nodes", []) or []),
            active_edges=list(d.get("active_edges", []) or []),
            schema=int(d.get("schema", SCHEMA_VERSION)),
            hash=d.get("hash", ""),
        )


def encode(payload: Payload) -> str:
    """Payload -> マーカー付き単一行文字列."""
    payload.with_hash()
    raw = json.dumps(payload.to_dict(), ensure_ascii=False, separators=(",", ":"))
    packed = gzip.compress(raw.encode("utf-8"), mtime=0)  # mtime=0 で決定的出力
    b64 = base64.b64encode(packed).decode("ascii")
    return PAYLOAD_PREFIX + b64


def decode(text: str) -> Payload:
    """マーカーを含むテキストから Payload を復元（本文中に埋もれていてもよい）."""
    marker = find_marker(text)
    if marker is None:
        raise ValueError("MdFlow ペイロードが見つかりません")
    b64 = marker[len(PAYLOAD_PREFIX):]
    packed = base64.b64decode(b64)
    raw = gzip.decompress(packed).decode("utf-8")
    return Payload.from_dict(json.loads(raw))


def find_marker(text: str) -> Optional[str]:
    """テキスト中の MDFLOW マーカー文字列を返す（無ければ None）."""
    if not text:
        return None
    m = _MARKER_RE.search(text)
    return m.group(0) if m else None
