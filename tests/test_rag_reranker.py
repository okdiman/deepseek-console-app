"""Unit tests for deepseek_chat.core.rag.reranker."""

import pytest
from deepseek_chat.core.rag.reranker import (
    ThresholdFilter,
    HeuristicReranker,
    rerank_and_filter,
    FilterResult,
)


def _make_results(scores):
    """Helper: build fake search results with given scores."""
    return [
        {"score": s, "text": f"chunk about transformers attention mechanism {i}", "source": f"doc{i}.md"}
        for i, s in enumerate(scores)
    ]


# ── ThresholdFilter ────────────────────────────────────────────────────────────

class TestThresholdFilter:
    def test_keeps_above_threshold(self):
        f = ThresholdFilter()
        results = _make_results([0.8, 0.5, 0.2])
        kept = f.filter(results, threshold=0.4)
        assert len(kept) == 2
        assert all(r["score"] >= 0.4 for r in kept)

    def test_drops_all_below(self):
        f = ThresholdFilter()
        results = _make_results([0.1, 0.2, 0.15])
        kept = f.filter(results, threshold=0.3)
        assert kept == []

    def test_keeps_all_above(self):
        f = ThresholdFilter()
        results = _make_results([0.9, 0.8, 0.7])
        kept = f.filter(results, threshold=0.5)
        assert len(kept) == 3

    def test_exact_threshold_is_kept(self):
        f = ThresholdFilter()
        results = _make_results([0.3])
        kept = f.filter(results, threshold=0.3)
        assert len(kept) == 1

    def test_empty_input(self):
        f = ThresholdFilter()
        assert ThresholdFilter().filter([], threshold=0.5) == []

    def test_missing_score_defaults_to_zero(self):
        f = ThresholdFilter()
        results = [{"text": "no score field"}]
        kept = f.filter(results, threshold=0.1)
        assert kept == []


# ── HeuristicReranker ──────────────────────────────────────────────────────────

class TestHeuristicReranker:
    def test_reorder_by_keyword_overlap(self):
        reranker = HeuristicReranker()
        results = [
            {"score": 0.5, "text": "something completely unrelated", "source": "a.md"},
            {"score": 0.5, "text": "transformer attention mechanism query key value", "source": "b.md"},
        ]
        reranked = reranker.rerank("transformer attention", results)
        # b.md should bubble up (more keyword overlap)
        assert reranked[0]["source"] == "b.md"

    def test_boosts_score(self):
        reranker = HeuristicReranker()
        results = [{"score": 0.5, "text": "attention mechanism", "source": "x.md"}]
        reranked = reranker.rerank("attention mechanism", results)
        assert reranked[0]["score"] > 0.5

    def test_preserves_order_when_no_overlap(self):
        reranker = HeuristicReranker()
        results = _make_results([0.8, 0.6])
        reranked = reranker.rerank("zzz completely unrelated query", results)
        # No overlap — scores unchanged, original order preserved
        assert reranked[0]["score"] == 0.8

    def test_empty_query(self):
        reranker = HeuristicReranker()
        results = _make_results([0.7, 0.5])
        reranked = reranker.rerank("", results)
        assert len(reranked) == 2

    def test_empty_results(self):
        reranker = HeuristicReranker()
        assert HeuristicReranker().rerank("query", []) == []

    def test_does_not_mutate_original(self):
        reranker = HeuristicReranker()
        original = [{"score": 0.5, "text": "attention is all you need", "source": "x.md"}]
        reranker.rerank("attention", original)
        assert original[0]["score"] == 0.5  # original unchanged


# ── rerank_and_filter ──────────────────────────────────────────────────────────

class TestRerankAndFilter:
    def test_threshold_mode_pre_post_counts(self):
        results = _make_results([0.8, 0.5, 0.2, 0.1])
        fr = rerank_and_filter("query", results, reranker_type="threshold", threshold=0.4, final_top_k=5)
        assert fr.pre_filter_count == 4
        assert fr.post_filter_count == 2
        assert len(fr.results) == 2

    def test_none_mode_passes_through(self):
        results = _make_results([0.9, 0.1])
        fr = rerank_and_filter("query", results, reranker_type="none", threshold=0.99, final_top_k=10)
        # threshold ignored in "none" mode
        assert len(fr.results) == 2
        assert fr.post_filter_count == 2

    def test_heuristic_mode(self):
        results = [
            {"score": 0.6, "text": "neural network deep learning", "source": "a.md"},
            {"score": 0.6, "text": "attention is all you need transformer", "source": "b.md"},
        ]
        fr = rerank_and_filter(
            "transformer attention",
            results,
            reranker_type="heuristic",
            threshold=0.3,
            final_top_k=2,
        )
        # b.md should be first (more keyword overlap)
        assert fr.results[0]["source"] == "b.md"

    def test_final_top_k_cap(self):
        results = _make_results([0.9, 0.8, 0.7, 0.6, 0.5])
        fr = rerank_and_filter("q", results, reranker_type="none", threshold=0.0, final_top_k=3)
        assert len(fr.results) == 3

    def test_all_filtered_out(self):
        results = _make_results([0.1, 0.2])
        fr = rerank_and_filter("q", results, reranker_type="threshold", threshold=0.9, final_top_k=3)
        assert fr.results == []
        assert fr.post_filter_count == 0

    def test_empty_input(self):
        fr = rerank_and_filter("q", [], reranker_type="threshold", threshold=0.3, final_top_k=3)
        assert fr.results == []
        assert fr.pre_filter_count == 0
        assert fr.post_filter_count == 0

    def test_threshold_used_is_recorded(self):
        results = _make_results([0.5])
        fr = rerank_and_filter("q", results, threshold=0.42)
        assert fr.threshold_used == 0.42
