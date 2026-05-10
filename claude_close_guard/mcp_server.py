"""MCP server exposing search_memory + list_memories tools.

Register in Claude Code via:
    claude mcp add ccg-memory -- ccg-mcp
or by hand-editing ~/.claude.json:
    "ccg-memory": { "command": "ccg-mcp" }
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import Config
from .memory_store import MemoryStore


def _build_server() -> Server:
    cfg = Config.load()
    store = MemoryStore(cfg.memory_dir, cfg.vector_db)
    embedder_holder: dict = {}

    def get_embedder():
        if "e" not in embedder_holder:
            from .embedder import Embedder
            embedder_holder["e"] = Embedder(cfg.embedding_model, cfg.embedding_device)
        return embedder_holder["e"]

    server: Server = Server("claude-close-guard")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search_memory",
                description=(
                    "Search the user's curated memory store (markdown + vector index) "
                    "for entries relevant to the query. Returns top-k entries with "
                    "their full body. Use this whenever the user references past "
                    "decisions, preferences, or project context that may be stored."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "top_k": {
                            "type": "integer",
                            "description": f"Max results (default {cfg.mcp_top_k})",
                            "default": cfg.mcp_top_k,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="list_memories",
                description=(
                    "List all memory entries (filename, title, type, description). "
                    "Use this when the user asks to dump or review the entire memory."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type_filter": {
                            "type": "string",
                            "enum": ["user", "feedback", "project", "reference"],
                            "description": "Optional: only return entries of this type",
                        }
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "search_memory":
            query = arguments["query"]
            top_k = int(arguments.get("top_k", cfg.mcp_top_k))
            results = store.search(
                query, get_embedder(), top_k=top_k, alpha=cfg.mcp_hybrid_alpha
            )
            payload = [
                {
                    "filename": e.filename,
                    "name": e.name,
                    "type": e.type,
                    "description": e.description,
                    "body": e.body,
                    "score": round(score, 4),
                }
                for e, score in results
            ]
            return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

        if name == "list_memories":
            type_filter = arguments.get("type_filter")
            entries = store.list_entries()
            if type_filter:
                entries = [e for e in entries if e.type == type_filter]
            payload = [
                {
                    "filename": e.filename,
                    "name": e.name,
                    "type": e.type,
                    "description": e.description,
                }
                for e in entries
            ]
            return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

        raise ValueError(f"Unknown tool: {name}")

    return server


async def _amain() -> None:
    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> int:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
