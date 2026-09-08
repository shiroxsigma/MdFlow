"""Local PlantUML rendering support."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


class PlantUmlError(RuntimeError):
    """Raised when PlantUML cannot be started or cannot render a diagram."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.line = line


def _command(resources_dir: Path | None = None) -> list[str]:
    executable = os.environ.get("MDFLOW_PLANTUML") or shutil.which("plantuml")
    if executable:
        return [executable, "-pipe", "-tsvg", "-charset", "UTF-8"]

    resources_dir = resources_dir or Path(__file__).parent / "resources"
    configured_jar = os.environ.get("MDFLOW_PLANTUML_JAR")
    jar = (Path(configured_jar) if configured_jar else
           resources_dir / "vendor" / "plantuml" / "plantuml.jar")
    java = shutil.which("java")
    if java and jar.is_file():
        return [java, "-Djava.awt.headless=true", "-jar", str(jar),
                "-pipe", "-tsvg", "-charset", "UTF-8"]
    raise PlantUmlError(
        "PlantUML を利用できません。Java をインストールし、"
        "python scripts/fetch_plantuml.py を実行してください。"
    )


@lru_cache(maxsize=64)
def render_svg(source: str, resources_dir: Path | None = None) -> str:
    """Render PlantUML source to SVG without sending it to an external server."""
    if not source.strip():
        raise PlantUmlError("PlantUML のソースが空です。")
    try:
        completed = subprocess.run(
            _command(resources_dir), input=source.encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlantUmlError(f"PlantUML の実行に失敗しました: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        match = re.search(r"(?:error\s+line|line)\s+(\d+)", detail, re.IGNORECASE)
        raise PlantUmlError(detail or "PlantUML の描画に失敗しました。",
                            int(match.group(1)) if match else None)
    svg = completed.stdout.decode("utf-8", errors="strict")
    if "<svg" not in svg:
        raise PlantUmlError("PlantUML から SVG が返されませんでした。")
    return svg
