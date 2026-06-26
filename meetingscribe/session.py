"""Live meeting session: wires the recorder to live transcription and the store.

A session goes: recording -> recorded -> transcribed -> done.
The offline high-accuracy re-pass and note generation happen after stop().
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .audio.recorder import Recorder
from .config import AppConfig
from .paths import RECORDINGS_DIR
from .store.db import MeetingStore


class LiveSession:
    def __init__(self, cfg: AppConfig, store: MeetingStore, title: str = "") -> None:
        self.cfg = cfg
        self.store = store
        self.id = f"meeting_{int(time.time() * 1000)}"
        self.title = title or "Untitled Meeting"
        self.started_at = time.time()
        self.audio_path = str(RECORDINGS_DIR / f"{self.id}.wav")
        self.live_segments: list[str] = []
        self._lock = threading.Lock()
        self._engine = None  # lazy WhisperEngine
        self._recorder: Recorder | None = None

    def _ensure_engine(self):
        if self._engine is None:
            from .stt.engine import WhisperEngine

            self._engine = WhisperEngine(self.cfg.stt)
        return self._engine

    def _on_chunk(self, audio) -> None:
        # Best-effort live transcription. Failures here never stop recording.
        try:
            engine = self._ensure_engine()
            segs = engine.transcribe_realtime(audio)
            text = " ".join(s.text for s in segs).strip()
            if text:
                with self._lock:
                    self.live_segments.append(text)
        except Exception:
            pass

    def start(self) -> None:
        Path(RECORDINGS_DIR).mkdir(parents=True, exist_ok=True)
        self.store.create(self.id, self.title, self.started_at, self.audio_path)
        self._recorder = Recorder(self.cfg.audio, self.audio_path, on_chunk=self._on_chunk)
        self._recorder.start()

    def live_transcript(self) -> str:
        with self._lock:
            return "\n".join(self.live_segments)

    def stop(self) -> dict:
        if self._recorder:
            self._recorder.stop()
        ended = time.time()
        duration = ended - self.started_at
        transcript = self.live_transcript()
        self.store.update(
            self.id,
            ended_at=ended,
            duration_secs=duration,
            transcript=transcript,
            transcript_quality="realtime",
            status="recorded",
        )
        return {"id": self.id, "duration_secs": duration, "transcript": transcript}
