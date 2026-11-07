"""OpenAI-compatible provider. In this project it talks to the LiteLLM proxy (infra/litellm.yaml),
which maps the aliases ``fast`` / ``smart`` to Ollama quantised models or a hosted model."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx

from regintel.llm.base import LLMError, LLMRequest, LLMResponse, Usage


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s, transport=transport
        )

    def _payload(self, request: LLMRequest, model: str, stream: bool) -> dict[str, Any]:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.user})
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        start = time.perf_counter()
        try:
            resp = self._client.post(
                "/v1/chat/completions", json=self._payload(request, model, False)
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"{self.name}/{model}: {exc}") from exc
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=str(data.get("model", model)),
            provider=self.name,
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    def stream(self, request: LLMRequest, model: str) -> Iterator[str]:
        try:
            with self._client.stream(
                "POST", "/v1/chat/completions", json=self._payload(request, model, True)
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    delta = json.loads(chunk)["choices"][0].get("delta", {}).get("content")
                    if delta:
                        yield delta
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"{self.name}/{model} stream: {exc}") from exc
