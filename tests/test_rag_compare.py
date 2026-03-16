"""Tests for the RAG strategy comparison module."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from deepseek_chat.core.rag.config import RagConfig
from deepseek_chat.core.rag.chunkers import Chunk
from deepseek_chat.core.rag.store import init_db, upsert_chunk
from experiments.rag_compare.compare import (
    ComparisonReport,
    compare_strategies,
    print_report,
    save_report,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def config(tmp_path) -> RagConfig:
    return RagConfig(
        fixed_chunk_size=100,
        fixed_chunk_overlap=10,
        ollama_url="http://localhost:11434",
        ollama_model="nomic-embed-text",
        embedding_dim=4,
        db_path=str(tmp_path / "test.db"),
    )


def _make_chunk(chunk_id, strategy, source="doc.md", section=""):
    return Chunk(
        chunk_id=chunk_id,
        source=source,
        title="Test",
        section=section,
        strategy=strategy,
        index=0,
        text=f"text for {chunk_id}",
    )


def _seed_index(config: RagConfig):
    """Populate index with some fixed and structure chunks."""
    init_db(config.db_path)
    vec = [1.0, 0.0, 0.0, 0.0]
    for i in range(5):
        upsert_chunk(_make_chunk(f"f{i}", "fixed", section=""), vec, config.db_path)
    for i in range(5):
        upsert_chunk(
            _make_chunk(f"s{i}", "structure", section=f"Section {i}"),
            vec,
            config.db_path,
        )


def _fake_embed(texts):
    return [[1.0, 0.0, 0.0, 0.0]] * len(texts)


# ── compare_strategies ────────────────────────────────────────────────────

class TestCompareStrategies:
    @patch("experiments.rag_compare.compare.OllamaEmbeddingClient")
    def test_returns_comparison_report(self, mock_cls, config):
        mock_cls.return_value.embed.side_effect = _fake_embed
        _seed_index(config)
        report = compare_strategies(config=config, probe_queries=["test query"])
        assert isinstance(report, ComparisonReport)

    @patch("experiments.rag_compare.compare.OllamaEmbeddingClient")
    def test_fixed_stats_zero_section_pct(self, mock_cls, config):
        mock_cls.return_value.embed.side_effect = _fake_embed
        _seed_index(config)
        report = compare_strategies(config=config, probe_queries=["test"])
        assert report.fixed_stats.pct_with_section == 0.0

    @patch("experiments.rag_compare.compare.OllamaEmbeddingClient")
    def test_structure_stats_nonzero_section_pct(self, mock_cls, config):
        mock_cls.return_value.embed.side_effect = _fake_embed
        _seed_index(config)
        report = compare_strategies(config=config, probe_queries=["test"])
        assert report.structure_stats.pct_with_section > 0

    @patch("experiments.rag_compare.compare.OllamaEmbeddingClient")
    def test_query_results_length_matches_probes(self, mock_cls, config):
        mock_cls.return_value.embed.side_effect = _fake_embed
        _seed_index(config)
        probes = ["q1", "q2", "q3"]
        report = compare_strategies(config=config, probe_queries=probes)
        assert len(report.query_results) == len(probes)

    @patch("experiments.rag_compare.compare.OllamaEmbeddingClient")
    def test_agreement_rate_between_0_and_1(self, mock_cls, config):
        mock_cls.return_value.embed.side_effect = _fake_embed
        _seed_index(config)
        report = compare_strategies(config=config, probe_queries=["test"])
        assert 0.0 <= report.agreement_rate <= 1.0

    @patch("experiments.rag_compare.compare.OllamaEmbeddingClient")
    def test_fixed_stats_total_matches_db(self, mock_cls, config):
        mock_cls.return_value.embed.side_effect = _fake_embed
        _seed_index(config)
        report = compare_strategies(config=config, probe_queries=["test"])
        assert report.fixed_stats.total_chunks == 5
        assert report.structure_stats.total_chunks == 5


# ── save_report ───────────────────────────────────────────────────────────

class TestSaveReport:
    @patch("experiments.rag_compare.compare.OllamaEmbeddingClient")
    def test_saves_valid_json(self, mock_cls, config, tmp_path):
        mock_cls.return_value.embed.side_effect = _fake_embed
        _seed_index(config)
        report = compare_strategies(config=config, probe_queries=["test"])
        path = str(tmp_path / "report.json")
        saved = save_report(report, path=path)
        assert saved == path
        data = json.loads(Path(path).read_text())
        assert "fixed_stats" in data
        assert "structure_stats" in data
        assert "query_results" in data
        assert "agreement_rate" in data

    @patch("experiments.rag_compare.compare.OllamaEmbeddingClient")
    def test_report_json_contains_strategy_names(self, mock_cls, config, tmp_path):
        mock_cls.return_value.embed.side_effect = _fake_embed
        _seed_index(config)
        report = compare_strategies(config=config, probe_queries=["test"])
        path = str(tmp_path / "report.json")
        save_report(report, path=path)
        data = json.loads(Path(path).read_text())
        assert data["fixed_stats"]["strategy"] == "fixed"
        assert data["structure_stats"]["strategy"] == "structure"


# ── print_report ──────────────────────────────────────────────────────────

class TestPrintReport:
    @patch("experiments.rag_compare.compare.OllamaEmbeddingClient")
    def test_print_does_not_raise(self, mock_cls, config, capsys):
        mock_cls.return_value.embed.side_effect = _fake_embed
        _seed_index(config)
        report = compare_strategies(config=config, probe_queries=["test query"])
        print_report(report)
        out = capsys.readouterr().out
        assert "CHUNKING STRATEGY COMPARISON" in out
        assert "FIXED-SIZE" in out
        assert "STRUCTURE-BASED" in out
