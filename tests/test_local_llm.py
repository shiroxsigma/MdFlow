from mdflow import local_llm


def test_ollama_models(monkeypatch):
    monkeypatch.setattr(local_llm, "_json_request", lambda *args, **kwargs: {
        "models": [{"name": "local-model:latest"}, {"name": "nomic-embedding"}]
    })
    cfg = local_llm.Config("ollama", "http://127.0.0.1:11434", "")
    assert local_llm.models(cfg) == ["local-model:latest"]


def test_config_from_switches_provider_default(monkeypatch):
    monkeypatch.delenv("MDFLOW_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("MDFLOW_LLM_URL", raising=False)
    cfg = local_llm.config_from("openai")
    assert cfg.url == "http://127.0.0.1:1234/v1"


def test_ollama_edit_prompt(monkeypatch):
    captured = {}
    def fake_request(url, payload=None, timeout=120):
        captured.update(payload)
        return {"message": {"content": "updated markdown"}}
    monkeypatch.setattr(local_llm, "_json_request", fake_request)
    cfg = local_llm.Config("ollama", "http://127.0.0.1:11434", "test")
    assert local_llm.chat("shorten", "# Long", "edit", cfg=cfg) == "updated markdown"
    assert captured["stream"] is False
    assert "Return only" in captured["messages"][0]["content"]


def test_openai_compatible_response(monkeypatch):
    monkeypatch.setattr(local_llm, "_json_request", lambda *args, **kwargs: {
        "choices": [{"message": {"content": "because"}}]
    })
    cfg = local_llm.Config("openai", "http://127.0.0.1:1234/v1", "test")
    assert local_llm.chat("why", "diagram", "ask", cfg=cfg) == "because"


def test_openai_stream(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def __iter__(self):
            return iter([
                b'data: {"choices":[{"delta":{"content":"hel"}}]}\n',
                b'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
                b'data: [DONE]\n',
            ])
    monkeypatch.setattr(local_llm, "urlopen", lambda *args, **kwargs: Response())
    cfg = local_llm.Config("openai", "http://127.0.0.1:1234/v1", "test")
    assert "".join(local_llm.stream_chat("say hello", "", "ask", cfg=cfg)) == "hello"
