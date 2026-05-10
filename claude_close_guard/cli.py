"""`ccg` CLI — manage the memory store from the command line."""

from __future__ import annotations

import json
import sys

import click

from .config import Config
from .memory_store import MemoryStore


@click.group()
def main() -> None:
    """claude-close-guard utility CLI."""


@main.command("list")
@click.option("--type", "type_filter", default=None,
              type=click.Choice(["user", "feedback", "project", "reference"]))
def cmd_list(type_filter: str | None) -> None:
    """List all memory entries."""
    cfg = Config.load()
    store = MemoryStore(cfg.memory_dir, cfg.vector_db)
    entries = store.list_entries()
    if type_filter:
        entries = [e for e in entries if e.type == type_filter]
    if not entries:
        click.echo("(no memories yet)")
        return
    for e in entries:
        click.echo(f"[{e.type:8s}] {e.filename}")
        click.echo(f"           {e.description}")


@main.command("search")
@click.argument("query")
@click.option("--top-k", default=5, type=int)
@click.option("--json", "as_json", is_flag=True)
def cmd_search(query: str, top_k: int, as_json: bool) -> None:
    """Search the memory store (hybrid BM25 + vector)."""
    cfg = Config.load()
    store = MemoryStore(cfg.memory_dir, cfg.vector_db)
    from .embedder import Embedder
    embedder = Embedder(cfg.embedding_model, cfg.embedding_device)
    results = store.search(query, embedder, top_k=top_k, alpha=cfg.mcp_hybrid_alpha)
    if as_json:
        click.echo(json.dumps([
            {"filename": e.filename, "name": e.name, "type": e.type,
             "description": e.description, "body": e.body, "score": round(s, 4)}
            for e, s in results
        ], ensure_ascii=False, indent=2))
        return
    for e, score in results:
        click.echo(f"{score:.3f}  [{e.type}] {e.filename}")
        click.echo(f"        {e.description}")


@main.command("reindex")
def cmd_reindex() -> None:
    """Rebuild the vector index from markdown files."""
    cfg = Config.load()
    store = MemoryStore(cfg.memory_dir, cfg.vector_db)
    from .embedder import Embedder
    embedder = Embedder(cfg.embedding_model, cfg.embedding_device)
    n = store.reindex(embedder)
    store.update_index()
    click.echo(f"reindexed {n} entries; INDEX.md regenerated")


@main.command("show")
@click.argument("filename")
def cmd_show(filename: str) -> None:
    """Print one memory entry's full content."""
    cfg = Config.load()
    path = cfg.memory_dir / filename
    if not path.exists():
        click.echo(f"not found: {path}", err=True)
        sys.exit(1)
    click.echo(path.read_text(encoding="utf-8"))


@main.command("path")
def cmd_path() -> None:
    """Print the memory directory."""
    cfg = Config.load()
    click.echo(str(cfg.memory_dir))


if __name__ == "__main__":
    main()
