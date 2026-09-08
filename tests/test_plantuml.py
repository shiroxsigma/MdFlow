import subprocess

import pytest

from mdflow import plantuml


def test_render_svg_uses_local_process(monkeypatch):
    monkeypatch.setattr(plantuml, "_command", lambda resources_dir=None: ["plantuml"])
    completed = subprocess.CompletedProcess(["plantuml"], 0, b'<svg xmlns="http://www.w3.org/2000/svg"/>', b"")
    monkeypatch.setattr(plantuml.subprocess, "run", lambda *args, **kwargs: completed)

    assert "<svg" in plantuml.render_svg("@startuml\nAlice -> Bob\n@enduml")


def test_render_svg_rejects_empty_source():
    with pytest.raises(plantuml.PlantUmlError, match="空"):
        plantuml.render_svg("  ")


def test_missing_renderer_has_setup_hint(monkeypatch, tmp_path):
    monkeypatch.delenv("MDFLOW_PLANTUML", raising=False)
    monkeypatch.delenv("MDFLOW_PLANTUML_JAR", raising=False)
    monkeypatch.setattr(plantuml.shutil, "which", lambda name: None)

    with pytest.raises(plantuml.PlantUmlError, match="fetch_plantuml.py"):
        plantuml._command(tmp_path)


def test_render_uses_disk_cache(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("MDFLOW_PLANTUML_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(plantuml, "_command", lambda resources_dir=None: ["plantuml"])
    def run(*args, **kwargs):
        calls.append(1)
        return subprocess.CompletedProcess(["plantuml"], 0, b"<svg>cached</svg>", b"")
    monkeypatch.setattr(plantuml.subprocess, "run", run)
    source = "@startuml\nA -> Cache\n@enduml"
    assert plantuml.render_svg(source) == plantuml.render_svg(source)
    assert len(calls) == 1


def test_diagnostics_reports_version(monkeypatch, tmp_path):
    monkeypatch.setenv("MDFLOW_PLANTUML_CACHE", str(tmp_path))
    monkeypatch.setattr(plantuml, "_command", lambda resources_dir=None: ["plantuml", "-pipe", "-tsvg"])
    monkeypatch.setattr(plantuml.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, b"PlantUML version 1.2.3\n", b""))
    result = plantuml.diagnostics()
    assert result["available"] is True
    assert result["version"] == "1.2.3"
