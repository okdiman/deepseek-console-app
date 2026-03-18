"""Tests for the RAG pipeline (embedder mocked, no Ollama needed)."""

from unittest.mock import MagicMock, patch
import pytest

from deepseek_chat.core.rag.chunkers import Chunk
from deepseek_chat.core.rag.config import RagConfig
from deepseek_chat.core.rag.pipeline import PipelineResult, run_pipeline
from deepseek_chat.core.rag.store import get_all_chunks, get_stats, init_db


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
        pre_rerank_top_k=10,
        reranker_type="threshold",
        reranker_threshold=0.30,
        query_rewrite_enabled=False,
    )


def _fake_embed(texts):
    """Return deterministic unit vectors (no Ollama call)."""
    return [[1.0, 0.0, 0.0, 0.0]] * len(texts)


SMALL_CORPUS = [
    MagicMock(path=MagicMock(name="doc1.md"), doc_type="markdown", title="Doc 1"),
    MagicMock(path=MagicMock(name="doc2.py"), doc_type="python",   title="Doc 2"),
]


def _make_corpus_text(cf):
    if "doc1" in str(cf.path.name):
        return "# Title\n\n## Section\n\nSome content here.\n"
    return "def hello():\n    return 'world'\n"


# ── run_pipeline ──────────────────────────────────────────────────────────

class TestRunPipeline:
    @patch("deepseek_chat.core.rag.pipeline.CORPUS_FILES", SMALL_CORPUS)
    @patch("deepseek_chat.core.rag.pipeline.load_corpus_text", side_effect=_make_corpus_text)
    @patch("deepseek_chat.core.rag.pipeline.OllamaEmbeddingClient")
    def test_returns_pipeline_results(self, mock_client_cls, mock_load, config):
        mock_client_cls.return_value.embed.side_effect = _fake_embed
        results = run_pipeline(strategy="fixed", config=config, verbose=False)
        assert len(results) == 1
        assert isinstance(results[0], PipelineResult)

    @patch("deepseek_chat.core.rag.pipeline.CORPUS_FILES", SMALL_CORPUS)
    @patch("deepseek_chat.core.rag.pipeline.load_corpus_text", side_effect=_make_corpus_text)
    @patch("deepseek_chat.core.rag.pipeline.OllamaEmbeddingClient")
    def test_both_strategies_runs_twice(self, mock_client_cls, mock_load, config):
        mock_client_cls.return_value.embed.side_effect = _fake_embed
        results = run_pipeline(strategy="both", config=config, verbose=False)
        assert len(results) == 2
        strategies = [r.strategy for r in results]
        assert "fixed" in strategies
        assert "structure" in strategies

    @patch("deepseek_chat.core.rag.pipeline.CORPUS_FILES", SMALL_CORPUS)
    @patch("deepseek_chat.core.rag.pipeline.load_corpus_text", side_effect=_make_corpus_text)
    @patch("deepseek_chat.core.rag.pipeline.OllamaEmbeddingClient")
    def test_chunks_stored_in_db(self, mock_client_cls, mock_load, config):
        mock_client_cls.return_value.embed.side_effect = _fake_embed
        run_pipeline(strategy="fixed", config=config, verbose=False)
        rows = get_all_chunks(strategy="fixed", db_path=config.db_path)
        assert len(rows) > 0

    @patch("deepseek_chat.core.rag.pipeline.CORPUS_FILES", SMALL_CORPUS)
    @patch("deepseek_chat.core.rag.pipeline.load_corpus_text", side_effect=_make_corpus_text)
    @patch("deepseek_chat.core.rag.pipeline.OllamaEmbeddingClient")
    def test_reindex_clears_old_chunks(self, mock_client_cls, mock_load, config):
        mock_client_cls.return_value.embed.side_effect = _fake_embed
        run_pipeline(strategy="fixed", config=config, verbose=False)
        count_first = len(get_all_chunks(strategy="fixed", db_path=config.db_path))
        run_pipeline(strategy="fixed", config=config, verbose=False)
        count_second = len(get_all_chunks(strategy="fixed", db_path=config.db_path))
        assert count_first == count_second  # no duplicates

    @patch("deepseek_chat.core.rag.pipeline.CORPUS_FILES", SMALL_CORPUS)
    @patch("deepseek_chat.core.rag.pipeline.load_corpus_text", return_value="")
    @patch("deepseek_chat.core.rag.pipeline.OllamaEmbeddingClient")
    def test_empty_files_captured_as_errors(self, mock_client_cls, mock_load, config):
        mock_client_cls.return_value.embed.side_effect = _fake_embed
        results = run_pipeline(strategy="fixed", config=config, verbose=False)
        assert len(results[0].errors) == len(SMALL_CORPUS)

    @patch("deepseek_chat.core.rag.pipeline.CORPUS_FILES", SMALL_CORPUS)
    @patch("deepseek_chat.core.rag.pipeline.load_corpus_text", side_effect=_make_corpus_text)
    @patch("deepseek_chat.core.rag.pipeline.OllamaEmbeddingClient")
    def test_result_has_correct_strategy_name(self, mock_client_cls, mock_load, config):
        mock_client_cls.return_value.embed.side_effect = _fake_embed
        results = run_pipeline(strategy="structure", config=config, verbose=False)
        assert results[0].strategy == "structure"

    @patch("deepseek_chat.core.rag.pipeline.CORPUS_FILES", SMALL_CORPUS)
    @patch("deepseek_chat.core.rag.pipeline.load_corpus_text", side_effect=_make_corpus_text)
    @patch("deepseek_chat.core.rag.pipeline.OllamaEmbeddingClient")
    def test_elapsed_seconds_is_positive(self, mock_client_cls, mock_load, config):
        mock_client_cls.return_value.embed.side_effect = _fake_embed
        results = run_pipeline(strategy="fixed", config=config, verbose=False)
        assert results[0].elapsed_seconds >= 0
