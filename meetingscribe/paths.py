"""Cross-platform data locations.

Code lives in the repo. User data (recordings, DB, secrets, config, exports)
lives in a per-user app dir, overridable with MEETINGSCRIBE_DATA_DIR.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_data_dir() -> Path:
    override = os.environ.get("MEETINGSCRIBE_DATA_DIR")
    if override:
        return Path(override).expanduser()

    home = Path.home()
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return base / "MeetingScribe"
    if sys.platform == "darwin":  # macOS
        return home / "Library" / "Application Support" / "MeetingScribe"
    # Linux / other
    base = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return base / "meetingscribe"


DATA_DIR = _default_data_dir()
RECORDINGS_DIR = DATA_DIR / "recordings"
EXPORTS_DIR = DATA_DIR / "exports"
MODELS_DIR = DATA_DIR / "models"
DB_PATH = DATA_DIR / "meetingscribe.db"
SECRETS_PATH = DATA_DIR / "secrets.enc.json"
CONFIG_PATH = DATA_DIR / "config.json"


def ensure_dirs() -> None:
    for d in (DATA_DIR, RECORDINGS_DIR, EXPORTS_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
