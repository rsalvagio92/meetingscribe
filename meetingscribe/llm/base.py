"""Vendor-agnostic LLM interface.

Every provider implements `chat(messages) -> str`. The notes pipeline only ever
talks to this interface, so swapping OpenAI / Ollama / Anthropic / Copilot is a
config change, never a code change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        ...
