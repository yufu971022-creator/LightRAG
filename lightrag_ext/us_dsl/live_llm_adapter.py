from __future__ import annotations

import os
import json
import urllib.error
import urllib.request
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_BINDINGS = {"openai", "azure_openai", "gemini", "ollama"}
DEFAULT_TIMEOUT_SECONDS = 90
DEFAULT_MAX_TOKENS = 3000


@dataclass(frozen=True)
class LiveLlmResolution:
    llm_callable: Callable[..., Any] | None
    binding: str | None
    model: str | None
    host_configured: bool
    api_key_configured: bool
    env_loaded_from: str | None
    reason: str | None = None


def resolve_live_llm_callable_from_env_or_lightrag():
    return resolve_live_llm_status_from_env_or_lightrag().llm_callable


def resolve_live_llm_status_from_env_or_lightrag(
    env_path: str | Path = ".env",
) -> LiveLlmResolution:
    env_loaded_from = _load_env_file(env_path)
    binding = _env("LLM_BINDING")
    if binding == "openai-ollama":
        binding = "openai"
    model = _env("LLM_MODEL")
    host = _env("LLM_BINDING_HOST")
    api_key = _api_key_for_binding(binding)

    if not binding:
        return _unavailable("LLM_BINDING is not configured.", env_loaded_from)
    if binding not in SUPPORTED_BINDINGS:
        return _unavailable(
            f"LLM binding '{binding}' is not supported by the live smoke adapter.",
            env_loaded_from,
            binding=binding,
            model=model,
            host=host,
            api_key=api_key,
        )
    if not model:
        return _unavailable(
            "LLM_MODEL is not configured.",
            env_loaded_from,
            binding=binding,
            host=host,
            api_key=api_key,
        )
    if binding in {"openai", "azure_openai", "gemini"} and not api_key:
        return _unavailable(
            "LLM API key is not configured.",
            env_loaded_from,
            binding=binding,
            model=model,
            host=host,
        )

    llm_callable = _build_callable(binding, model, host, api_key)
    return LiveLlmResolution(
        llm_callable=llm_callable,
        binding=binding,
        model=model,
        host_configured=bool(host),
        api_key_configured=bool(api_key),
        env_loaded_from=env_loaded_from,
    )


def _build_callable(
    binding: str,
    model: str,
    host: str | None,
    api_key: str | None,
):
    timeout = int(_env("LIGHTRAG_DSL_LIVE_SMOKE_TIMEOUT") or DEFAULT_TIMEOUT_SECONDS)
    max_tokens = int(_env("LIGHTRAG_DSL_LIVE_SMOKE_MAX_TOKENS") or DEFAULT_MAX_TOKENS)

    async def llm_callable(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        **_kwargs,
    ) -> str:
        history_messages = history_messages or []
        if binding == "openai":
            return await _openai_compatible_complete(
                model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                base_url=host,
                api_key=api_key,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        if binding == "azure_openai":
            from lightrag.llm.azure_openai import azure_openai_complete_if_cache

            return await azure_openai_complete_if_cache(
                model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                base_url=host,
                api_key=api_key,
                timeout=timeout,
                max_tokens=max_tokens,
                temperature=0,
            )
        if binding == "gemini":
            from lightrag.llm.gemini import gemini_complete_if_cache

            return await gemini_complete_if_cache(
                model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                base_url=host,
                api_key=api_key,
                timeout=timeout,
                generation_config={"temperature": 0, "max_output_tokens": max_tokens},
            )

        from lightrag.llm.ollama import _ollama_model_if_cache

        return await _ollama_model_if_cache(
            model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            host=host,
            timeout=timeout,
            api_key=api_key,
            stream=False,
            options={"temperature": 0, "num_predict": max_tokens},
        )

    return llm_callable


async def _openai_compatible_complete(
    model: str,
    prompt: str,
    *,
    system_prompt: str | None,
    history_messages: list[dict[str, str]],
    base_url: str | None,
    api_key: str | None,
    timeout: int,
    max_tokens: int,
) -> str:
    return await asyncio.to_thread(
        _openai_compatible_complete_sync,
        model,
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        max_tokens=max_tokens,
    )


def _openai_compatible_complete_sync(
    model: str,
    prompt: str,
    *,
    system_prompt: str | None,
    history_messages: list[dict[str, str]],
    base_url: str | None,
    api_key: str | None,
    timeout: int,
    max_tokens: int,
) -> str:
    url = _openai_chat_completions_url(base_url)
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(history_messages)
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if model.lower().startswith("gpt-5"):
        payload["max_completion_tokens"] = max_tokens
    else:
        payload["max_tokens"] = max_tokens
        payload["temperature"] = 0
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI-compatible endpoint returned HTTP {exc.code}: {body}") from exc
    data = json.loads(body)
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise RuntimeError("OpenAI-compatible endpoint returned no choices.")
    message = choices[0].get("message", {})
    content = message.get("content")
    if not content:
        raise RuntimeError("OpenAI-compatible endpoint returned empty content.")
    return str(content)


def _openai_chat_completions_url(base_url: str | None) -> str:
    root = (base_url or "https://api.openai.com/v1").rstrip("/")
    if root.endswith("/chat/completions"):
        return root
    return f"{root}/chat/completions"


def _load_env_file(env_path: str | Path) -> str | None:
    path = Path(env_path)
    if not path.exists():
        return None
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        values[key] = _strip_quotes(value.strip())

    for key, value in values.items():
        if key not in os.environ:
            os.environ[key] = _resolve_env_refs(value, values)
    return str(path.resolve())


def _resolve_env_refs(value: str, values: dict[str, str]) -> str:
    if value.startswith("${") and value.endswith("}"):
        ref = value[2:-1]
        return os.environ.get(ref) or values.get(ref, "")
    return value


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _api_key_for_binding(binding: str | None) -> str | None:
    if binding == "openai":
        return _env("LLM_BINDING_API_KEY") or _env("OPENAI_API_KEY")
    if binding == "azure_openai":
        return _env("AZURE_OPENAI_API_KEY") or _env("LLM_BINDING_API_KEY")
    if binding == "gemini":
        return _env("LLM_BINDING_API_KEY") or _env("GEMINI_API_KEY")
    if binding == "ollama":
        return _env("LLM_BINDING_API_KEY") or _env("OLLAMA_API_KEY")
    return _env("LLM_BINDING_API_KEY")


def _env(key: str) -> str | None:
    value = os.getenv(key)
    return value if value else None


def _unavailable(
    reason: str,
    env_loaded_from: str | None,
    *,
    binding: str | None = None,
    model: str | None = None,
    host: str | None = None,
    api_key: str | None = None,
) -> LiveLlmResolution:
    return LiveLlmResolution(
        llm_callable=None,
        binding=binding,
        model=model,
        host_configured=bool(host),
        api_key_configured=bool(api_key),
        env_loaded_from=env_loaded_from,
        reason=reason,
    )
