"""OpenAI-compatible chat provider.

Covers OpenAI, Ollama (/v1), LM Studio, OpenRouter, LiteLLM, vLLM, Azure-ish —
anything exposing POST {base_url}/chat/completions with the OpenAI schema.
"""
from __future__ import annotations

import httpx

from .base import LLMError, Message


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.extra_headers = extra_headers or {}
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        url = f"{self.base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
            except httpx.HTTPError as e:
                raise LLMError(f"{self.name}: request failed: {e}") from e
        if resp.status_code >= 400:
            raise LLMError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"{self.name}: unexpected response shape: {data}") from e
