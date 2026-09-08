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
