"""High-level operations shared by the API and the CLI.

Stateless helpers over (config, store, secrets): offline re-transcription,
note generation, and export. Kept import-light so the API boots without the
heavy STT/LLM deps until those operations are actually invoked.
"""
from __future__ import annotations

import time
from pathlib import Path

from .config import AppConfig
from .llm import build_provider
from .notes import generate_notes, render_markdown, render_pdf
from .store.db import MeetingStore
from .store.secrets import SecretStore


def offline_transcribe(
    cfg: AppConfig,
    store: MeetingStore,
    meeting_id: str,
    *,
    model: str | None = None,
) -> tuple[str, str]:
    """Re-transcribe a saved recording with the high-accuracy offline model.

    Pass ``model`` to run a specific (heavier) Whisper model for this pass —
    e.g. when the real-time captions weren't precise enough. Returns
    ``(transcript, model_used)``.
    """
    meeting = store.get(meeting_id)
    if not meeting:
        raise ValueError(f"meeting not found: {meeting_id}")
    audio_path = meeting.get("audio_path")
    if not audio_path or not Path(audio_path).exists():
        raise FileNotFoundError(f"recording missing for {meeting_id}")

    model_used = (model or cfg.stt.offline_model or "").strip()
    if not model_used:
        raise ValueError("no offline model configured")

    from .stt.engine import WhisperEngine

    engine = WhisperEngine(cfg.stt)
    segments = engine.transcribe_file(audio_path, offline=True, model=model_used)
    transcript = "\n".join(s.text for s in segments if s.text).strip()
    store.update(
        meeting_id,
        transcript=transcript,
        transcript_quality="offline",
        status="transcribed",
    )
    return transcript, model_used


async def make_notes(
    cfg: AppConfig,
    store: MeetingStore,
    secrets: SecretStore,
    meeting_id: str,
    *,
    include_transcript: bool = True,
) -> dict:
    """Generate structured notes + markdown report for a meeting and persist."""
    meeting = store.get(meeting_id)
    if not meeting:
        raise ValueError(f"meeting not found: {meeting_id}")
    transcript = (meeting.get("transcript") or "").strip()
    if not transcript:
        raise ValueError("no transcript to interpret; transcribe first")

    provider = build_provider(cfg.llm, secrets)
    notes = await generate_notes(
        provider,
        meeting["title"],
        transcript,
        temperature=cfg.llm.temperature,
        max_tokens=cfg.llm.max_tokens,
    )
    report = render_markdown(
        meeting["title"],
        notes,
        started_at=meeting.get("started_at"),
        duration_secs=meeting.get("duration_secs"),
        transcript=transcript,
        include_transcript=include_transcript,
    )
    store.set_notes(meeting_id, notes.to_dict(), report)
    return {"notes": notes.to_dict(), "report_md": report}


def export(cfg: AppConfig, store: MeetingStore, meeting_id: str, fmt: str = "md") -> str:
    """Write the report to the output dir. Returns the file path."""
    meeting = store.get(meeting_id)
    if not meeting:
        raise ValueError(f"meeting not found: {meeting_id}")
    report = meeting.get("report_md")
    if not report:
        raise ValueError("no report generated yet")

    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in meeting["title"]).strip()
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(meeting.get("started_at", time.time())))
    base = f"{stamp}_{safe or meeting_id}"

    if fmt == "pdf":
        path = out_dir / f"{base}.pdf"
        render_pdf(report, str(path))
    else:
        path = out_dir / f"{base}.md"
        path.write_text(report, encoding="utf-8")
    return str(path)
