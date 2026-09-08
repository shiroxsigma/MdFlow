"""Small client for local Ollama and OpenAI-compatible LLM servers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import llm_connections


class LocalLlmError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    provider: str
    url: str
    model: str


def config() -> Config:
    selected = llm_connections.server()
    provider = os.environ.get("MDFLOW_LLM_PROVIDER", selected["provider"]).lower()
    return Config(provider, os.environ.get("MDFLOW_LLM_URL", selected["base_url"]).rstrip("/"),
                  os.environ.get("MDFLOW_LLM_MODEL", selected["model"]))


def config_for_server(index: int) -> Config:
    selected = llm_connections.server(index)
    return Config(selected["provider"], selected["base_url"], selected["model"])


def config_from(provider: str = "", url: str = "", model: str = "") -> Config:
    base = config()
    chosen_provider = (provider or base.provider).lower()
    if chosen_provider not in {"ollama", "openai"}:
        raise LocalLlmError("LLM providerはollamaまたはopenaiを指定してください。")
    default_url = "http://127.0.0.1:11434" if chosen_provider == "ollama" else "http://127.0.0.1:1234/v1"
    return Config(chosen_provider, (url or (base.url if provider == base.provider else default_url)).rstrip("/"),
                  model or base.model)


def _json_request(url: str, payload: dict | None = None, timeout: int = 120) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"},
                  method="GET" if data is None else "POST")
    try:
        with urlopen(req, timeout=timeout) as response:  # noqa: S310 - loopback URL by default
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LocalLlmError(f"LLM server error {exc.code}: {detail[:500]}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LocalLlmError(f"ローカルLLMに接続できません: {exc}") from exc


def models(cfg: Config | None = None) -> list[str]:
    cfg = cfg or config()
    if cfg.provider == "ollama":
        data = _json_request(f"{cfg.url}/api/tags", timeout=5)
        names = [item["name"] for item in data.get("models", []) if item.get("name")]
    else:
        data = _json_request(f"{cfg.url}/models", timeout=5)
        names = [item["id"] for item in data.get("data", []) if item.get("id")]
    excluded = ("embed", "embedding", "mmproj", "rerank", "whisper", "tts")
    return [name for name in names if not any(part in name.lower() for part in excluded)]


def _messages(instruction: str, text: str, mode: str) -> list[dict[str, str]]:
    if not instruction.strip():
        raise LocalLlmError("依頼または質問が空です。")
    if len(text) > 200_000:
        raise LocalLlmError("対象テキストが大きすぎます（上限200,000文字）。")
    if mode == "edit":
        system = (
            "You edit Markdown containing Mermaid and PlantUML. Return only the complete revised "
            "text, without Markdown code fences or commentary. Preserve content not requested to change. "
            "Keep the original human-language unless explicitly asked to translate."
        )
        user = f"Instruction:\n{instruction}\n\nText to edit:\n{text}"
    else:
        system = ("Explain the supplied Markdown, Mermaid, or PlantUML clearly. Do not modify it. "
                  "Answer in the same language as the question.")
        user = f"Question:\n{instruction}\n\nRelevant text:\n{text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def chat(instruction: str, text: str, mode: str, model: str = "",
         cfg: Config | None = None) -> str:
    cfg = cfg or config()
    chosen_model = model or cfg.model
    if not chosen_model:
        available = models(cfg)
        if not available:
            raise LocalLlmError("利用可能なローカルLLMモデルがありません。")
        chosen_model = available[0]

    messages = _messages(instruction, text, mode)

    if cfg.provider == "ollama":
        data = _json_request(f"{cfg.url}/api/chat",
                             {"model": chosen_model, "messages": messages, "stream": False})
        answer = data.get("message", {}).get("content", "").strip()
    else:
        data = _json_request(f"{cfg.url}/chat/completions",
                             {"model": chosen_model, "messages": messages, "stream": False})
        choices = data.get("choices", [])
        answer = (choices[0].get("message", {}).get("content", "") if choices else "").strip()
    if not answer:
        raise LocalLlmError("ローカルLLMから空の応答が返されました。")
    return answer


def stream_chat(instruction: str, text: str, mode: str, model: str = "",
                cfg: Config | None = None, timeout: int = 120):
    """Yield text chunks from a local model response."""
    cfg = cfg or config()
    chosen_model = model or cfg.model
    if not chosen_model:
        available = models(cfg)
        if not available:
            raise LocalLlmError("利用可能なローカルLLMモデルがありません。")
        chosen_model = available[0]
    messages = _messages(instruction, text, mode)
    if cfg.provider == "ollama":
        url = f"{cfg.url}/api/chat"
        payload = {"model": chosen_model, "messages": messages, "stream": True}
    else:
        url = f"{cfg.url}/chat/completions"
        payload = {"model": chosen_model, "messages": messages, "stream": True}
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured local server
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if cfg.provider != "ollama":
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data: "):
                        line = line[6:]
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cfg.provider == "ollama":
                    chunk = data.get("message", {}).get("content", "")
                else:
                    choices = data.get("choices", [])
                    chunk = choices[0].get("delta", {}).get("content", "") if choices else ""
                if chunk:
                    yield chunk
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LocalLlmError(f"LLM server error {exc.code}: {detail[:500]}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise LocalLlmError(f"ローカルLLMに接続できません: {exc}") from exc
