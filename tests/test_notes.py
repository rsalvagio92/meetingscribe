import pytest

from meetingscribe.llm.base import Message
from meetingscribe.notes.builder import (
    MeetingNotes,
    generate_notes,
    parse_notes,
    render_markdown,
)


def test_parse_clean_json():
    raw = """{
      "summary": "We discussed Q3 roadmap.",
      "topics": ["roadmap", "hiring"],
      "decisions": ["Ship beta in August"],
      "action_items": [{"task": "Draft spec", "owner": "Gighy", "due": "Friday"}],
      "open_questions": ["Budget for hiring?"],
      "follow_ups": ["Schedule design review"]
    }"""
    n = parse_notes(raw)
    assert n.summary.startswith("We discussed")
    assert n.topics == ["roadmap", "hiring"]
    assert n.action_items[0].owner == "Gighy"
    assert n.action_items[0].due == "Friday"


def test_parse_with_code_fence_and_prose():
    raw = 'Here you go:\n```json\n{"summary":"S","action_items":["do X"]}\n```\nThanks!'
    n = parse_notes(raw)
    assert n.summary == "S"
    # String action item normalized to ActionItem(task=...).
    assert n.action_items[0].task == "do X"
    assert n.action_items[0].owner is None


def test_parse_missing_keys_defaults():
    n = parse_notes('{"summary": "only summary"}')
    assert n.summary == "only summary"
    assert n.topics == []
    assert n.action_items == []


def test_render_markdown_structure():
    n = MeetingNotes(
        summary="Sum",
        topics=["t1"],
        decisions=["d1"],
        action_items=[],
        open_questions=["q1"],
        follow_ups=["f1"],
    )
    md = render_markdown("Standup", n, started_at=1718000000, duration_secs=600,
                         transcript="hello", include_transcript=True)
    assert "# Standup" in md
    assert "## Summary" in md
    assert "## Action Items" in md
    assert "_(none)_" in md  # empty action items
    assert "## Decisions" in md
    assert "- d1" in md
    assert "## Full Transcript" in md
    assert "Duration:** 10 min" in md


class _FakeProvider:
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply
        self.seen: list[Message] = []

    async def chat(self, messages, *, temperature=0.2, max_tokens=2000):
        self.seen = messages
        return self.reply


@pytest.mark.asyncio
async def test_generate_notes_uses_provider():
    fake = _FakeProvider('{"summary":"Generated","action_items":[]}')
    notes = await generate_notes(fake, "Title", "transcript text")
    assert notes.summary == "Generated"
    # System + user messages were sent; transcript embedded.
    assert any("transcript text" in m.content for m in fake.seen)
    assert fake.seen[0].role == "system"
