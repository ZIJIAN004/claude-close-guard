"""Memory store: markdown is source-of-truth, sqlite-vec is the search index.

Layout:
    memory_dir/
        INDEX.md                         # human-readable index
        feedback_close_guard.md          # one .md per memory entry
        project_xxx.md
        ...

Every .md file has YAML front-matter:
    ---
    name: feedback close guard
    description: one-line hook
    type: feedback
    ---
    <body>
"""

from __future__ import annotations

import re
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

INDEX_FILENAME = "INDEX.md"


@dataclass
class MemoryEntry:
    filename: str
    name: str
    description: str
    type: str
    body: str

    @property
    def stem(self) -> str:
        return Path(self.filename).stem

    @property
    def searchable_text(self) -> str:
        return f"{self.name}\n{self.description}\n{self.body}"


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_md(path: Path) -> MemoryEntry | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    body = m.group(2).strip()
    return MemoryEntry(
        filename=path.name,
        name=str(meta.get("name", path.stem)),
        description=str(meta.get("description", "")),
        type=str(meta.get("type", "project")),
        body=body,
    )


def serialize_md(entry: MemoryEntry) -> str:
    front = yaml.safe_dump(
        {"name": entry.name, "description": entry.description, "type": entry.type},
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    return f"---\n{front}\n---\n\n{entry.body}\n"


def _safe_filename(stem: str) -> str:
    s = re.sub(r"[^\w\-.]", "_", stem)
    if not s.endswith(".md"):
        s += ".md"
    return s


class MemoryStore:
    def __init__(self, memory_dir: Path, vector_db: Path) -> None:
        self.memory_dir = memory_dir
        self.vector_db = vector_db
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.vector_db.parent.mkdir(parents=True, exist_ok=True)

    # ---------- markdown side ----------

    def list_entries(self) -> list[MemoryEntry]:
        out: list[MemoryEntry] = []
        for p in sorted(self.memory_dir.glob("*.md")):
            if p.name == INDEX_FILENAME:
                continue
            entry = parse_md(p)
            if entry:
                out.append(entry)
        return out

    def write_entry(self, entry: MemoryEntry, overwrite: bool = False) -> Path:
        filename = _safe_filename(entry.filename)
        path = self.memory_dir / filename
        if path.exists() and not overwrite:
            stem = path.stem
            i = 2
            while (self.memory_dir / f"{stem}_{i}.md").exists():
                i += 1
            path = self.memory_dir / f"{stem}_{i}.md"
        path.write_text(serialize_md(entry), encoding="utf-8")
        return path

    def update_index(self) -> Path:
        entries = self.list_entries()
        groups: dict[str, list[MemoryEntry]] = {}
        for e in entries:
            groups.setdefault(e.type.capitalize(), []).append(e)

        lines = ["# Memory Index", ""]
        for section in ("User", "Feedback", "Project", "Reference"):
            items = groups.pop(section, [])
            if not items:
                continue
            lines.append(f"## {section}")
            for e in items:
                lines.append(f"- [{e.name}]({e.filename}) — {e.description}")
            lines.append("")
        for section, items in groups.items():
            lines.append(f"## {section}")
            for e in items:
                lines.append(f"- [{e.name}]({e.filename}) — {e.description}")
            lines.append("")
        path = self.memory_dir / INDEX_FILENAME
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

    # ---------- vector side ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.vector_db))
        conn.enable_load_extension(True)
        try:
            import sqlite_vec
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection, dim: int) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS entries ("
            "  id INTEGER PRIMARY KEY,"
            "  filename TEXT UNIQUE,"
            "  name TEXT,"
            "  description TEXT,"
            "  type TEXT,"
            "  body TEXT,"
            "  mtime REAL"
            ")"
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec USING vec0("
            f"  embedding float[{dim}]"
            f")"
        )
        conn.commit()

    @staticmethod
    def _vec_to_blob(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    def reindex(self, embedder) -> int:
        """Rebuild the vector index from the markdown files. Returns count indexed."""
        entries = self.list_entries()
        if not entries:
            # still ensure schema so subsequent searches don't error
            conn = self._connect()
            try:
                self._ensure_schema(conn, embedder.dim)
            finally:
                conn.close()
            return 0

        texts = [e.searchable_text for e in entries]
        embeddings = embedder.encode(texts)
        dim = len(embeddings[0])

        conn = self._connect()
        try:
            self._ensure_schema(conn, dim)
            conn.execute("DELETE FROM entries")
            conn.execute("DELETE FROM vec")
            for entry, emb in zip(entries, embeddings):
                cur = conn.execute(
                    "INSERT INTO entries(filename, name, description, type, body, mtime) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        entry.filename,
                        entry.name,
                        entry.description,
                        entry.type,
                        entry.body,
                        (self.memory_dir / entry.filename).stat().st_mtime,
                    ),
                )
                conn.execute(
                    "INSERT INTO vec(rowid, embedding) VALUES (?, ?)",
                    (cur.lastrowid, self._vec_to_blob(emb)),
                )
            conn.commit()
        finally:
            conn.close()
        return len(entries)

    def search(
        self,
        query: str,
        embedder,
        top_k: int = 5,
        alpha: float = 0.5,
    ) -> list[tuple[MemoryEntry, float]]:
        """Hybrid search: BM25 (rank-bm25) + vector cosine, blended by alpha.

        alpha=0 → BM25 only, alpha=1 → vector only.
        """
        entries = self.list_entries()
        if not entries:
            return []

        # BM25 over filename+name+description+body
        try:
            from rank_bm25 import BM25Okapi
            corpus = [_tokenize(e.searchable_text) for e in entries]
            bm25 = BM25Okapi(corpus)
            bm25_scores = bm25.get_scores(_tokenize(query))
            if bm25_scores.max() > 0:
                bm25_scores = bm25_scores / bm25_scores.max()
            else:
                bm25_scores = bm25_scores * 0.0
        except Exception:
            bm25_scores = [0.0] * len(entries)

        # Vector
        try:
            qvec = embedder.encode_one(query)
            conn = self._connect()
            try:
                self._ensure_schema(conn, len(qvec))
                rows = conn.execute(
                    "SELECT entries.filename, vec.distance "
                    "FROM vec JOIN entries ON entries.id = vec.rowid "
                    "WHERE embedding MATCH ? AND k = ? "
                    "ORDER BY distance",
                    (self._vec_to_blob(qvec), len(entries)),
                ).fetchall()
            finally:
                conn.close()
            # vec0 returns L2 distance for normalized vectors → convert to similarity in [0,1]
            dist_map = {fn: dist for fn, dist in rows}
            vec_scores = []
            for e in entries:
                d = dist_map.get(e.filename, 2.0)
                # for unit vectors, cos_sim = 1 - d^2 / 2
                vec_scores.append(max(0.0, 1.0 - d * d / 2.0))
        except Exception:
            vec_scores = [0.0] * len(entries)

        blended = [
            (e, (1 - alpha) * b + alpha * v)
            for e, b, v in zip(entries, bm25_scores, vec_scores)
        ]
        blended.sort(key=lambda x: x[1], reverse=True)
        return blended[:top_k]


def _tokenize(text: str) -> list[str]:
    """Cheap multilingual tokenization: lowercase, split on non-word, also keep CJK chars individually."""
    text = text.lower()
    # Split CJK runs into individual chars (so BM25 can hit on Chinese)
    parts: list[str] = []
    for token in re.findall(r"[\w]+", text, flags=re.UNICODE):
        if any("一" <= ch <= "鿿" for ch in token):
            parts.extend(list(token))
        else:
            parts.append(token)
    return parts


def candidate_to_entry(c) -> MemoryEntry:
    """Convert summarizer.MemoryCandidate to MemoryEntry."""
    return MemoryEntry(
        filename=c.suggested_filename,
        name=c.title,
        description=c.description,
        type=c.type,
        body=c.body,
    )
