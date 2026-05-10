"""Config loader. Reads ~/.claude-close-guard/config.yaml, falls back to defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".claude-close-guard" / "config.yaml"


@dataclass
class Config:
    memory_dir: Path
    vector_db: Path
    embedding_model: str = "BAAI/bge-base-zh-v1.5"
    embedding_device: str = "cpu"
    summarizer_model: str = "claude-haiku-4-5-20251001"
    summarizer_max_tokens: int = 2000
    target_window_classes: list[str] = field(
        default_factory=lambda: ["CASCADIA_HOSTING_WINDOW_CLASS", "ConsoleWindowClass"]
    )
    mcp_top_k: int = 5
    mcp_hybrid_alpha: float = 0.5
    min_turns_to_prompt: int = 3
    ui_window_size: str = "720x540"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or DEFAULT_CONFIG_PATH
        raw: dict[str, Any] = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}

        memory_dir = Path(os.path.expanduser(
            raw.get("memory_dir", "~/.claude-close-guard/memory")
        ))
        vector_db = Path(os.path.expanduser(
            raw.get("vector_db", "~/.claude-close-guard/vectors.sqlite")
        ))
        memory_dir.mkdir(parents=True, exist_ok=True)
        vector_db.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            memory_dir=memory_dir,
            vector_db=vector_db,
            embedding_model=raw.get("embedding_model", "BAAI/bge-base-zh-v1.5"),
            embedding_device=raw.get("embedding_device", "cpu"),
            summarizer_model=raw.get("summarizer_model", "claude-haiku-4-5-20251001"),
            summarizer_max_tokens=int(raw.get("summarizer_max_tokens", 2000)),
            target_window_classes=raw.get(
                "target_window_classes",
                ["CASCADIA_HOSTING_WINDOW_CLASS", "ConsoleWindowClass"],
            ),
            mcp_top_k=int(raw.get("mcp_top_k", 5)),
            mcp_hybrid_alpha=float(raw.get("mcp_hybrid_alpha", 0.5)),
            min_turns_to_prompt=int(raw.get("min_turns_to_prompt", 3)),
            ui_window_size=raw.get("ui_window_size", "720x540"),
        )
