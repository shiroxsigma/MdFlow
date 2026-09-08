"""Local LLM connection list stored in ``config.json``.

The shape follows CodeWithPixie's ``servers[]`` / ``active_server`` model.
Credentials are deliberately unsupported and never returned by this module.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DEFAULT_SERVERS = [
    {"name": "LM Studio", "provider": "openai", "base_url": "http://127.0.0.1:1234/v1", "model": ""},
    {"name": "Ollama", "provider": "ollama", "base_url": "http://127.0.0.1:11434", "model": ""},
]


def config_path() -> Path:
    configured = os.environ.get("MDFLOW_CONFIG", "").strip()
    if configured:
        return Path(configured).expanduser()
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).parents[1]
    return root / "config.json"


def _read() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"LLM設定JSONを読み込めません: {path} ({exc})") from exc
    if not isinstance(value, dict):
        raise ValueError(f"LLM設定JSONのルートはobjectにしてください: {path}")
    return value


def _sanitise_server(raw: Any, index: int) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(f"servers[{index}]はobjectにしてください")
    url = str(raw.get("base_url") or raw.get("url") or "").strip().rstrip("/")
    provider = str(raw.get("provider") or "").strip().lower()
    if not provider:
        provider = "ollama" if "11434" in url or "ollama" in str(raw.get("name", "")).lower() else "openai"
    if provider not in {"openai", "ollama"}:
        raise ValueError(f"servers[{index}].providerはopenaiまたはollamaを指定してください")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"servers[{index}].base_urlはhttp(s) URLを指定してください")
    return {
        "name": str(raw.get("name") or url),
        "provider": provider,
        "base_url": url,
        "model": str(raw.get("model") or ""),
    }


def load_servers() -> list[dict[str, str]]:
    raw_servers = _read().get("servers") or _DEFAULT_SERVERS
    if not isinstance(raw_servers, list) or not raw_servers:
        raise ValueError("config.jsonのserversには1件以上の接続先を指定してください")
    if len(raw_servers) > 32:
        raise ValueError("LLM接続先は最大32件です")
    return [_sanitise_server(raw, index) for index, raw in enumerate(raw_servers)]


def get_active_server_index() -> int:
    value = _read().get("active_server", 0)
    count = len(load_servers())
    return value if isinstance(value, int) and 0 <= value < count else 0


def server(index: int | None = None) -> dict[str, str]:
    servers = load_servers()
    selected = get_active_server_index() if index is None else index
    if not isinstance(selected, int) or not 0 <= selected < len(servers):
        raise ValueError(f"LLM接続先番号が範囲外です: {selected}")
    return servers[selected]


def update_selection(index: int, model: str | None = None) -> dict[str, str]:
    """Persist active server/model atomically while retaining unrelated settings."""
    with _LOCK:
        data = _read()
        raw_servers = data.get("servers")
        if not raw_servers:
            raw_servers = [dict(item) for item in _DEFAULT_SERVERS]
            data["servers"] = raw_servers
        if not isinstance(raw_servers, list) or not 0 <= index < len(raw_servers):
            raise ValueError(f"LLM接続先番号が範囲外です: {index}")
        # Validate before writing. Unknown keys are preserved, but never exposed.
        _sanitise_server(raw_servers[index], index)
        data["active_server"] = index
        if model is not None:
            raw_servers[index]["model"] = str(model).strip()
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    return server(index)
