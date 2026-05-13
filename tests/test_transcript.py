"""Smoke tests for transcript parsing."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_close_guard import transcript as transcript_mod
from claude_close_guard.transcript import (
    Turn,
    _encode_cwd,
    _extract_text,
    find_session_files_for_pid,
    iter_turns,
    load_turns,
    render_for_summary,
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


# --- pid-based session lookup --------------------------------------------

def _make_fake_proc(open_jsonls: list[Path], children: list = None):
    """Build a MagicMock that quacks like a psutil.Process."""
    proc = MagicMock()
    proc.children.return_value = children or []
    proc.open_files.return_value = [MagicMock(path=str(p)) for p in open_jsonls]
    return proc


def test_find_session_files_for_pid_prefers_handle_over_mtime(tmp_path, monkeypatch):
    """The whole point of this fix: when two jsonls share the same cwd, we
    pick the one whose handle is open in the terminal's process tree — NOT
    the one with the newest mtime."""
    cwd = tmp_path / "myproj"
    cwd.mkdir()
    projects_root = tmp_path / "projects"
    encoded_dir = projects_root / _encode_cwd(cwd)
    encoded_dir.mkdir(parents=True)

    # Window A's session — older mtime, but THIS is the one terminal pid holds open.
    session_a = encoded_dir / "aaaa.jsonl"
    session_a.write_text("{}", encoding="utf-8")
    older = time.time() - 600
    import os
    os.utime(session_a, (older, older))

    # Window B's session — newer mtime, NOT held open by our terminal.
    session_b = encoded_dir / "bbbb.jsonl"
    session_b.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(transcript_mod, "PROJECTS_ROOT", projects_root)

    fake_psutil = MagicMock()
    fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    fake_psutil.AccessDenied = type("AccessDenied", (Exception,), {})
    fake_psutil.Process.return_value = _make_fake_proc(
        open_jsonls=[],
        children=[_make_fake_proc([session_a])],
    )

    with patch.dict("sys.modules", {"psutil": fake_psutil}):
        found = find_session_files_for_pid(1234, cwd_filter=cwd)

    assert found == [session_a]


def test_find_session_files_for_pid_filters_to_cwd(tmp_path, monkeypatch):
    """A node child handling a different cwd shouldn't leak into the result."""
    projects_root = tmp_path / "projects"
    cwd_a = tmp_path / "proj_a"
    cwd_b = tmp_path / "proj_b"
    cwd_a.mkdir(); cwd_b.mkdir()
    enc_a = projects_root / _encode_cwd(cwd_a); enc_a.mkdir(parents=True)
    enc_b = projects_root / _encode_cwd(cwd_b); enc_b.mkdir(parents=True)

    s_a = enc_a / "x.jsonl"; s_a.write_text("{}", encoding="utf-8")
    s_b = enc_b / "y.jsonl"; s_b.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(transcript_mod, "PROJECTS_ROOT", projects_root)

    fake_psutil = MagicMock()
    fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    fake_psutil.AccessDenied = type("AccessDenied", (Exception,), {})
    fake_psutil.Process.return_value = _make_fake_proc(
        open_jsonls=[],
        children=[_make_fake_proc([s_a]), _make_fake_proc([s_b])],
    )

    with patch.dict("sys.modules", {"psutil": fake_psutil}):
        found = find_session_files_for_pid(1234, cwd_filter=cwd_a)

    assert found == [s_a]


def test_find_session_files_for_pid_handles_missing_psutil(monkeypatch):
    """If psutil isn't installed we degrade gracefully (return empty list,
    caller falls back to mtime)."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "psutil":
            raise ImportError("nope")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert find_session_files_for_pid(1234) == []


def test_load_turns_falls_back_when_pid_lookup_empty(tmp_path, monkeypatch):
    """No open handle found ⇒ fall back to cwd+mtime instead of returning nothing."""
    cwd = tmp_path / "proj"; cwd.mkdir()
    projects_root = tmp_path / "projects"
    enc = projects_root / _encode_cwd(cwd); enc.mkdir(parents=True)
    session = enc / "s.jsonl"
    session.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(transcript_mod, "PROJECTS_ROOT", projects_root)
    monkeypatch.setattr(
        transcript_mod, "find_session_files_for_pid", lambda *a, **kw: []
    )

    path, turns = load_turns(cwd, pid=9999)
    assert path == session
    assert [t.text for t in turns] == ["hi"]
