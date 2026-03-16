"""
Comparison of two chunking strategies: fixed-size vs structure-based.

Metrics:
  1. Chunk size distribution (avg / min / max / stddev tokens)
  2. Section coverage (% of chunks with non-empty section field)
  3. Retrieval quality on 8 probe queries (top-3 results per strategy)
"""

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import tiktoken

from deepseek_chat.core.rag.config import RagConfig, load_rag_config
from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
from deepseek_chat.core.rag.store import get_all_chunks, search_by_embedding

_DATA_DIR = Path(__file__).parent / "data"
_ENC = tiktoken.get_encoding("cl100k_base")

PROBE_QUERIES = [
    "How does the agent hook system work?",
    "What is PEP 8 naming convention for classes?",
    "How does information retrieval work?",
    "What is the transformer self-attention mechanism?",
    "How do large language models handle context?",
    "How does Python handle concurrent tasks?",
    "What SQLite tables does the scheduler use?",
    "How is the MCP tool execution integrated into the agent?",
]


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class StrategyStats:
    strategy: str
    total_chunks: int
    avg_tokens: float
    min_tokens: int
    max_tokens: int
    stddev_tokens: float
    pct_with_section: float     # 0–100


@dataclass
class QueryResult:
    query: str
    fixed_top1_id: str
    fixed_top1_score: float
    fixed_top1_section: str
    fixed_top1_source: str
    structure_top1_id: str
    structure_top1_score: float
    structure_top1_section: str
    structure_top1_source: str
    same_source_in_top3: bool   # True if both strategies return same source file


@dataclass
class ComparisonReport:
    fixed_stats: StrategyStats
    structure_stats: StrategyStats
    query_results: List[QueryResult] = field(default_factory=list)
    agreement_rate: float = 0.0  # fraction of queries with same_source_in_top3


# ── Helpers ───────────────────────────────────────────────────────────────

def _token_count(text: str) -> int:
    return len(_ENC.encode(text))


def _compute_stats(strategy: str, db_path: str) -> StrategyStats:
    rows = get_all_chunks(strategy=strategy, db_path=db_path)
    if not rows:
        return StrategyStats(strategy, 0, 0, 0, 0, 0, 0)

    counts = [_token_count(r["text"]) for r in rows]
    with_section = sum(1 for r in rows if r.get("section", ""))

    return StrategyStats(
        strategy=strategy,
        total_chunks=len(rows),
        avg_tokens=round(statistics.mean(counts), 1),
        min_tokens=min(counts),
        max_tokens=max(counts),
        stddev_tokens=round(statistics.stdev(counts) if len(counts) > 1 else 0, 1),
        pct_with_section=round(100 * with_section / len(rows), 1),
    )


def _top3_sources(results: list) -> set:
    return {r["source"] for r in results[:3]}


# ── Main ──────────────────────────────────────────────────────────────────

def compare_strategies(
    config: Optional[RagConfig] = None,
    probe_queries: Optional[List[str]] = None,
) -> ComparisonReport:
    """Run comparison between fixed and structure strategies."""
    if config is None:
        config = load_rag_config()
    if probe_queries is None:
        probe_queries = PROBE_QUERIES

    embedder = OllamaEmbeddingClient(config)

    fixed_stats = _compute_stats("fixed", config.db_path)
    structure_stats = _compute_stats("structure", config.db_path)

    query_results: List[QueryResult] = []
    agreements = 0

    for query in probe_queries:
        vec = embedder.embed([query])[0]

        fixed_res = search_by_embedding(vec, top_k=3, strategy="fixed", db_path=config.db_path)
        struct_res = search_by_embedding(vec, top_k=3, strategy="structure", db_path=config.db_path)

        if not fixed_res or not struct_res:
            continue

        same = bool(_top3_sources(fixed_res) & _top3_sources(struct_res))
        if same:
            agreements += 1

        query_results.append(QueryResult(
            query=query,
            fixed_top1_id=fixed_res[0]["chunk_id"],
            fixed_top1_score=round(fixed_res[0]["score"], 4),
            fixed_top1_section=fixed_res[0].get("section", ""),
            fixed_top1_source=fixed_res[0]["source"],
            structure_top1_id=struct_res[0]["chunk_id"],
            structure_top1_score=round(struct_res[0]["score"], 4),
            structure_top1_section=struct_res[0].get("section", ""),
            structure_top1_source=struct_res[0]["source"],
            same_source_in_top3=same,
        ))

    agreement_rate = agreements / len(query_results) if query_results else 0.0

    return ComparisonReport(
        fixed_stats=fixed_stats,
        structure_stats=structure_stats,
        query_results=query_results,
        agreement_rate=round(agreement_rate, 3),
    )


# ── Output ────────────────────────────────────────────────────────────────

def print_report(report: ComparisonReport) -> None:
    sep = "=" * 60

    def _print_stats(s: StrategyStats) -> None:
        print(f"  Total chunks    : {s.total_chunks}")
        print(f"  Avg tokens      : {s.avg_tokens} ± {s.stddev_tokens}")
        print(f"  Min / Max tokens: {s.min_tokens} / {s.max_tokens}")
        print(f"  With section    : {s.pct_with_section}%")

    print(f"\n{sep}")
    print("  CHUNKING STRATEGY COMPARISON")
    print(sep)

    print("\nFIXED-SIZE (sliding window):")
    _print_stats(report.fixed_stats)

    print("\nSTRUCTURE-BASED (headings / AST):")
    _print_stats(report.structure_stats)

    print(f"\n{sep}")
    print("  RETRIEVAL QUALITY — 8 probe queries")
    print(sep)

    for qr in report.query_results:
        agree = "✓" if qr.same_source_in_top3 else "✗"
        print(f"\nQuery: {qr.query}")
        section_f = f"  section={qr.fixed_top1_section!r}" if qr.fixed_top1_section else ""
        section_s = f"  section={qr.structure_top1_section!r}" if qr.structure_top1_section else ""
        print(f"  Fixed     score={qr.fixed_top1_score:.4f}{section_f}")
        print(f"  Structure score={qr.structure_top1_score:.4f}{section_s}")
        print(f"  Same source in top-3: {agree}")

    print(f"\n{sep}")
    pct = round(report.agreement_rate * 100, 1)
    print(f"  Agreement rate : {pct}%  ({sum(1 for q in report.query_results if q.same_source_in_top3)}/{len(report.query_results)} queries)")
    struct_wins = sum(1 for q in report.query_results if q.structure_top1_score > q.fixed_top1_score)
    fixed_wins = len(report.query_results) - struct_wins
    print(f"  Structure wins : {struct_wins}/{len(report.query_results)} queries by top-1 score")
    print(f"  Fixed wins     : {fixed_wins}/{len(report.query_results)} queries by top-1 score")
    print(sep)


def save_report(report: ComparisonReport, path: Optional[str] = None) -> str:
    """Save report as JSON. Returns the path written to."""
    if path is None:
        path = str(_DATA_DIR / "comparison_report.json")

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "fixed_stats": report.fixed_stats.__dict__,
        "structure_stats": report.structure_stats.__dict__,
        "agreement_rate": report.agreement_rate,
        "query_results": [q.__dict__ for q in report.query_results],
    }
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
