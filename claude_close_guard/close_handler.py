"""Main entry point invoked by the AHK script when a target window is being closed.

Protocol with AHK
=================

AHK calls (synchronously, blocking the close):
    ccg-close --pid <PID> --hwnd <HWND> [--cwd <CWD>]

Exit codes:
    0  → AHK should release the close (let the window die)
    1  → AHK should abort the close (window stays open)
    2  → unexpected error; AHK falls back to releasing (don't trap user)

Master/worker dance (so multiple simultaneous closes share one popup):

1. Every invocation appends a JSON job to <state_dir>/queue/<pid>.json.
2. Every invocation tries to acquire <state_dir>/master.lock (portalocker).
3. The acquirer becomes MASTER:
     - sleeps DEBOUNCE_MS to collect any other windows closing in the same gust
     - reads all queue/*.json
     - kicks off background summaries (one per session)
     - shows the aggregate UI
     - on confirm: writes selected memories
     - writes <state_dir>/done/<pid>.txt with "0" or "1" per job
     - releases the lock
4. Non-acquirers become WORKERS:
     - poll <state_dir>/done/<own-pid>.txt up to TIMEOUT_S
     - exit with the integer in that file (or 0 on timeout — never trap the user)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import portalocker

from .config import Config
from .summarizer import summarize
from .transcript import load_turns, render_for_summary, Turn
from .ui import SessionPanel, run_summarizer_threads, show_aggregate_dialog
from .memory_store import MemoryStore, candidate_to_entry

STATE_DIR = Path.home() / ".claude-close-guard" / "state"
QUEUE_DIR = STATE_DIR / "queue"
DONE_DIR = STATE_DIR / "done"
LOCK_FILE = STATE_DIR / "master.lock"
LOG_FILE = Path.home() / ".claude-close-guard" / "close-guard.log"

DEBOUNCE_MS = 800
WORKER_TIMEOUT_S = 60.0
WORKER_POLL_INTERVAL_S = 0.2

EXIT_RELEASE = 0
EXIT_ABORT = 1
EXIT_ERROR = 2


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{os.getpid()}] {msg}\n")


@dataclass
class Job:
    pid: int
    hwnd: str
    cwd: str | None
    timestamp: float


def _ensure_dirs() -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    DONE_DIR.mkdir(parents=True, exist_ok=True)


def _enqueue(pid: int, hwnd: str, cwd: str | None) -> Path:
    _ensure_dirs()
    path = QUEUE_DIR / f"{pid}.json"
    data = {"pid": pid, "hwnd": hwnd, "cwd": cwd, "timestamp": time.time()}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _drain_queue() -> list[Job]:
    jobs: list[Job] = []
    if not QUEUE_DIR.exists():
        return jobs
    for p in sorted(QUEUE_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            jobs.append(Job(
                pid=int(data["pid"]),
                hwnd=str(data.get("hwnd", "")),
                cwd=data.get("cwd"),
                timestamp=float(data.get("timestamp", 0)),
            ))
        except (OSError, ValueError, KeyError):
            continue
        finally:
            try:
                p.unlink()
            except OSError:
                pass
    return jobs


def _write_done(pid: int, exit_code: int) -> None:
    _ensure_dirs()
    path = DONE_DIR / f"{pid}.txt"
    path.write_text(str(exit_code), encoding="utf-8")


def _read_done(pid: int) -> int | None:
    path = DONE_DIR / f"{pid}.txt"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


def _consume_done(pid: int) -> None:
    path = DONE_DIR / f"{pid}.txt"
    try:
        path.unlink()
    except OSError:
        pass


def _try_acquire_master():
    """Try to atomically become the master. Returns an open file handle on success
    (caller must keep it alive and close it to release), or None if another
    process already holds the lock."""
    _ensure_dirs()
    fh = open(LOCK_FILE, "w")
    try:
        portalocker.lock(fh, portalocker.LOCK_EX | portalocker.LOCK_NB)
        return fh
    except portalocker.LockException:
        fh.close()
        return None


def _summarize_for_job(job: Job, cfg: Config):
    cwd = Path(job.cwd) if job.cwd else None
    path, turns = load_turns(cwd)
    if path is None or len(turns) < cfg.min_turns_to_prompt:
        return _trivial_summary(turns)
    text = render_for_summary(turns)
    return summarize(
        text,
        model=cfg.summarizer_model,
        max_tokens=cfg.summarizer_max_tokens,
    )


def _trivial_summary(turns: list[Turn]):
    """Make a no-op Summary for sessions too short to bother summarizing."""
    from .summarizer import Summary
    if not turns:
        return Summary(headline="(no transcript found)", bullets=[], candidates=[])
    return Summary(
        headline=f"Short session ({len(turns)} turns) — no memory candidates",
        bullets=[t.text[:140] for t in turns[-3:]],
        candidates=[],
    )


def _persist_selected(selected_by_pid, cfg: Config) -> int:
    """Write chosen candidates to the memory store. Returns count written."""
    if not any(selected_by_pid.values()):
        return 0
    store = MemoryStore(cfg.memory_dir, cfg.vector_db)
    written = 0
    for pid, candidates in selected_by_pid.items():
        for c in candidates:
            store.write_entry(candidate_to_entry(c))
            written += 1
    if written:
        store.update_index()
        # Best-effort vector reindex; failures shouldn't block the close.
        try:
            from .embedder import Embedder
            embedder = Embedder(cfg.embedding_model, cfg.embedding_device)
            store.reindex(embedder)
        except Exception as exc:
            _log(f"reindex failed: {exc!r}")
    return written


def _run_master(my_pid: int, cfg: Config) -> int:
    _log(f"master: debouncing {DEBOUNCE_MS}ms")
    time.sleep(DEBOUNCE_MS / 1000)
    jobs = _drain_queue()
    if not jobs:
        _log("master: queue empty after debounce, releasing self")
        return EXIT_RELEASE
    _log(f"master: collected {len(jobs)} job(s): {[j.pid for j in jobs]}")

    panels = [
        SessionPanel(label=f"PID {j.pid}" + (f" — {Path(j.cwd).name}" if j.cwd else ""), pid=j.pid)
        for j in jobs
    ]
    job_by_pid = {j.pid: j for j in jobs}

    def summarize_panel(panel: SessionPanel):
        return _summarize_for_job(job_by_pid[panel.pid], cfg)

    run_summarizer_threads(panels, summarize_panel)

    post_close = os.environ.get("CCG_POST_CLOSE") == "1"
    result = show_aggregate_dialog(panels, window_size=cfg.ui_window_size, post_close=post_close)
    _log(f"master: ui result confirmed={result.confirmed} "
         f"selected_counts={ {k: len(v) for k, v in result.selected.items()} }")

    if result.confirmed:
        try:
            n = _persist_selected(result.selected, cfg)
            _log(f"master: wrote {n} memories")
        except Exception as exc:
            _log(f"master: persist failed: {exc!r}")

    exit_code = EXIT_RELEASE if result.confirmed else EXIT_ABORT
    for j in jobs:
        _write_done(j.pid, exit_code)
    _log(f"master: wrote done files with exit={exit_code}")
    return exit_code


def _run_worker(my_pid: int) -> int:
    _log("worker: waiting for master to signal")
    deadline = time.time() + WORKER_TIMEOUT_S
    while time.time() < deadline:
        code = _read_done(my_pid)
        if code is not None:
            _consume_done(my_pid)
            _log(f"worker: got exit={code}")
            return code
        time.sleep(WORKER_POLL_INTERVAL_S)
    _log("worker: timeout, releasing close")
    return EXIT_RELEASE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ccg-close")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--hwnd", type=str, default="")
    parser.add_argument("--cwd", type=str, default=None)
    parser.add_argument(
        "--post-close",
        action="store_true",
        help="Window is already gone; UI shows save-only flow (no Cancel-close).",
    )
    args = parser.parse_args(argv)
    os.environ["CCG_POST_CLOSE"] = "1" if args.post_close else "0"

    try:
        cfg = Config.load()
        _enqueue(args.pid, args.hwnd, args.cwd)
        _log(f"enqueued pid={args.pid} hwnd={args.hwnd} cwd={args.cwd}")

        lock_fh = _try_acquire_master()
        if lock_fh is not None:
            try:
                # First check if our own pid is already done (a previous master may
                # have processed our job during a race window).
                code = _read_done(args.pid)
                if code is not None:
                    _consume_done(args.pid)
                    return code
                return _run_master(args.pid, cfg)
            finally:
                try:
                    portalocker.unlock(lock_fh)
                finally:
                    lock_fh.close()
        else:
            return _run_worker(args.pid)
    except SystemExit:
        raise
    except Exception as exc:
        _log(f"fatal: {exc!r}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
