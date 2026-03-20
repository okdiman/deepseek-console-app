"""
SQLite persistence for the RAG index.

Schema:
  doc_chunks(chunk_id, source, title, section, strategy,
             chunk_index, text, embedding, indexed_at)

Search uses cosine similarity computed in Python — sufficient for <1000 chunks.
"""

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .chunkers import Chunk
from .config import _DEFAULT_DB

# ── Embedding cache ────────────────────────────────────────────────────────
# key: (db_path, strategy_or_None) → rows with pre-parsed "_vec" field
# Invalidated on any write (upsert / clear). Survives across requests.
_embed_cache: Dict[Tuple[str, Optional[str]], List[Dict]] = {}


def _invalidate_cache(db_path: str) -> None:
    for key in [k for k in _embed_cache if k[0] == db_path]:
        del _embed_cache[key]


# ── Helpers ───────────────────────────────────────────────────────────────

def _ensure_dir(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)


def _connect(db_path: str) -> sqlite3.Connection:
    _ensure_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    denom = na * nb
    return dot / denom if denom > 1e-10 else 0.0


# ── Init ──────────────────────────────────────────────────────────────────

def init_db(db_path: str = _DEFAULT_DB) -> None:
    """Create tables and indexes if they don't exist."""
    conn = _connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS doc_chunks (
            chunk_id    TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            title       TEXT NOT NULL,
            section     TEXT NOT NULL DEFAULT '',
            strategy    TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text        TEXT NOT NULL,
            embedding   TEXT,
            indexed_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_strategy ON doc_chunks(strategy);
        CREATE INDEX IF NOT EXISTS idx_source   ON doc_chunks(source);
    """)
    conn.commit()
    conn.close()


# ── CRUD ──────────────────────────────────────────────────────────────────

def upsert_chunk(
    chunk: Chunk,
    embedding: List[float],
    db_path: str = _DEFAULT_DB,
) -> None:
    """Insert or replace a single chunk. Prefer upsert_chunks_bulk for batch indexing."""
    upsert_chunks_bulk([chunk], [embedding], db_path)


def upsert_chunks_bulk(
    chunks: List[Chunk],
    embeddings: List[List[float]],
    db_path: str = _DEFAULT_DB,
) -> None:
    """Insert or replace multiple chunks in a single transaction."""
    if not chunks:
        return
    now = _now_iso()
    conn = _connect(db_path)
    conn.executemany(
        """INSERT OR REPLACE INTO doc_chunks
           (chunk_id, source, title, section, strategy, chunk_index,
            text, embedding, indexed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (c.chunk_id, c.source, c.title, c.section, c.strategy, c.index,
             c.text, json.dumps(vec), now)
            for c, vec in zip(chunks, embeddings)
        ],
    )
    conn.commit()
    conn.close()
    _invalidate_cache(db_path)


def get_all_chunks(
    strategy: Optional[str] = None,
    db_path: str = _DEFAULT_DB,
) -> List[Dict[str, Any]]:
    """Return all chunks, optionally filtered by strategy."""
    conn = _connect(db_path)
    if strategy:
        rows = conn.execute(
            "SELECT * FROM doc_chunks WHERE strategy = ? ORDER BY chunk_index",
            (strategy,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM doc_chunks ORDER BY strategy, chunk_index"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_strategy(strategy: str, db_path: str = _DEFAULT_DB) -> int:
    """Delete all chunks for a strategy. Returns number of deleted rows."""
    conn = _connect(db_path)
    cur = conn.execute(
        "DELETE FROM doc_chunks WHERE strategy = ?", (strategy,)
    )
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    _invalidate_cache(db_path)
    return deleted


# ── Search ────────────────────────────────────────────────────────────────

def search_by_embedding(
    query_vec: List[float],
    top_k: int = 5,
    strategy: Optional[str] = None,
    db_path: str = _DEFAULT_DB,
) -> List[Dict[str, Any]]:
    """Return top-k chunks ranked by cosine similarity to query_vec.

    Embeddings are parsed from JSON once and cached in memory.
    Cache is invalidated whenever chunks are written or cleared.
    """
    cache_key = (db_path, strategy)
    if cache_key not in _embed_cache:
        rows = get_all_chunks(strategy=strategy, db_path=db_path)
        parsed = []
        for row in rows:
            raw = row.get("embedding")
            if not raw:
                continue
            d = dict(row)
            d["_vec"] = json.loads(raw)
            parsed.append(d)
        _embed_cache[cache_key] = parsed

    scored = []
    for row in _embed_cache[cache_key]:
        score = _cosine_sim(query_vec, row["_vec"])
        scored.append({k: v for k, v in row.items() if k != "_vec"} | {"score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# ── Stats ─────────────────────────────────────────────────────────────────

def get_stats(db_path: str = _DEFAULT_DB) -> Dict[str, Any]:
    """Return chunk counts per strategy and total."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT strategy, COUNT(*) as cnt FROM doc_chunks GROUP BY strategy"
    ).fetchall()
    last = conn.execute(
        "SELECT MAX(indexed_at) as last FROM doc_chunks"
    ).fetchone()
    conn.close()

    per_strategy = {r["strategy"]: r["cnt"] for r in rows}
    return {
        "per_strategy": per_strategy,
        "total": sum(per_strategy.values()),
        "last_indexed_at": last["last"] if last else None,
    }
