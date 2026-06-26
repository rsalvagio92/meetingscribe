"""Prompt templates for meeting interpretation. User-overridable later."""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a precise meeting analyst. You read a raw, possibly noisy "
    "transcript and extract structured, faithful notes. Never invent facts, "
    "names, dates, or decisions that are not supported by the transcript. "
    "If something is unclear, say so rather than guessing. "
    "Respond in the same language as the transcript."
)

# The model must return strict JSON matching this shape.
EXTRACTION_PROMPT = """Analyze this meeting transcript and produce structured output.

TITLE: {title}

TRANSCRIPT:
{transcript}

---

Return ONLY a JSON object, no prose, no code fences, with exactly these keys:
{{
  "summary": "2-4 sentence neutral summary of what the meeting covered",
  "topics": ["topic 1", "topic 2"],
  "decisions": ["decision made (who decided, if stated)"],
  "action_items": [
    {{"task": "what", "owner": "who or null", "due": "when or null"}}
  ],
  "open_questions": ["unresolved question or risk raised"],
  "follow_ups": ["explicit next step / follow-up agreed"]
}}

Rules:
- Keep entries short and specific.
- owner/due are null when not stated. Do not infer them.
- Empty arrays are fine when a category has nothing.
- Output must be valid JSON parseable by a strict parser."""


def build_extraction_messages(title: str, transcript: str):
    from ..llm.base import Message

    return [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(
            role="user",
            content=EXTRACTION_PROMPT.format(title=title or "Untitled Meeting", transcript=transcript),
        ),
    ]
