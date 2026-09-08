import json

import pytest

from mdflow import llm_connections, local_llm


def test_load_servers_and_active_selection(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "servers": [
            {"name": "Local A", "base_url": "http://localhost:1234/v1", "model": "a"},
            {"name": "Local B", "provider": "ollama", "base_url": "http://localhost:11434"},
        ],
        "active_server": 1,
    }), encoding="utf-8")
    monkeypatch.setenv("MDFLOW_CONFIG", str(path))

    assert llm_connections.get_active_server_index() == 1
    assert llm_connections.load_servers()[0]["provider"] == "openai"
    assert local_llm.config().provider == "ollama"


def test_update_selection_writes_model_and_never_exposes_api_key(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "servers": [{"name": "Studio", "base_url": "http://localhost:1234/v1",
                     "model": "old", "api_key": "must-not-be-returned"}],
        "active_server": 0,
    }), encoding="utf-8")
    monkeypatch.setenv("MDFLOW_CONFIG", str(path))

    selected = llm_connections.update_selection(0, "new-model")
    assert selected["model"] == "new-model"
    assert "api_key" not in selected
    assert json.loads(path.read_text("utf-8"))["servers"][0]["model"] == "new-model"


def test_invalid_server_config_is_rejected(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"servers":[{"name":"bad","base_url":"file:///tmp/model"}]}', encoding="utf-8")
    monkeypatch.setenv("MDFLOW_CONFIG", str(path))
    with pytest.raises(ValueError, match="http"):
        llm_connections.load_servers()
