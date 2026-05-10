"""Smoke tests for transcript parsing."""

from __future__ import annotations

import json
from pathlib import Path

from claude_close_guard.transcript import (
    Turn,
    iter_turns,
    render_for_summary,
    _extract_text,
)


def test_extract_text_string():
    assert _extract_text("hello") == "hello"


def test_extract_text_blocks():
    blocks = [
        {"type": "text", "text": "answer"},
        {"type": "thinking", "thinking": "ponder"},
        {"type": "tool_use", "name": "Read"},
        {"type": "tool_result", "content": [{"type": "text", "text": "file body"}]},
    ]
    out = _extract_text(blocks)
    assert "answer" in out
    assert "[thinking] ponder" in out
    assert "[tool_use:Read]" in out
    assert "file body" in out


def test_iter_turns_skips_non_messages(tmp_path: Path):
    p = tmp_path / "session.jsonl"
    lines = [
        {"type": "permission-mode", "permissionMode": "default"},
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "message": {"role": "assistant",
                                          "content": [{"type": "text", "text": "hello"}]}},
        {"type": "ai-title", "title": "x"},
    ]
    p.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    turns = list(iter_turns(p))
    assert [t.role for t in turns] == ["user", "assistant"]
    assert turns[0].text == "hi"
    assert turns[1].text == "hello"


def test_render_for_summary_strips_thinking():
    turns = [
        Turn(role="user", text="ask"),
        Turn(role="assistant", text="[thinking] internal\nreal answer"),
    ]
    rendered = render_for_summary(turns)
    assert "internal" not in rendered
    assert "real answer" in rendered


def test_render_for_summary_truncates_head():
    turns = [Turn(role="user", text="x" * 1000) for _ in range(100)]
    rendered = render_for_summary(turns, max_chars=2000)
    assert rendered.startswith("...[earlier turns trimmed]...")
    assert len(rendered) < 2200
