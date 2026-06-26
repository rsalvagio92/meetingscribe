import httpx
import pytest
import respx

from meetingscribe.llm.anthropic import AnthropicProvider
from meetingscribe.llm.base import LLMError, Message
from meetingscribe.llm.openai_compat import OpenAICompatProvider


@pytest.mark.asyncio
@respx.mock
async def test_openai_compat_happy_path():
    route = respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "hello world"}}]
        })
    )
    p = OpenAICompatProvider(model="llama3", base_url="http://localhost:11434/v1")
    out = await p.chat([Message("user", "hi")])
    assert out == "hello world"
    assert route.called
    # No api key -> no Authorization header.
    sent = route.calls[0].request
    assert "authorization" not in {k.lower() for k in sent.headers}


@pytest.mark.asyncio
@respx.mock
async def test_openai_compat_sends_bearer_when_key_set():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})
    )
    p = OpenAICompatProvider(model="gpt-4o", base_url="https://api.openai.com/v1", api_key="sk-abc")
    await p.chat([Message("user", "hi")])
    req = respx.calls[0].request
    assert req.headers["authorization"] == "Bearer sk-abc"


@pytest.mark.asyncio
@respx.mock
async def test_openai_compat_http_error_raises():
    respx.post("http://x/v1/chat/completions").mock(return_value=httpx.Response(500, text="boom"))
    p = OpenAICompatProvider(model="m", base_url="http://x/v1")
    with pytest.raises(LLMError):
        await p.chat([Message("user", "hi")])


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_splits_system_and_turns():
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "A"}]})
    )
    p = AnthropicProvider(model="claude-haiku-4-5", api_key="key")
    out = await p.chat([Message("system", "be brief"), Message("user", "hi")])
    assert out == "A"
    body = respx.calls[0].request
    import json
    payload = json.loads(body.content)
    assert payload["system"] == "be brief"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert body.headers["x-api-key"] == "key"
