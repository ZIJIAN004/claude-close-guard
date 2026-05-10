"""Summarize a Claude Code conversation and propose memory candidates."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Literal

import anthropic

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


def _strip_code_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def summarize(
    transcript_text: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 2000,
    api_key: str | None = None,
) -> Summary:
    """Call Claude API to summarize and propose memory candidates."""
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"<transcript>\n{transcript_text}\n</transcript>\n\nReturn the JSON.",
            }
        ],
    )

    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text

    text = _strip_code_fence(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Best-effort recovery: extract the largest {...} block
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
