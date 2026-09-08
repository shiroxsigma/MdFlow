"""ヘッドレスCLI（PyQt不要）。PPTからの復元・検査、画像指定でのPPT出力.

使い方:
    python -m mdflow.cli import  <file.pptx>
    python -m mdflow.cli export  <doc.md> --diagram flow-login --image fig.png -o out.pptx
                                 [--conditions '{"role":"admin"}'] [--preset 管理者・正常]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import pptx_io
from .document import Document


def _cmd_import(args) -> int:
    res = pptx_io.import_ppt(args.file)
    pl = res.payload
    out = {
        "source": res.source,
        "hash_ok": res.hash_ok,
        "diagram_id": pl.diagram_id,
        "preset": pl.preset,
        "conditions": pl.conditions,
        "active_nodes": pl.active_nodes,
        "mermaid": pl.mermaid,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not res.hash_ok:
        print("⚠ ハッシュ不一致: 画像とコードがずれている可能性があります", file=sys.stderr)
        return 2
    return 0


def _cmd_export(args) -> int:
    doc = Document(Path(args.md).read_text("utf-8"))
    conditions = json.loads(args.conditions) if args.conditions else {}
    payload = doc.build_payload(args.diagram, conditions, args.preset)
    pptx_io.export_ppt(payload, args.image, args.out, title=args.diagram)
    print(f"出力: {args.out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mdflow.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("import", help="PPTからコード/条件を復元")
    pi.add_argument("file")
    pi.set_defaults(func=_cmd_import)

    pe = sub.add_parser("export", help="画像を指定してPPTを生成")
    pe.add_argument("md")
    pe.add_argument("--diagram", required=True)
    pe.add_argument("--image", required=True)
    pe.add_argument("-o", "--out", required=True)
    pe.add_argument("--conditions", default="")
    pe.add_argument("--preset", default=None)
    pe.set_defaults(func=_cmd_export)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
