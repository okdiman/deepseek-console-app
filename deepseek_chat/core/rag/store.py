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
from pathlib import Path
from typing import Any, Dict, List, Optional

from .chunkers import Chunk

_DEFAULT_DB = str(
    Path(__file__).parent.parent.parent.parent
    / "experiments" / "rag_compare" / "data" / "doc_index.db"
)


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
    """Insert or replace a chunk with its embedding vector."""
    conn = _connect(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO doc_chunks
           (chunk_id, source, title, section, strategy, chunk_index,
            text, embedding, indexed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            chunk.chunk_id,
            chunk.source,
            chunk.title,
            chunk.section,
            chunk.strategy,
            chunk.index,
            chunk.text,
            json.dumps(embedding),
            _now_iso(),
        ),
    )
    conn.commit()
    conn.close()


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
    return deleted


# ── Search ────────────────────────────────────────────────────────────────

def search_by_embedding(
    query_vec: List[float],
    top_k: int = 5,
    strategy: Optional[str] = None,
    db_path: str = _DEFAULT_DB,
) -> List[Dict[str, Any]]:
    """Return top-k chunks ranked by cosine similarity to query_vec."""
    rows = get_all_chunks(strategy=strategy, db_path=db_path)
    scored = []
    for row in rows:
        raw = row.get("embedding")
        if not raw:
            continue
        vec = json.loads(raw)
        score = _cosine_sim(query_vec, vec)
        scored.append({**row, "score": score})
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
