"""Manual end-to-end dry-run.

What this exercises (no Anthropic API call, no embedder):
  1. transcript discovery & turn parsing on this user's real ~/.claude/projects
  2. enqueue → master/worker lockfile dance (single-process: master path only)
  3. tkinter aggregate dialog (you SEE the popup)
  4. memory_store.write_entry + update_index on a temp memory dir

What it does NOT exercise:
  - real Anthropic summarization (replaced with a canned Summary)
  - embedder / sqlite-vec reindex (reindex is in a try/except, will warn)

Usage:
  python scripts/dry_run.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make sure we import the package from the working tree, not site-packages.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from claude_close_guard import close_handler, transcript
from claude_close_guard.summarizer import MemoryCandidate, Summary


def fake_summary_for_panel(panel):
    """Replace the real summarizer call with a canned response."""
    # Look at what transcript was found (just to prove the wiring works).
    cwd = None  # AHK doesn't pass it; we scan globally
    path, turns = transcript.load_turns(cwd)
    headline = f"DRY-RUN: found {len(turns)} turns in {path.name if path else 'nothing'}"
    bullets = [
        "this is a fake bullet for testing the UI layout",
        "another bullet to show wrap behavior — " + "x" * 80,
        f"last user turn preview: {(turns[-1].text[:120] if turns else '(none)')!r}",
    ]
    candidates = [
        MemoryCandidate(
            title="dryrun-feedback",
            type="feedback",
            description="Sample feedback memory — should appear with [feedback] tag",
            body="This is a dry-run candidate. **Why:** to test the UI. "
                 "**How to apply:** never, it's just for visual inspection.",
            suggested_filename="feedback_dryrun.md",
        ),
        MemoryCandidate(
            title="dryrun-project",
            type="project",
            description="Sample project memory",
            body="A project-typed candidate.",
            suggested_filename="project_dryrun.md",
        ),
    ]
    return Summary(headline=headline, bullets=bullets, candidates=candidates)


def main() -> int:
    # Redirect memory_dir + state to a temp location so we don't pollute the
    # user's real config.
    tmp = Path(tempfile.mkdtemp(prefix="ccg-dryrun-"))
    print(f"[dry-run] temp config root: {tmp}")
    memory_dir = tmp / "memory"
    vector_db = tmp / "vectors.sqlite"
    memory_dir.mkdir(parents=True)

    # Override module-level paths.
    close_handler.STATE_DIR = tmp / "state"
    close_handler.QUEUE_DIR = close_handler.STATE_DIR / "queue"
    close_handler.DONE_DIR = close_handler.STATE_DIR / "done"
    close_handler.LOCK_FILE = close_handler.STATE_DIR / "master.lock"
    close_handler.LOG_FILE = tmp / "close-guard.log"

    # Monkey-patch _summarize_for_job so we don't hit the API.
    close_handler._summarize_for_job = lambda job, cfg: fake_summary_for_panel(None)

    # Build a Config that points at the temp dirs.
    from claude_close_guard.config import Config
    cfg = Config(
        memory_dir=memory_dir,
        vector_db=vector_db,
        embedding_model="BAAI/bge-base-zh-v1.5",
        embedding_device="cpu",
        summarizer_model="claude-haiku-4-5-20251001",
        summarizer_max_tokens=2000,
        target_window_classes=[],
        mcp_top_k=5,
        mcp_hybrid_alpha=0.5,
        min_turns_to_prompt=0,  # don't skip
        ui_window_size="780x560",
    )
    close_handler.Config.load = staticmethod(lambda path=None: cfg)

    # Simulate two terminal windows closing simultaneously.
    print("[dry-run] enqueuing two fake jobs (PIDs 11111 and 22222)")
    close_handler._enqueue(11111, "0x1111", None)
    close_handler._enqueue(22222, "0x2222", None)

    print("[dry-run] running close_handler.main(--pid 11111) — this is the master")
    print("[dry-run] tkinter window should appear with TWO tabs.")
    print("[dry-run] Click 'Confirm close + save selected' to write memories.")
    print()

    rc = close_handler.main(["--pid", "11111", "--hwnd", "0x1111"])

    print()
    print(f"[dry-run] master exited with code {rc}")
    print(f"[dry-run] memory dir contents:")
    for p in sorted(memory_dir.iterdir()):
        print(f"    {p.name}  ({p.stat().st_size} bytes)")
    idx = memory_dir / "INDEX.md"
    if idx.exists():
        print()
        print("[dry-run] INDEX.md:")
        print(idx.read_text(encoding="utf-8"))

    print(f"[dry-run] log file: {close_handler.LOG_FILE}")
    if close_handler.LOG_FILE.exists():
        print(close_handler.LOG_FILE.read_text(encoding="utf-8"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
