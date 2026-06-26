"""Encrypted secret store (AES-256-GCM).

Mirrors WildClaude's approach: a single JSON blob on disk, file mode 0600 where
the OS supports it. The master key is derived from a machine-local key file
(auto-generated) so secrets are encrypted at rest without prompting the user for
a passphrase on every launch. Set MEETINGSCRIBE_MASTER_KEY to supply your own.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..paths import DATA_DIR, SECRETS_PATH

_KEY_PATH = DATA_DIR / ".master.key"


def _load_or_create_key() -> bytes:
    env = os.environ.get("MEETINGSCRIBE_MASTER_KEY")
    if env:
        raw = base64.urlsafe_b64decode(_pad(env))
        if len(raw) != 32:
            raise ValueError("MEETINGSCRIBE_MASTER_KEY must decode to 32 bytes")
        return raw

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _KEY_PATH.exists():
        return base64.urlsafe_b64decode(_KEY_PATH.read_text().strip())

    key = AESGCM.generate_key(bit_length=256)
    _KEY_PATH.write_text(base64.urlsafe_b64encode(key).decode())
    _chmod_600(_KEY_PATH)
    return key


def _pad(s: str) -> str:
    return s + "=" * (-len(s) % 4)


def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass  # Windows / unsupported FS — ACLs handle it.


class SecretStore:
    def __init__(self, path: Path = SECRETS_PATH) -> None:
        self.path = path
        self._key = _load_or_create_key()
        self._cache: dict[str, str] | None = None

    def _read(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = {}
            return self._cache
        blob = json.loads(self.path.read_text())
        nonce = base64.b64decode(blob["nonce"])
        ct = base64.b64decode(blob["ciphertext"])
        plaintext = AESGCM(self._key).decrypt(nonce, ct, None)
        self._cache = json.loads(plaintext.decode())
        return self._cache

    def _write(self, data: dict[str, str]) -> None:
        nonce = os.urandom(12)
        ct = AESGCM(self._key).encrypt(nonce, json.dumps(data).encode(), None)
        blob = {
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ct).decode(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(blob))
        _chmod_600(self.path)
        self._cache = data

    def get(self, key: str, default: str | None = None) -> str | None:
        # Resolution order: encrypted store -> environment variable.
        return self._read().get(key) or os.environ.get(key) or default

    def set(self, key: str, value: str) -> None:
        data = dict(self._read())
        data[key] = value
        self._write(data)

    def delete(self, key: str) -> None:
        data = dict(self._read())
        data.pop(key, None)
        self._write(data)

    def names(self) -> list[str]:
        return sorted(self._read().keys())
