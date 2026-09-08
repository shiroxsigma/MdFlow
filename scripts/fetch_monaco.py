"""Download a pinned Monaco Editor distribution for offline use."""
from __future__ import annotations

import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "0.56.0"
URL = f"https://registry.npmjs.org/monaco-editor/-/monaco-editor-{VERSION}.tgz"
DEST = Path(__file__).parents[1] / "mdflow" / "resources" / "vendor" / "monaco" / "vs"


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="mdflow_monaco_") as work:
            archive = Path(work) / "monaco.tgz"
            print(f"Downloading Monaco Editor {VERSION}...")
            urllib.request.urlretrieve(URL, archive)  # noqa: S310 - pinned npm package URL
            with tarfile.open(archive, "r:gz") as package:
                package.extractall(work, filter="data")
            source = Path(work) / "package" / "min" / "vs"
            if DEST.exists():
                shutil.rmtree(DEST)
            DEST.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, DEST)
    except Exception as exc:  # noqa: BLE001
        print(f"Monaco download failed: {exc}", file=sys.stderr)
        return 1
    print(f"Saved: {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
