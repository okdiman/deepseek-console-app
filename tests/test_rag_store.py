"""Tests for the RAG SQLite store."""

import json
import math
import tempfile
import os
import pytest

from deepseek_chat.core.rag.chunkers import Chunk
from deepseek_chat.core.rag.store import (
    clear_strategy,
    get_all_chunks,
    get_stats,
    init_db,
    search_by_embedding,
    upsert_chunk,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_index.db")
    init_db(path)
    return path


def _make_chunk(
    chunk_id: str = "c1",
    source: str = "doc.md",
    strategy: str = "fixed",
    section: str = "",
    index: int = 0,
    text: str = "sample text",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source=source,
        title="Test Doc",
        section=section,
        strategy=strategy,
        index=index,
        text=text,
    )


def _unit_vec(dim: int = 4, i: int = 0) -> list:
    """Return a unit vector with 1.0 at position i."""
    v = [0.0] * dim
    v[i % dim] = 1.0
    return v


# ── init_db ───────────────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_table(self, tmp_path):
        import sqlite3
        path = str(tmp_path / "new.db")
        init_db(path)
        conn = sqlite3.connect(path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "doc_chunks" in tables

    def test_idempotent(self, tmp_path):
        path = str(tmp_path / "new.db")
        init_db(path)
        init_db(path)  # should not raise


# ── upsert_chunk ──────────────────────────────────────────────────────────

class TestUpsertChunk:
    def test_inserts_chunk(self, db_path):
        chunk = _make_chunk()
        upsert_chunk(chunk, _unit_vec(), db_path)
        rows = get_all_chunks(db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["chunk_id"] == "c1"

    def test_embedding_stored_as_json(self, db_path):
        import sqlite3
        vec = [0.1, 0.2, 0.3, 0.4]
        upsert_chunk(_make_chunk(), vec, db_path)
        conn = sqlite3.connect(db_path)
        raw = conn.execute("SELECT embedding FROM doc_chunks WHERE chunk_id='c1'").fetchone()[0]
        conn.close()
        assert json.loads(raw) == pytest.approx(vec, abs=1e-6)

    def test_upsert_updates_existing(self, db_path):
        chunk = _make_chunk(text="original")
        upsert_chunk(chunk, _unit_vec(), db_path)
        updated = _make_chunk(text="updated")
        upsert_chunk(updated, _unit_vec(), db_path)
        rows = get_all_chunks(db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["text"] == "updated"

    def test_section_stored(self, db_path):
        chunk = _make_chunk(section="My Section")
        upsert_chunk(chunk, _unit_vec(), db_path)
        rows = get_all_chunks(db_path=db_path)
        assert rows[0]["section"] == "My Section"


# ── get_all_chunks ────────────────────────────────────────────────────────

class TestGetAllChunks:
    def test_returns_all_chunks(self, db_path):
        for i in range(3):
            upsert_chunk(_make_chunk(chunk_id=f"c{i}", strategy="fixed"), _unit_vec(), db_path)
        assert len(get_all_chunks(db_path=db_path)) == 3

    def test_filter_by_strategy(self, db_path):
        upsert_chunk(_make_chunk(chunk_id="f1", strategy="fixed"), _unit_vec(), db_path)
        upsert_chunk(_make_chunk(chunk_id="s1", strategy="structure"), _unit_vec(), db_path)

        fixed = get_all_chunks(strategy="fixed", db_path=db_path)
        struct = get_all_chunks(strategy="structure", db_path=db_path)

        assert len(fixed) == 1 and fixed[0]["chunk_id"] == "f1"
        assert len(struct) == 1 and struct[0]["chunk_id"] == "s1"

    def test_empty_db_returns_empty_list(self, db_path):
        assert get_all_chunks(db_path=db_path) == []


# ── clear_strategy ────────────────────────────────────────────────────────

class TestClearStrategy:
    def test_clears_only_specified_strategy(self, db_path):
        upsert_chunk(_make_chunk(chunk_id="f1", strategy="fixed"), _unit_vec(), db_path)
        upsert_chunk(_make_chunk(chunk_id="s1", strategy="structure"), _unit_vec(), db_path)

        deleted = clear_strategy("fixed", db_path)
        assert deleted == 1
        remaining = get_all_chunks(db_path=db_path)
        assert len(remaining) == 1
        assert remaining[0]["chunk_id"] == "s1"

    def test_returns_count_of_deleted(self, db_path):
        for i in range(4):
            upsert_chunk(_make_chunk(chunk_id=f"f{i}", strategy="fixed"), _unit_vec(), db_path)
        assert clear_strategy("fixed", db_path) == 4

    def test_clear_nonexistent_strategy_returns_zero(self, db_path):
        assert clear_strategy("fixed", db_path) == 0


# ── search_by_embedding ───────────────────────────────────────────────────

class TestSearchByEmbedding:
    def test_returns_top_k(self, db_path):
        for i in range(5):
            upsert_chunk(
                _make_chunk(chunk_id=f"c{i}", strategy="fixed"),
                _unit_vec(dim=5, i=i),
                db_path,
            )
        results = search_by_embedding(_unit_vec(dim=5, i=0), top_k=3, db_path=db_path)
        assert len(results) == 3

    def test_sorted_by_score_descending(self, db_path):
        for i in range(4):
            upsert_chunk(
                _make_chunk(chunk_id=f"c{i}", strategy="fixed"),
                _unit_vec(dim=4, i=i),
                db_path,
            )
        results = search_by_embedding(_unit_vec(dim=4, i=0), top_k=4, db_path=db_path)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_exact_match_scores_near_one(self, db_path):
        vec = [0.5, 0.5, 0.5, 0.5]
        norm = math.sqrt(sum(x * x for x in vec))
        vec_norm = [x / norm for x in vec]
        upsert_chunk(_make_chunk(chunk_id="exact"), vec_norm, db_path)
        results = search_by_embedding(vec_norm, top_k=1, db_path=db_path)
        assert results[0]["score"] == pytest.approx(1.0, abs=1e-5)

    def test_filter_by_strategy(self, db_path):
        upsert_chunk(_make_chunk(chunk_id="f1", strategy="fixed"), _unit_vec(), db_path)
        upsert_chunk(_make_chunk(chunk_id="s1", strategy="structure"), _unit_vec(), db_path)

        fixed_res = search_by_embedding(_unit_vec(), top_k=5, strategy="fixed", db_path=db_path)
        assert all(r["strategy"] == "fixed" for r in fixed_res)

    def test_empty_index_returns_empty(self, db_path):
        results = search_by_embedding(_unit_vec(), top_k=5, db_path=db_path)
        assert results == []


# ── get_stats ─────────────────────────────────────────────────────────────

class TestGetStats:
    def test_returns_correct_counts(self, db_path):
        for i in range(3):
            upsert_chunk(_make_chunk(chunk_id=f"f{i}", strategy="fixed"), _unit_vec(), db_path)
        for i in range(2):
            upsert_chunk(_make_chunk(chunk_id=f"s{i}", strategy="structure"), _unit_vec(), db_path)

        stats = get_stats(db_path)
        assert stats["total"] == 5
        assert stats["per_strategy"]["fixed"] == 3
        assert stats["per_strategy"]["structure"] == 2

    def test_empty_db_returns_zero_total(self, db_path):
        stats = get_stats(db_path)
        assert stats["total"] == 0

    def test_last_indexed_at_populated(self, db_path):
        upsert_chunk(_make_chunk(), _unit_vec(), db_path)
        stats = get_stats(db_path)
        assert stats["last_indexed_at"] is not None
