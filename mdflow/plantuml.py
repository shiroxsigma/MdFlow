"""Local PlantUML rendering support."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


class PlantUmlError(RuntimeError):
    """Raised when PlantUML cannot be started or cannot render a diagram."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.line = line


_RENDER_LIMIT = max(1, int(os.environ.get("MDFLOW_PLANTUML_CONCURRENCY", "2")))
_RENDER_SLOTS = threading.BoundedSemaphore(_RENDER_LIMIT)


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


def render_svg(source: str, resources_dir: Path | None = None) -> str:
    """Render PlantUML source to SVG without sending it to an external server."""
    if not source.strip():
        raise PlantUmlError("PlantUML のソースが空です。")
    command = _command(resources_dir)
    identity = "\0".join(command)
    jar = next((Path(part) for part in command if part.endswith(".jar")), None)
    if jar and jar.exists():
        identity += f"\0{jar.stat().st_size}\0{jar.stat().st_mtime_ns}"
    key = hashlib.sha256((identity + "\0" + source).encode("utf-8")).hexdigest()
    cache = _cache_dir() / f"{key}.svg"
    if cache.is_file():
        return cache.read_text("utf-8")
    try:
        with _RENDER_SLOTS:
            if cache.is_file():
                return cache.read_text("utf-8")
            completed = subprocess.run(
                command, input=source.encode("utf-8"), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=30, check=False,
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
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(f".{threading.get_ident()}.tmp")
        temporary.write_text(svg, "utf-8")
        temporary.replace(cache)
    except OSError:
        pass  # A read-only cache must not prevent rendering.
    return svg


def _cache_dir() -> Path:
    configured = os.environ.get("MDFLOW_PLANTUML_CACHE")
    if configured:
        return Path(configured)
    base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    return base / "MdFlow" / "cache" / "plantuml"


def diagnostics(resources_dir: Path | None = None) -> dict:
    """Return renderer, Java, Graphviz and cache diagnostics."""
    result = {"available": False, "version": "", "java": shutil.which("java") or "",
              "graphviz": shutil.which("dot") or "", "concurrency": _RENDER_LIMIT,
              "cache": str(_cache_dir())}
    try:
        command = _command(resources_dir)
        if "-jar" in command:
            version_command = command[:command.index("-jar") + 2] + ["-version"]
        else:
            version_command = [command[0], "-version"]
        completed = subprocess.run(version_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   timeout=10, check=False)
        output = completed.stdout.decode("utf-8", errors="replace")
        match = re.search(r"PlantUML version\s+([^\s(]+)", output, re.IGNORECASE)
        result.update({"available": completed.returncode == 0,
                       "version": match.group(1) if match else output.strip().splitlines()[0] if output.strip() else "",
                       "command": command[0]})
    except (PlantUmlError, OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
    return result
