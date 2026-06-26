import os
import tempfile
from pathlib import Path

from meetingscribe.store.secrets import SecretStore


def test_roundtrip_and_encryption_at_rest():
    p = Path(tempfile.mkdtemp()) / "secrets.enc.json"
    s = SecretStore(path=p)
    s.set("GITHUB_COPILOT_OAUTH_TOKEN", "ghp_secretvalue123")
    assert s.get("GITHUB_COPILOT_OAUTH_TOKEN") == "ghp_secretvalue123"
    # Plaintext must not appear on disk.
    raw = p.read_text()
    assert "ghp_secretvalue123" not in raw
    assert "ciphertext" in raw


def test_persists_across_instances():
    p = Path(tempfile.mkdtemp()) / "secrets.enc.json"
    SecretStore(path=p).set("A", "1")
    assert SecretStore(path=p).get("A") == "1"


def test_env_fallback(monkeypatch):
    p = Path(tempfile.mkdtemp()) / "secrets.enc.json"
    s = SecretStore(path=p)
    monkeypatch.setenv("ONLY_IN_ENV", "envval")
    assert s.get("ONLY_IN_ENV") == "envval"


def test_delete_and_names():
    p = Path(tempfile.mkdtemp()) / "secrets.enc.json"
    s = SecretStore(path=p)
    s.set("X", "1")
    s.set("Y", "2")
    assert s.names() == ["X", "Y"]
    s.delete("X")
    assert s.names() == ["Y"]
