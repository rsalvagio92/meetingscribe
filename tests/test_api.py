"""API smoke tests with the real store/secrets but mocked LLM + no audio."""
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from meetingscribe.api.server import AppState, create_app


@pytest.fixture
def client():
    state = AppState()
    app = create_app(state)
    return TestClient(app), state


def test_health(client):
    c, _ = client
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_config_roundtrip(client):
    c, _ = client
    r = c.get("/api/config")
    assert r.json()["llm"]["provider"] == "openai_compat"
    r = c.put("/api/config", json={"patch": {"llm": {"provider": "copilot", "model": "gpt-4o"}}})
    assert r.json()["llm"]["provider"] == "copilot"
    assert r.json()["llm"]["model"] == "gpt-4o"


def test_secrets_names_only(client):
    c, _ = client
    c.post("/api/secrets", json={"key": "GITHUB_COPILOT_OAUTH_TOKEN", "value": "secret"})
    r = c.get("/api/secrets")
    assert "GITHUB_COPILOT_OAUTH_TOKEN" in r.json()["names"]
    # Value never returned.
    assert "secret" not in r.text


def test_meeting_lifecycle_with_mocked_llm(client):
    c, state = client
    # Seed a recorded meeting directly in the store (no audio hardware).
    mid = "meeting_test1"
    state.store.create(mid, "Planning", 1718000000.0, None)
    state.store.update(
        mid,
        transcript="We agreed to ship the beta. Gighy will write the spec.",
        status="recorded",
        duration_secs=300,
    )

    # Configure a local openai-compatible provider and mock its endpoint.
    state.cfg.update({"llm": {"provider": "openai_compat", "base_url": "http://llm.local/v1"}})

    notes_json = (
        '{"summary":"Agreed to ship beta.","topics":["beta"],'
        '"decisions":["Ship beta"],'
        '"action_items":[{"task":"write spec","owner":"Gighy","due":null}],'
        '"open_questions":[],"follow_ups":[]}'
    )
    with respx.mock:
        respx.post("http://llm.local/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {"content": notes_json}}]})
        )
        r = c.post(f"/api/meetings/{mid}/notes", json={"include_transcript": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["notes"]["summary"] == "Agreed to ship beta."
    assert body["notes"]["action_items"][0]["owner"] == "Gighy"
    assert "# Planning" in body["report_md"]

    # Library lists it; export writes a file.
    assert any(m["id"] == mid for m in c.get("/api/meetings").json()["meetings"])
    r = c.post(f"/api/meetings/{mid}/export?fmt=md")
    assert r.status_code == 200
    assert r.json()["path"].endswith(".md")


def test_notes_without_transcript_400(client):
    c, state = client
    state.store.create("empty1", "Empty", 1718000000.0, None)
    r = c.post("/api/meetings/empty1/notes", json={})
    assert r.status_code == 400


def test_stt_models_listing(client):
    c, _ = client
    r = c.get("/api/stt/models")
    assert r.status_code == 200
    body = r.json()
    assert "large-v3" in body["models"]
    assert body["realtime"] == "base"
    assert body["offline"] == "large-v3"


def test_offline_transcribe_model_override(client, monkeypatch, tmp_path):
    c, state = client
    # Seed a recorded meeting pointing at a real (empty) file on disk.
    mid = "meeting_override"
    audio = tmp_path / f"{mid}.wav"
    audio.write_bytes(b"RIFF")  # existence is all offline_transcribe checks
    state.store.create(mid, "Imprecise", 1718000000.0, str(audio))
    state.store.update(mid, transcript="garbled live text", status="recorded")

    # Capture which model the engine was asked to use — no real Whisper.
    used = {}

    class FakeSeg:
        def __init__(self, text):
            self.text = text

    class FakeEngine:
        def __init__(self, cfg):
            pass

        def transcribe_file(self, path, *, offline=True, model=None):
            used["model"] = model
            used["offline"] = offline
            return [FakeSeg("clean accurate transcript")]

    import meetingscribe.stt.engine as engine_mod

    monkeypatch.setattr(engine_mod, "WhisperEngine", FakeEngine)

    r = c.post(f"/api/meetings/{mid}/transcribe?model=large-v3")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] == "clean accurate transcript"
    assert body["model"] == "large-v3"
    assert body["quality"] == "offline"
    assert used == {"model": "large-v3", "offline": True}

    # No explicit model → falls back to the configured offline model.
    r = c.post(f"/api/meetings/{mid}/transcribe")
    assert r.status_code == 200
    assert used["model"] == "large-v3"  # cfg.stt.offline_model default
    assert r.json()["model"] == "large-v3"
