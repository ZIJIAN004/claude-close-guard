"""Smoke tests for the markdown side of MemoryStore (no embedder required)."""

from __future__ import annotations

from pathlib import Path

from claude_close_guard.memory_store import MemoryEntry, MemoryStore, parse_md, serialize_md


def test_serialize_then_parse_round_trip(tmp_path: Path):
    entry = MemoryEntry(
        filename="feedback_x.md",
        name="x rule",
        description="hook",
        type="feedback",
        body="rule body\n\n**Why:** because\n**How to apply:** always",
    )
    p = tmp_path / "feedback_x.md"
    p.write_text(serialize_md(entry), encoding="utf-8")
    parsed = parse_md(p)
    assert parsed is not None
    assert parsed.name == entry.name
    assert parsed.type == entry.type
    assert parsed.body == entry.body


def test_write_entry_collision_appends_index(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem", tmp_path / "vec.sqlite")
    e = MemoryEntry(filename="p.md", name="p", description="d", type="project", body="b")
    p1 = store.write_entry(e)
    p2 = store.write_entry(e)
    assert p1 != p2
    assert p1.name == "p.md"
    assert p2.name == "p_2.md"


def test_update_index_groups_by_type(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem", tmp_path / "vec.sqlite")
    store.write_entry(MemoryEntry("u.md", "user role", "I am X", "user", "body"))
    store.write_entry(MemoryEntry("p.md", "project p", "ongoing", "project", "body"))
    store.write_entry(MemoryEntry("f.md", "feedback f", "rule", "feedback", "body"))
    idx = store.update_index().read_text(encoding="utf-8")
    assert "## User" in idx
    assert "## Feedback" in idx
    assert "## Project" in idx
    assert "[user role](u.md)" in idx
