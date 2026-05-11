"""Summarize a Claude Code conversation and propose memory candidates.

Two backends, picked in order:
  1. `claude -p --json-schema` CLI — reuses Claude Code's OAuth (no API key needed)
  2. anthropic Python SDK — requires ANTHROPIC_API_KEY env var

If neither is available, returns a trivial Summary so the popup can still load.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Literal

MemoryType = Literal["user", "feedback", "project", "reference"]


@dataclass
class MemoryCandidate:
    title: str
    type: MemoryType
    description: str
    body: str
    suggested_filename: str


@dataclass
class Summary:
    headline: str
    bullets: list[str]
    candidates: list[MemoryCandidate] = field(default_factory=list)


SYSTEM_PROMPT = """You are a conversation curator for Claude Code's persistent memory system.

Given a transcript of a single Claude Code session, produce:
1. A headline (one sentence, ≤60 chars) summarizing the core of the session.
2. 3-6 bullets describing what happened (decisions, outcomes, blockers).
3. A list of memory candidates worth saving.

Memory types — pick the one that fits:
- user      : the user's role, preferences, knowledge
- feedback  : guidance from the user about how to work (corrections OR validated approaches)
- project   : ongoing work, decisions, deadlines, motivations not derivable from code
- reference : pointers to external systems (Linear projects, dashboards, etc.)

DO NOT propose memories for:
- Code patterns, file paths, architecture (re-derivable by reading the repo)
- Git history, who-changed-what (`git log` is authoritative)
- One-off debugging tricks (the fix is in the code)
- Ephemeral task state (in-progress work)

For each candidate, provide:
- title: short kebab-case-ish title (used as filename stem)
- type: one of user|feedback|project|reference
- description: one line ≤150 chars (used as MEMORY.md hook)
- body: the actual memory content. For feedback/project, structure as: rule/fact, then "Why:" line and "How to apply:" line.
- suggested_filename: like "feedback_close_guard.md" or "project_xxx.md"

Return STRICT JSON only:
{
  "headline": "...",
  "bullets": ["...", "..."],
  "candidates": [
    {"title": "...", "type": "...", "description": "...", "body": "...", "suggested_filename": "..."}
  ]
}

If nothing meaningful is worth memorizing, return candidates: []."""


_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "type": {"type": "string",
                             "enum": ["user", "feedback", "project", "reference"]},
                    "description": {"type": "string"},
                    "body": {"type": "string"},
                    "suggested_filename": {"type": "string"},
                },
                "required": ["title", "type", "description", "body", "suggested_filename"],
            },
        },
    },
    "required": ["headline", "bullets", "candidates"],
}


def _strip_code_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def _parse_summary_json(text: str) -> "Summary":
    text = _strip_code_fence(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return Summary(headline="(summarizer returned non-JSON)", bullets=[text[:500]])
        data = json.loads(match.group(0))

    candidates: list[MemoryCandidate] = []
    for c in data.get("candidates", []) or []:
        try:
            candidates.append(
                MemoryCandidate(
                    title=str(c["title"]).strip(),
                    type=c["type"],
                    description=str(c["description"]).strip(),
                    body=str(c["body"]).strip(),
                    suggested_filename=str(c.get("suggested_filename")
                                           or f"{c['type']}_{c['title']}.md").strip(),
                )
            )
        except (KeyError, TypeError):
            continue

    return Summary(
        headline=str(data.get("headline", "")).strip(),
        bullets=[str(b).strip() for b in (data.get("bullets") or [])],
        candidates=candidates,
    )


def _summarize_via_claude_cli(
    transcript_text: str,
    model: str | None = None,
    timeout_s: float = 120.0,
) -> Summary:
    """Use the `claude` CLI in print mode with --json-schema for structured output.

    Reuses Claude Code's existing OAuth session — no API key needed.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise RuntimeError("`claude` CLI not on PATH")

    prompt = (
        SYSTEM_PROMPT
        + "\n\n<transcript>\n" + transcript_text + "\n</transcript>\n\n"
        + "Return the JSON object only."
    )
    # --output-format=json wraps the real payload under .structured_output.
    # --bare can't be used here: it disables OAuth/keychain reads, requiring
    # ANTHROPIC_API_KEY. We want to reuse Claude Code's existing OAuth session.
    args = [claude_bin, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(_JSON_SCHEMA)]
    if model:
        args += ["--model", model]
    args.append(prompt)
    proc = subprocess.run(
        args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"`claude -p` exited {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}"
        )

    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude reported error: {envelope.get('result', '')[:500]}")

    structured = envelope.get("structured_output")
    if not isinstance(structured, dict):
        # Fallback: the model returned text instead of using the schema.
        return _parse_summary_json(envelope.get("result", ""))
    return _parse_summary_json(json.dumps(structured))


def _summarize_via_sdk(
    transcript_text: str,
    model: str,
    max_tokens: int,
    api_key: str | None,
) -> Summary:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"<transcript>\n{transcript_text}\n</transcript>\n\nReturn the JSON.",
        }],
    )
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    return _parse_summary_json(text)


def summarize(
    transcript_text: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 2000,
    api_key: str | None = None,
) -> Summary:
    """Summarize via `claude -p` (preferred) or anthropic SDK (fallback)."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    try:
        return _summarize_via_claude_cli(transcript_text, model=model)
    except (FileNotFoundError, subprocess.TimeoutExpired,
            subprocess.SubprocessError, RuntimeError, json.JSONDecodeError) as exc:
        cli_err = f"{type(exc).__name__}: {exc}"

    if api_key:
        try:
            return _summarize_via_sdk(transcript_text, model, max_tokens, api_key)
        except Exception as exc:
            return Summary(
                headline=f"(summarizer fallback failed: {type(exc).__name__})",
                bullets=[f"claude -p: {cli_err}", f"sdk: {exc}"],
                candidates=[],
            )

    return Summary(
        headline="(no summarizer available)",
        bullets=[
            f"claude -p failed: {cli_err}",
            "ANTHROPIC_API_KEY not set, can't fall back to SDK.",
            "Install Claude Code CLI on PATH or set ANTHROPIC_API_KEY.",
        ],
        candidates=[],
    )
