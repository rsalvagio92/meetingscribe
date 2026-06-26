"""Anthropic Messages API provider (parity with WildClaude)."""
from __future__ import annotations

import httpx

from .base import LLMError, Message

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        *,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        # Anthropic keeps system separate from the turn list.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        payload = {
            "model": self.model,
            "system": system,
            "messages": turns,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        url = f"{self.base_url}/v1/messages"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as e:
                raise LLMError(f"{self.name}: request failed: {e}") from e
        if resp.status_code >= 400:
            raise LLMError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            return "".join(
                block["text"] for block in data["content"] if block.get("type") == "text"
            )
        except (KeyError, TypeError) as e:
            raise LLMError(f"{self.name}: unexpected response shape: {data}") from e
