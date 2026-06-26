import httpx
import pytest
import respx

from meetingscribe.llm.base import LLMError, Message
from meetingscribe.llm.copilot import CopilotProvider, token_exchange_url


def test_token_exchange_url_public():
    assert token_exchange_url("") == "https://api.github.com/copilot_internal/v2/token"


def test_token_exchange_url_ghe():
    assert (
        token_exchange_url("ghe.corp.com")
        == "https://api.ghe.corp.com/copilot_internal/v2/token"
    )


def test_token_exchange_url_ghe_strips_scheme():
    assert (
        token_exchange_url("https://ghe.corp.com/")
        == "https://api.ghe.corp.com/copilot_internal/v2/token"
    )


def test_requires_some_token():
    with pytest.raises(LLMError):
        CopilotProvider(model="gpt-4o", oauth_token=None)


@pytest.mark.asyncio
@respx.mock
async def test_full_exchange_then_chat_public():
    # 1. Token exchange returns a copilot token + api endpoint.
    respx.get("https://api.github.com/copilot_internal/v2/token").mock(
        return_value=httpx.Response(200, json={
            "token": "copilot_tok_abc",
            "expires_at": 9999999999,
            "endpoints": {"api": "https://api.githubcopilot.com"},
        })
    )
    # 2. Chat completion at the advertised endpoint.
    chat = respx.post("https://api.githubcopilot.com/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )
    p = CopilotProvider(model="gpt-4o", oauth_token="gho_oauth")
    out = await p.chat([Message("user", "hi")])
    assert out == "ok"

    # Exchange used the OAuth token as `token <...>`.
    exch_req = respx.calls[0].request
    assert exch_req.headers["authorization"] == "token gho_oauth"
    # Chat used the copilot token as Bearer + required headers.
    chat_req = chat.calls[0].request
    assert chat_req.headers["authorization"] == "Bearer copilot_tok_abc"
    assert chat_req.headers["copilot-integration-id"] == "vscode-chat"
    assert "editor-version" in {k.lower() for k in chat_req.headers}


@pytest.mark.asyncio
@respx.mock
async def test_ghe_uses_enterprise_token_host_and_advertised_endpoint():
    respx.get("https://api.ghe.corp.com/copilot_internal/v2/token").mock(
        return_value=httpx.Response(200, json={
            "token": "ent_tok",
            "expires_at": 9999999999,
            "endpoints": {"api": "https://copilot-proxy.ghe.corp.com"},
        })
    )
    chat = respx.post("https://copilot-proxy.ghe.corp.com/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "ent ok"}}]})
    )
    p = CopilotProvider(model="gpt-4o", oauth_token="gho_ent", ghe_host="ghe.corp.com")
    out = await p.chat([Message("user", "hi")])
    assert out == "ent ok"
    assert chat.called


@pytest.mark.asyncio
@respx.mock
async def test_prefetched_token_skips_exchange():
    # No exchange route registered; if it tried to exchange, respx would error.
    chat = respx.post("https://api.githubcopilot.com/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "pre"}}]})
    )
    p = CopilotProvider(model="gpt-4o", prefetched_copilot_token="ready_tok")
    out = await p.chat([Message("user", "hi")])
    assert out == "pre"
    assert chat.calls[0].request.headers["authorization"] == "Bearer ready_tok"


@pytest.mark.asyncio
@respx.mock
async def test_token_cached_between_calls():
    exch = respx.get("https://api.github.com/copilot_internal/v2/token").mock(
        return_value=httpx.Response(200, json={
            "token": "tok1", "expires_at": 9999999999,
            "endpoints": {"api": "https://api.githubcopilot.com"},
        })
    )
    respx.post("https://api.githubcopilot.com/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "y"}}]})
    )
    p = CopilotProvider(model="gpt-4o", oauth_token="gho")
    await p.chat([Message("user", "1")])
    await p.chat([Message("user", "2")])
    # Token exchanged once, reused on the second call.
    assert exch.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_poll_once_pending():
    device = httpx.Response(200, json={
        "device_code": "dev123",
        "user_code": "ABCD",
        "verification_uri": "https://github.com/login/device",
        "interval": 5,
        "expires_in": 900,
    }).json()
    device = __import__("meetingscribe.llm.copilot_auth", fromlist=["DeviceCode"]).DeviceCode(
        device_code=device["device_code"],
        user_code=device["user_code"],
        verification_uri=device["verification_uri"],
        interval=device["interval"],
        expires_in=device["expires_in"],
    )
    from meetingscribe.llm.copilot_auth import poll_once

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"error": "authorization_pending"})
    )
    status, result = await poll_once(device)
    assert status == "pending"
    assert result == ""


@pytest.mark.asyncio
@respx.mock
async def test_poll_once_ok():
    device = __import__("meetingscribe.llm.copilot_auth", fromlist=["DeviceCode"]).DeviceCode(
        device_code="dev123",
        user_code="ABCD",
        verification_uri="https://github.com/login/device",
        interval=5,
        expires_in=900,
    )
    from meetingscribe.llm.copilot_auth import poll_once

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "gho_ready"})
    )
    status, result = await poll_once(device)
    assert status == "ok"
    assert result == "gho_ready"


@pytest.mark.asyncio
@respx.mock
async def test_poll_once_expired():
    device = __import__("meetingscribe.llm.copilot_auth", fromlist=["DeviceCode"]).DeviceCode(
        device_code="dev123",
        user_code="ABCD",
        verification_uri="https://github.com/login/device",
        interval=5,
        expires_in=900,
    )
    from meetingscribe.llm.copilot_auth import poll_once

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"error": "expired_token"})
    )
    status, result = await poll_once(device)
    assert status == "expired"
    assert result == "expired_token"
