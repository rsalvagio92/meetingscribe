"""SQLite meeting library: sessions, transcripts, generated notes."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..paths import DB_PATH, ensure_dirs

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    started_at    REAL NOT NULL,
    ended_at      REAL,
    duration_secs REAL DEFAULT 0,
    audio_path    TEXT,
    transcript    TEXT DEFAULT '',
    transcript_quality TEXT DEFAULT 'realtime',  -- realtime | offline
    notes_json    TEXT,
    report_md     TEXT,
    status        TEXT DEFAULT 'recording',       -- recording | recorded | transcribed | done
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meetings_started ON meetings(started_at DESC);
"""


class MeetingStore:
    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        ensure_dirs()
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def create(self, meeting_id: str, title: str, started_at: float, audio_path: str | None) -> None:
        self._conn.execute(
            "INSERT INTO meetings (id, title, started_at, audio_path, status, created_at) "
            "VALUES (?, ?, ?, ?, 'recording', ?)",
            (meeting_id, title, started_at, audio_path, time.time()),
        )
        self._conn.commit()

    def update(self, meeting_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(
            f"UPDATE meetings SET {cols} WHERE id = ?",
            (*fields.values(), meeting_id),
        )
        self._conn.commit()

    def set_notes(self, meeting_id: str, notes: dict, report_md: str) -> None:
        self.update(
            meeting_id,
            notes_json=json.dumps(notes, ensure_ascii=False),
            report_md=report_md,
            status="done",
        )

    def get(self, meeting_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def list(self, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, title, started_at, ended_at, duration_secs, status, "
            "transcript_quality FROM meetings ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, meeting_id: str) -> None:
        self._conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("notes_json"):
        try:
            d["notes"] = json.loads(d["notes_json"])
        except json.JSONDecodeError:
            d["notes"] = None
    return d
