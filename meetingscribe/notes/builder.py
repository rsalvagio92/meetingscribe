"""Turn a transcript into structured notes + a Markdown report (+ optional PDF)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..llm.base import LLMProvider
from .prompts import build_extraction_messages


@dataclass
class ActionItem:
    task: str
    owner: str | None = None
    due: str | None = None


@dataclass
class MeetingNotes:
    summary: str = ""
    topics: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "topics": self.topics,
            "decisions": self.decisions,
            "action_items": [a.__dict__ for a in self.action_items],
            "open_questions": self.open_questions,
            "follow_ups": self.follow_ups,
        }


def _extract_json(raw: str) -> dict:
    """Tolerant JSON extraction: strip code fences, grab the first {...} block."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("LLM returned no JSON object")
        return json.loads(match.group(0))


def parse_notes(raw: str) -> MeetingNotes:
    data = _extract_json(raw)
    items = []
    for a in data.get("action_items", []) or []:
        if isinstance(a, str):
            items.append(ActionItem(task=a))
        elif isinstance(a, dict):
            items.append(
                ActionItem(
                    task=a.get("task", "").strip(),
                    owner=(a.get("owner") or None),
                    due=(a.get("due") or None),
                )
            )
    return MeetingNotes(
        summary=data.get("summary", "").strip(),
        topics=[t for t in data.get("topics", []) if t],
        decisions=[d for d in data.get("decisions", []) if d],
        action_items=[i for i in items if i.task],
        open_questions=[q for q in data.get("open_questions", []) if q],
        follow_ups=[f for f in data.get("follow_ups", []) if f],
    )


async def generate_notes(
    provider: LLMProvider,
    title: str,
    transcript: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> MeetingNotes:
    messages = build_extraction_messages(title, transcript)
    raw = await provider.chat(messages, temperature=temperature, max_tokens=max_tokens)
    return parse_notes(raw)


def render_markdown(
    title: str,
    notes: MeetingNotes,
    *,
    started_at: float | None = None,
    duration_secs: float | None = None,
    transcript: str | None = None,
    include_transcript: bool = True,
) -> str:
    lines: list[str] = [f"# {title or 'Untitled Meeting'}", ""]

    if started_at:
        dt = datetime.fromtimestamp(started_at, tz=timezone.utc).astimezone()
        lines.append(f"**Date:** {dt.strftime('%Y-%m-%d %H:%M')}")
    if duration_secs:
        lines.append(f"**Duration:** {round(duration_secs / 60)} min")
    lines.append("")

    lines += ["## Summary", notes.summary or "_(none)_", ""]

    if notes.topics:
        lines += ["## Topics", *[f"- {t}" for t in notes.topics], ""]

    lines.append("## Action Items")
    if notes.action_items:
        for a in notes.action_items:
            meta = []
            if a.owner:
                meta.append(f"owner: {a.owner}")
            if a.due:
                meta.append(f"due: {a.due}")
            suffix = f" ({', '.join(meta)})" if meta else ""
            lines.append(f"- [ ] {a.task}{suffix}")
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("## Decisions")
    lines += ([f"- {d}" for d in notes.decisions] if notes.decisions else ["_(none)_"])
    lines.append("")

    if notes.open_questions:
        lines += ["## Open Questions", *[f"- {q}" for q in notes.open_questions], ""]
    if notes.follow_ups:
        lines += ["## Follow-ups", *[f"- {f}" for f in notes.follow_ups], ""]

    if include_transcript and transcript:
        lines += ["## Full Transcript", "", transcript, ""]

    return "\n".join(lines)


def render_pdf(markdown_text: str, out_path: str) -> str:
    """Render markdown -> HTML -> PDF via WeasyPrint (optional dependency)."""
    try:
        from markdown_it import MarkdownIt
        from weasyprint import HTML  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "PDF export needs extras: pip install 'meetingscribe[pdf]'"
        ) from e
    html_body = MarkdownIt().render(markdown_text)
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>body{{font-family:sans-serif;max-width:48rem;margin:2rem auto;line-height:1.5}}
h1{{border-bottom:2px solid #333}} code,pre{{background:#f4f4f4}}</style>
</head><body>{html_body}</body></html>"""
    HTML(string=html).write_pdf(out_path)
    return out_path
