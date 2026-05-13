"""Read the most recent Claude Code session transcript (jsonl).

The harness writes one JSONL file per session under
~/.claude/projects/<encoded-cwd>/<session-id>.jsonl.

Each line is a record with a `type` field. We only care about `user` and
`assistant` records; everything else is housekeeping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal

PROJECTS_ROOT = Path.home() / ".claude" / "projects"


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    text: str
    timestamp: str | None = None


def _encode_cwd(cwd: Path) -> str:
    """Replicate Claude Code's cwd → directory-name encoding.

    Observed: `C:\\Users\\zijia` → `C--Users-zijia` (drive colon+backslash → `--`,
    other backslashes → `-`).
    """
    s = str(cwd)
    s = s.replace(":\\", "--").replace("\\", "-").replace("/", "-")
    return s


def find_latest_session_file(cwd: Path | None = None) -> Path | None:
    """Find the most recently modified .jsonl session file.

    If `cwd` is given, only search that project's subdirectory.
    """
    if cwd is not None:
        candidates_dir = PROJECTS_ROOT / _encode_cwd(cwd)
        if not candidates_dir.exists():
            return None
        candidates: Iterable[Path] = candidates_dir.glob("*.jsonl")
    else:
        candidates = PROJECTS_ROOT.rglob("*.jsonl")

    files = [p for p in candidates if p.is_file() and "subagents" not in p.parts]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def find_session_files_for_pid(
    pid: int, cwd_filter: Path | None = None
) -> list[Path]:
    """Return jsonl session files currently held open by any process inside
    the process tree rooted at `pid`, sorted most-recently-modified first.

    The terminal window's owner pid (from AHK) usually owns one or more child
    `node.exe` processes — the running Claude Code instances. Each Claude
    instance keeps an open handle to its own session jsonl file, so walking
    the tree and inspecting `open_files()` gives us the *actual* sessions
    belonging to that terminal, instead of just the most-recently-touched
    jsonl in the cwd (which is what mtime-only selection picks, and which
    breaks when two terminal windows share a cwd).
    """
    try:
        import psutil
    except ImportError:
        return []
    try:
        root = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []

    procs = [root]
    try:
        procs.extend(root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    target_dir: Path | None = None
    if cwd_filter is not None:
        target_dir = PROJECTS_ROOT / _encode_cwd(cwd_filter)

    try:
        projects_root_resolved = PROJECTS_ROOT.resolve()
    except OSError:
        projects_root_resolved = PROJECTS_ROOT

    found: dict[Path, float] = {}
    for p in procs:
        try:
            open_files = p.open_files()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for f in open_files:
            fp = Path(f.path)
            if fp.suffix.lower() != ".jsonl":
                continue
            try:
                parent_resolved = fp.parent.resolve()
            except OSError:
                continue
            # Must live under ~/.claude/projects/...
            if (
                parent_resolved != projects_root_resolved
                and projects_root_resolved not in parent_resolved.parents
            ):
                continue
            if target_dir is not None:
                try:
                    if parent_resolved != target_dir.resolve():
                        continue
                except OSError:
                    if parent_resolved != target_dir:
                        continue
            try:
                found[fp] = fp.stat().st_mtime
            except OSError:
                found[fp] = 0.0

    return sorted(found.keys(), key=lambda x: found[x], reverse=True)


def _extract_text(content: object) -> str:
    """Pull plain text out of a message.content field.

    Content can be:
    - a plain string (legacy user messages)
    - a list of blocks: {type: "text"|"thinking"|"tool_use"|"tool_result", ...}
    We collect text + thinking + tool_result text. tool_use args are stringified.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(str(block.get("text", "")))
        elif btype == "thinking":
            t = block.get("thinking") or block.get("text", "")
            if t:
                parts.append(f"[thinking] {t}")
        elif btype == "tool_use":
            name = block.get("name", "?")
            parts.append(f"[tool_use:{name}]")
        elif btype == "tool_result":
            inner = block.get("content")
            inner_text = _extract_text(inner) if isinstance(inner, list) else str(inner or "")
            parts.append(f"[tool_result] {inner_text[:400]}")
    return "\n".join(p for p in parts if p)


def iter_turns(session_file: Path) -> Iterator[Turn]:
    with session_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = obj.get("type")
            if t not in ("user", "assistant"):
                continue
            msg = obj.get("message", {}) or {}
            role = msg.get("role", t)
            if role not in ("user", "assistant"):
                continue
            text = _extract_text(msg.get("content"))
            if not text.strip():
                continue
            yield Turn(role=role, text=text, timestamp=obj.get("timestamp"))


def load_turns(
    cwd: Path | None = None, pid: int | None = None
) -> tuple[Path | None, list[Turn]]:
    """Load all turns from the session that belongs to the given terminal pid.

    When `pid` is provided we first try to identify the jsonl by walking the
    terminal's process tree (see `find_session_files_for_pid`). This is the
    only way to distinguish two Claude Code windows that happen to share a
    cwd — mtime alone picks whichever was most recently active, which is
    wrong when the user closes a different window.

    Falls back to the cwd+mtime heuristic if pid lookup yields nothing
    (psutil missing, process gone, no open jsonl handles, etc.).
    """
    path: Path | None = None
    if pid is not None:
        candidates = find_session_files_for_pid(pid, cwd_filter=cwd)
        if candidates:
            path = candidates[0]
    if path is None:
        path = find_latest_session_file(cwd)
    if path is None:
        return None, []
    return path, list(iter_turns(path))


def render_for_summary(turns: list[Turn], max_chars: int = 40000) -> str:
    """Format turns as a single string suitable for an LLM summarizer.

    Drops thinking blocks and trims to `max_chars`, keeping the tail (most
    recent turns matter most for memory curation).
    """
    lines: list[str] = []
    for turn in turns:
        text = turn.text
        # Strip thinking blocks from the rendered transcript — they bloat the
        # summary input and rarely contain user-facing decisions.
        text = "\n".join(
            ln for ln in text.splitlines() if not ln.startswith("[thinking]")
        )
        if not text.strip():
            continue
        prefix = "User" if turn.role == "user" else "Assistant"
        lines.append(f"## {prefix}\n{text}")
    rendered = "\n\n".join(lines)
    if len(rendered) > max_chars:
        rendered = "...[earlier turns trimmed]...\n\n" + rendered[-max_chars:]
    return rendered
