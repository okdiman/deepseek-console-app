"""
Reranking and relevance filtering for RAG search results.

Two strategies:
  threshold  — drops chunks with cosine similarity below a cutoff score
  heuristic  — keyword-overlap boost, then threshold filter
  none       — pass-through, no filtering (original behaviour)

Usage:
    from deepseek_chat.core.rag.reranker import rerank_and_filter
    result = rerank_and_filter(query, raw_results, reranker_type="threshold", threshold=0.30, final_top_k=3)
    print(f"Kept {result.post_filter_count}/{result.pre_filter_count} chunks")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class FilterResult:
    results: List[Dict]
    pre_filter_count: int   # candidates entering the filter
    post_filter_count: int  # chunks that passed the threshold (before top_k cap)
    threshold_used: float


class ThresholdFilter:
    """Drops chunks whose cosine similarity score is below the minimum threshold."""

    def filter(self, results: List[Dict], threshold: float) -> List[Dict]:
        return [r for r in results if r.get("score", 0.0) >= threshold]


class HeuristicReranker:
    """
    Boosts score based on keyword overlap between query and chunk text,
    then applies a threshold filter.

    Overlap boost: up to +30% additive on the cosine score.
    """

    def rerank(self, query: str, results: List[Dict]) -> List[Dict]:
        query_terms = set(re.findall(r"\w+", query.lower()))
        if not query_terms:
            return results
        reranked = []
        for r in results:
            text_terms = set(re.findall(r"\w+", r.get("text", "").lower()))
            overlap = len(query_terms & text_terms) / len(query_terms)
            boosted = dict(r)
            boosted["score"] = r.get("score", 0.0) * (1.0 + 0.3 * overlap)
            reranked.append(boosted)
        return sorted(reranked, key=lambda x: x["score"], reverse=True)


def rerank_and_filter(
    query: str,
    results: List[Dict],
    reranker_type: str = "threshold",
    threshold: float = 0.30,
    final_top_k: int = 3,
) -> FilterResult:
    """
    Apply reranking and/or threshold filtering to a list of search results.

    Args:
        query:          Original (or rewritten) user query.
        results:        Raw results from search_by_embedding(), each with a "score" key.
        reranker_type:  "none" | "threshold" | "heuristic"
        threshold:      Minimum cosine similarity to retain a chunk.
        final_top_k:    Maximum number of chunks to return after filtering.

    Returns:
        FilterResult with final results and bookkeeping counts.
    """
    pre_count = len(results)

    if reranker_type == "heuristic":
        reranked = HeuristicReranker().rerank(query, results)
        filtered = ThresholdFilter().filter(reranked, threshold)
    elif reranker_type == "threshold":
        filtered = ThresholdFilter().filter(results, threshold)
    else:  # "none"
        filtered = list(results)

    final = filtered[:final_top_k]
    return FilterResult(
        results=final,
        pre_filter_count=pre_count,
        post_filter_count=len(filtered),
        threshold_used=threshold,
    )
