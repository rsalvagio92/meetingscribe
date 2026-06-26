"""Build the configured LLM provider from config + secret store."""
from __future__ import annotations

from ..config import LLMConfig
from ..store.secrets import SecretStore
from .anthropic import AnthropicProvider
from .base import LLMError, LLMProvider
from .copilot import CopilotProvider
from .openai_compat import OpenAICompatProvider


def build_provider(cfg: LLMConfig, secrets: SecretStore) -> LLMProvider:
    provider = cfg.provider

    if provider == "openai_compat":
        # api_key is optional (local Ollama/LM Studio need none).
        return OpenAICompatProvider(
            model=cfg.model,
            base_url=cfg.base_url,
            api_key=secrets.get("OPENAI_API_KEY"),
        )

    if provider == "anthropic":
        key = secrets.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("anthropic: set the ANTHROPIC_API_KEY secret")
        return AnthropicProvider(model=cfg.model, api_key=key)

    if provider == "copilot":
        return CopilotProvider(
            model=cfg.model,
            oauth_token=secrets.get("GITHUB_COPILOT_OAUTH_TOKEN"),
            ghe_host=cfg.copilot_ghe_host,
            prefetched_copilot_token=secrets.get("GITHUB_COPILOT_TOKEN"),
        )

    raise LLMError(f"unknown LLM provider: {provider!r}")
