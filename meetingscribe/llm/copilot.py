"""GitHub Copilot provider, with GitHub Enterprise (GHE) support.

Copilot's chat API is OpenAI-compatible at the wire level, but auth is two-step:

  1. You hold a GitHub OAuth token (github.com or your GHE instance).
  2. You exchange it for a short-lived *Copilot token* at
        {token_host}/copilot_internal/v2/token
     The response also tells you which API endpoint to hit (endpoints.api),
     and when the token expires.
  3. You call {api_endpoint}/chat/completions with the Copilot token as Bearer,
     plus the editor identification headers Copilot requires.

GHE differences are entirely in the hosts:
  - token exchange:  https://api.<ghe-host>/copilot_internal/v2/token
  - api endpoint:    taken from the exchange response (endpoints.api), which for
                     enterprise points at the enterprise Copilot proxy.

Set copilot_ghe_host="" for public github.com.

Secrets used (resolved by the factory, not here):
  GITHUB_COPILOT_OAUTH_TOKEN   the long-lived GitHub OAuth/PAT token
  GITHUB_COPILOT_TOKEN         (optional) a pre-exchanged Copilot token; if set,
                               the exchange step is skipped entirely.
"""
from __future__ import annotations

import time

import httpx

from .base import LLMError, Message

# Identity Copilot expects. These mirror what an editor plugin sends.
_EDITOR_VERSION = "MeetingScribe/0.1.0"
_PLUGIN_VERSION = "meetingscribe-chat/0.1.0"
_INTEGRATION_ID = "vscode-chat"
_USER_AGENT = "MeetingScribe/0.1.0"


def token_exchange_url(ghe_host: str = "") -> str:
    """Where to exchange the OAuth token for a Copilot token."""
    if ghe_host:
        host = ghe_host.strip().rstrip("/")
        # Accept either "ghe.corp.com" or "https://ghe.corp.com".
        host = host.removeprefix("https://").removeprefix("http://")
        return f"https://api.{host}/copilot_internal/v2/token"
    return "https://api.github.com/copilot_internal/v2/token"


class CopilotProvider:
    name = "copilot"

    def __init__(
        self,
        model: str,
        oauth_token: str | None = None,
        *,
        ghe_host: str = "",
        prefetched_copilot_token: str | None = None,
        api_endpoint_override: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        if not oauth_token and not prefetched_copilot_token:
            raise LLMError(
                "copilot: need GITHUB_COPILOT_OAUTH_TOKEN (or a pre-exchanged "
                "GITHUB_COPILOT_TOKEN)"
            )
        self.model = model
        self.oauth_token = oauth_token
        self.ghe_host = ghe_host
        self.timeout = timeout
        self.api_endpoint_override = api_endpoint_override

        # Cached Copilot session token.
        self._copilot_token: str | None = prefetched_copilot_token
        self._expires_at: float = float("inf") if prefetched_copilot_token else 0.0
        self._api_endpoint: str | None = api_endpoint_override

    # --- token exchange ----------------------------------------------------
    def _exchange_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self.oauth_token}",
            "Editor-Version": _EDITOR_VERSION,
            "Editor-Plugin-Version": _PLUGIN_VERSION,
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        }

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        # Refresh ~60s before expiry.
        if self._copilot_token and time.time() < self._expires_at - 60:
            return self._copilot_token
        if not self.oauth_token:
            # Pre-exchanged token with no way to refresh.
            if self._copilot_token:
                return self._copilot_token
            raise LLMError("copilot: token expired and no OAuth token to refresh")

        url = token_exchange_url(self.ghe_host)
        try:
            resp = await client.get(url, headers=self._exchange_headers())
        except httpx.HTTPError as e:
            raise LLMError(f"copilot: token exchange failed: {e}") from e
        if resp.status_code >= 400:
            raise LLMError(
                f"copilot: token exchange HTTP {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        token = data.get("token")
        if not token:
            raise LLMError(f"copilot: no token in exchange response: {data}")
        self._copilot_token = token
        self._expires_at = float(data.get("expires_at", time.time() + 1500))
        # Prefer the endpoint the server tells us (correct for GHE proxies).
        if not self.api_endpoint_override:
            endpoints = data.get("endpoints") or {}
            self._api_endpoint = endpoints.get("api") or "https://api.githubcopilot.com"
        return token

    # --- chat --------------------------------------------------------------
    def _chat_headers(self, copilot_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {copilot_token}",
            "Content-Type": "application/json",
            "Editor-Version": _EDITOR_VERSION,
            "Editor-Plugin-Version": _PLUGIN_VERSION,
            "Copilot-Integration-Id": _INTEGRATION_ID,
            "Openai-Intent": "conversation-panel",
            "User-Agent": _USER_AGENT,
        }

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            token = await self._ensure_token(client)
            api = self.api_endpoint_override or self._api_endpoint or "https://api.githubcopilot.com"
            url = f"{api.rstrip('/')}/chat/completions"
            payload = {
                "model": self.model,
                "messages": [
                    {"role": m.role, "content": m.content} for m in messages
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            try:
                resp = await client.post(url, json=payload, headers=self._chat_headers(token))
            except httpx.HTTPError as e:
                raise LLMError(f"copilot: request failed: {e}") from e
        if resp.status_code >= 400:
            raise LLMError(f"copilot: HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"copilot: unexpected response shape: {data}") from e
