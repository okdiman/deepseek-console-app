"""
RAG benchmark — baseline vs filter vs rewrite vs full.

Modes:
  baseline  — plain RAG (top-k, no filter, no query rewrite)
  filter    — RAG + threshold/heuristic reranking
  rewrite   — RAG + LLM query rewriting, no filter
  full      — RAG + query rewriting + filter

For each EvalCase in eval_set, all four modes are run and compared.
Legacy plain_query / rag_query / run_benchmark are preserved for the `ask` CLI command.
"""

import asyncio
import json
import time
from asyncio import TimeoutError as AsyncTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from deepseek_chat.core.agent_factory import build_client
from deepseek_chat.core.rag.config import load_rag_config
from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
from deepseek_chat.core.rag.query_rewriter import QueryRewriter
from deepseek_chat.core.rag.reranker import rerank_and_filter
from deepseek_chat.core.rag.store import search_by_embedding
from experiments.rag_compare.eval_set import EvalCase, EVAL_SET

_DATA_DIR = Path(__file__).parent / "data"

_SYSTEM_PLAIN = "You are a helpful assistant. Answer the question concisely and accurately."
_SYSTEM_RAG_PREFIX = (
    "You are a helpful assistant. "
    "Use the provided documentation context to answer the question accurately."
)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """Legacy 2-mode result (plain vs RAG). Kept for backward compatibility."""
    question: str
    expected_keywords: List[str]
    expected_sources: List[str]
    plain_answer: str
    rag_answer: str
    retrieved_sources: List[str]
    keyword_hits_plain: int
    keyword_hits_rag: int
    source_hit: bool
    plain_elapsed: float
    rag_elapsed: float


@dataclass
class ModeResult:
    """Result for a single benchmark mode."""
    answer: str
    sources: List[str]          # retrieved filenames
    keyword_hits: int
    source_hit: bool
    chunks_before: int          # candidates fetched (pre-filter pool)
    chunks_after: int           # chunks that survived the filter
    elapsed: float


@dataclass
class MultiModeBenchmarkResult:
    """4-mode benchmark result for one eval question."""
    question: str
    expected_keywords: List[str]
    expected_sources: List[str]
    baseline: ModeResult        # RAG, no filter, no rewrite
    filter_only: ModeResult     # RAG + threshold filter
    rewrite_only: ModeResult    # RAG + query rewrite
    full: ModeResult            # RAG + rewrite + filter


# ── LLM helpers ───────────────────────────────────────────────────────────────

_BENCHMARK_TEMPERATURE = 0.1  # low temperature for reproducible benchmark results
_BENCHMARK_TIMEOUT = 90.0    # seconds; skips a hung API call instead of blocking the run


async def _collect_stream(client, messages: list) -> Tuple[str, float]:
    """Drain the streaming LLM response into a string. Returns (text, elapsed_s)."""
    t0 = time.perf_counter()
    tokens = []

    async def _drain():
        async for chunk in client.stream_message(messages, temperature=_BENCHMARK_TEMPERATURE):
            if chunk.startswith('{"__type__"'):
                continue
            tokens.append(chunk)

    try:
        await asyncio.wait_for(_drain(), timeout=_BENCHMARK_TIMEOUT)
    except AsyncTimeoutError:
        tokens.append(f"[TIMEOUT after {_BENCHMARK_TIMEOUT:.0f}s]")

    return "".join(tokens), time.perf_counter() - t0


def _build_rag_block(results: list) -> str:
    lines = ["", "---", "Relevant documentation (retrieved from local index):"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        section = r.get("section", "")
        source = Path(r.get("source", "")).name
        label = f"{title} › {section}" if section else f"{title} ({source})"
        text = r["text"].strip()[:500].replace("\n", " ")
        lines.append(f"\n[{i}] {label}")
        lines.append(f'"{text}"')
    lines.append("---")
    return "\n".join(lines)


async def _llm_with_rag(client, question: str, results: list) -> Tuple[str, float]:
    """Run LLM with a RAG block built from the given results."""
    sources = [Path(r["source"]).name for r in results]  # noqa: F841 (used below)
    system_prompt = _SYSTEM_RAG_PREFIX + _build_rag_block(results)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    return await _collect_stream(client, messages)


# ── Legacy API (used by `ask` CLI command) ─────────────────────────────────────

async def plain_query(client, question: str) -> Tuple[str, float]:
    """LLM call without any RAG context."""
    messages = [
        {"role": "system", "content": _SYSTEM_PLAIN},
        {"role": "user", "content": question},
    ]
    return await _collect_stream(client, messages)


async def rag_query(
    client,
    question: str,
    embedder: OllamaEmbeddingClient,
    config,
    top_k: int = 3,
    strategy: str = "structure",
) -> Tuple[str, List[str], float]:
    """LLM call with RAG context. Returns (answer, retrieved_source_names, elapsed_s)."""
    vec = embedder.embed([question])[0]
    results = search_by_embedding(vec, top_k=top_k, strategy=strategy, db_path=config.db_path)
    sources = [Path(r["source"]).name for r in results]
    answer, elapsed = await _llm_with_rag(client, question, results)
    return answer, sources, elapsed


# ── 4-mode query functions ─────────────────────────────────────────────────────

async def _run_mode_baseline(
    client, question: str, embedder, config, top_k: int, strategy: str
) -> ModeResult:
    """Baseline: embed raw query, fetch top_k, no filter."""
    t0 = time.perf_counter()
    vec = embedder.embed([question])[0]
    results = search_by_embedding(vec, top_k=top_k, strategy=strategy, db_path=config.db_path)
    sources = [Path(r["source"]).name for r in results]
    answer, _ = await _llm_with_rag(client, question, results)
    elapsed = time.perf_counter() - t0
    return ModeResult(
        answer=answer,
        sources=sources,
        keyword_hits=0,   # filled in by caller
        source_hit=False,
        chunks_before=len(results),
        chunks_after=len(results),
        elapsed=round(elapsed, 2),
    )


async def _run_mode_filter(
    client, question: str, embedder, config,
    top_k: int, strategy: str,
    pre_rerank_top_k: int, threshold: float, reranker_type: str,
) -> ModeResult:
    """Filter: embed raw query, fetch more candidates, apply reranker/threshold."""
    t0 = time.perf_counter()
    vec = embedder.embed([question])[0]
    pre_k = max(pre_rerank_top_k, top_k)
    candidates = search_by_embedding(vec, top_k=pre_k, strategy=strategy, db_path=config.db_path)
    fr = rerank_and_filter(
        query=question,
        results=candidates,
        reranker_type=reranker_type,
        threshold=threshold,
        final_top_k=top_k,
    )
    sources = [Path(r["source"]).name for r in fr.results]
    answer, _ = await _llm_with_rag(client, question, fr.results)
    elapsed = time.perf_counter() - t0
    return ModeResult(
        answer=answer,
        sources=sources,
        keyword_hits=0,
        source_hit=False,
        chunks_before=fr.pre_filter_count,
        chunks_after=fr.post_filter_count,
        elapsed=round(elapsed, 2),
    )


async def _run_mode_rewrite(
    client, question: str, embedder, config, top_k: int, strategy: str
) -> ModeResult:
    """Rewrite: LLM query rewrite, then baseline retrieval (no filter)."""
    t0 = time.perf_counter()
    rewritten = await QueryRewriter(client).rewrite(question)
    vec = embedder.embed([rewritten])[0]
    results = search_by_embedding(vec, top_k=top_k, strategy=strategy, db_path=config.db_path)
    sources = [Path(r["source"]).name for r in results]
    answer, _ = await _llm_with_rag(client, question, results)
    elapsed = time.perf_counter() - t0
    return ModeResult(
        answer=answer,
        sources=sources,
        keyword_hits=0,
        source_hit=False,
        chunks_before=len(results),
        chunks_after=len(results),
        elapsed=round(elapsed, 2),
    )


async def _run_mode_full(
    client, question: str, embedder, config,
    top_k: int, strategy: str,
    pre_rerank_top_k: int, threshold: float, reranker_type: str,
) -> ModeResult:
    """Full: LLM query rewrite + filter/reranker."""
    t0 = time.perf_counter()
    rewritten = await QueryRewriter(client).rewrite(question)
    vec = embedder.embed([rewritten])[0]
    pre_k = max(pre_rerank_top_k, top_k)
    candidates = search_by_embedding(vec, top_k=pre_k, strategy=strategy, db_path=config.db_path)
    fr = rerank_and_filter(
        query=rewritten,
        results=candidates,
        reranker_type=reranker_type,
        threshold=threshold,
        final_top_k=top_k,
    )
    sources = [Path(r["source"]).name for r in fr.results]
    answer, _ = await _llm_with_rag(client, question, fr.results)
    elapsed = time.perf_counter() - t0
    return ModeResult(
        answer=answer,
        sources=sources,
        keyword_hits=0,
        source_hit=False,
        chunks_before=fr.pre_filter_count,
        chunks_after=fr.post_filter_count,
        elapsed=round(elapsed, 2),
    )


def _fill_metrics(mode: ModeResult, expected_keywords: List[str], expected_sources: List[str]) -> ModeResult:
    """Compute and inject keyword_hits + source_hit into a ModeResult."""
    hits = _keyword_hits(mode.answer, expected_keywords)
    hit = _source_hit(mode.sources, expected_sources)
    return ModeResult(
        answer=mode.answer,
        sources=mode.sources,
        keyword_hits=hits,
        source_hit=hit,
        chunks_before=mode.chunks_before,
        chunks_after=mode.chunks_after,
        elapsed=mode.elapsed,
    )


# ── Metrics ───────────────────────────────────────────────────────────────────

def _keyword_hits(answer: str, keywords: List[str]) -> int:
    lower = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in lower)


def _source_hit(retrieved: List[str], expected: List[str]) -> bool:
    retrieved_lower = {s.lower() for s in retrieved}
    return any(e.lower() in retrieved_lower for e in expected)


# ── Runners ───────────────────────────────────────────────────────────────────

async def run_benchmark(
    eval_cases: Optional[List[EvalCase]] = None,
    top_k: int = 3,
    strategy: str = "structure",
    verbose: bool = True,
) -> List[BenchmarkResult]:
    """Legacy 2-mode benchmark (plain vs RAG). Kept for CLI backward compatibility."""
    if eval_cases is None:
        eval_cases = EVAL_SET

    client = build_client()
    config = load_rag_config()
    embedder = OllamaEmbeddingClient(config)

    results: List[BenchmarkResult] = []

    for i, case in enumerate(eval_cases, 1):
        if verbose:
            print(f"\n[{i}/{len(eval_cases)}] {case.question}")
            print("  plain ... ", end="", flush=True)

        plain_ans, plain_t = await plain_query(client, case.question)

        if verbose:
            print(f"{plain_t:.1f}s  |  rag ... ", end="", flush=True)

        rag_ans, sources, rag_t = await rag_query(
            client, case.question, embedder, config, top_k, strategy
        )

        if verbose:
            print(f"{rag_t:.1f}s")

        hits_plain = _keyword_hits(plain_ans, case.expected_keywords)
        hits_rag = _keyword_hits(rag_ans, case.expected_keywords)
        hit = _source_hit(sources, case.expected_sources)

        results.append(BenchmarkResult(
            question=case.question,
            expected_keywords=case.expected_keywords,
            expected_sources=case.expected_sources,
            plain_answer=plain_ans,
            rag_answer=rag_ans,
            retrieved_sources=sources,
            keyword_hits_plain=hits_plain,
            keyword_hits_rag=hits_rag,
            source_hit=hit,
            plain_elapsed=round(plain_t, 2),
            rag_elapsed=round(rag_t, 2),
        ))

    return results


async def run_benchmark_modes(
    eval_cases: Optional[List[EvalCase]] = None,
    top_k: int = 3,
    strategy: str = "structure",
    pre_rerank_top_k: int = 10,
    threshold: float = 0.30,
    reranker_type: str = "threshold",
    modes: Optional[List[str]] = None,
    verbose: bool = True,
) -> List[MultiModeBenchmarkResult]:
    """
    4-mode benchmark: baseline | filter | rewrite | full.

    Args:
        modes: subset of ["baseline", "filter", "rewrite", "full"] to run.
               Defaults to all four.
    """
    if eval_cases is None:
        eval_cases = EVAL_SET
    if modes is None:
        modes = ["baseline", "filter", "rewrite", "full"]

    client = build_client()
    config = load_rag_config()
    embedder = OllamaEmbeddingClient(config)

    results: List[MultiModeBenchmarkResult] = []

    for i, case in enumerate(eval_cases, 1):
        if verbose:
            print(f"\n[{i}/{len(eval_cases)}] {case.question}")

        # ── baseline ───────────────────────────────────────────────────────
        if verbose:
            print("  baseline ... ", end="", flush=True)
        baseline = await _run_mode_baseline(client, case.question, embedder, config, top_k, strategy)
        baseline = _fill_metrics(baseline, case.expected_keywords, case.expected_sources)
        if verbose:
            print(f"{baseline.elapsed:.1f}s", end="")

        # ── filter ─────────────────────────────────────────────────────────
        if verbose:
            print("  |  filter ... ", end="", flush=True)
        filter_only = await _run_mode_filter(
            client, case.question, embedder, config,
            top_k, strategy, pre_rerank_top_k, threshold, reranker_type,
        )
        filter_only = _fill_metrics(filter_only, case.expected_keywords, case.expected_sources)
        if verbose:
            print(f"{filter_only.elapsed:.1f}s", end="")

        # ── rewrite ────────────────────────────────────────────────────────
        if verbose:
            print("  |  rewrite ... ", end="", flush=True)
        rewrite_only = await _run_mode_rewrite(client, case.question, embedder, config, top_k, strategy)
        rewrite_only = _fill_metrics(rewrite_only, case.expected_keywords, case.expected_sources)
        if verbose:
            print(f"{rewrite_only.elapsed:.1f}s", end="")

        # ── full ───────────────────────────────────────────────────────────
        if verbose:
            print("  |  full ... ", end="", flush=True)
        full = await _run_mode_full(
            client, case.question, embedder, config,
            top_k, strategy, pre_rerank_top_k, threshold, reranker_type,
        )
        full = _fill_metrics(full, case.expected_keywords, case.expected_sources)
        if verbose:
            print(f"{full.elapsed:.1f}s")

        results.append(MultiModeBenchmarkResult(
            question=case.question,
            expected_keywords=case.expected_keywords,
            expected_sources=case.expected_sources,
            baseline=baseline,
            filter_only=filter_only,
            rewrite_only=rewrite_only,
            full=full,
        ))

    return results


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(results: List[BenchmarkResult]) -> None:
    """Legacy 2-mode (plain vs RAG) output."""
    sep = "=" * 70

    print(f"\n{sep}")
    print("  RAG vs NO-RAG — BENCHMARK RESULTS")
    print(sep)

    for i, r in enumerate(results, 1):
        n = len(r.expected_keywords)
        plain_pct = round(100 * r.keyword_hits_plain / n) if n else 0
        rag_pct = round(100 * r.keyword_hits_rag / n) if n else 0

        if r.keyword_hits_rag > r.keyword_hits_plain:
            winner = "RAG ↑"
        elif r.keyword_hits_plain > r.keyword_hits_rag:
            winner = "PLAIN ↑"
        else:
            winner = "TIE"

        src_mark = "✓" if r.source_hit else "✗"

        print(f"\n{i}. {r.question}")
        print(f"   Keywords  plain={r.keyword_hits_plain}/{n} ({plain_pct}%)  "
              f"rag={r.keyword_hits_rag}/{n} ({rag_pct}%)  → {winner}")
        print(f"   Sources   retrieved={r.retrieved_sources}  expected hit: {src_mark}")
        print(f"   Time      plain={r.plain_elapsed}s  rag={r.rag_elapsed}s")

        plain_preview = r.plain_answer[:120].replace("\n", " ")
        rag_preview = r.rag_answer[:120].replace("\n", " ")
        print(f"   Plain »   {plain_preview}…")
        print(f"   RAG   »   {rag_preview}…")

    total_possible = sum(len(r.expected_keywords) for r in results)
    total_plain = sum(r.keyword_hits_plain for r in results)
    total_rag = sum(r.keyword_hits_rag for r in results)
    source_hits = sum(1 for r in results if r.source_hit)
    rag_wins = sum(1 for r in results if r.keyword_hits_rag > r.keyword_hits_plain)
    plain_wins = sum(1 for r in results if r.keyword_hits_plain > r.keyword_hits_rag)
    ties = len(results) - rag_wins - plain_wins

    print(f"\n{sep}")
    print(f"  Questions        : {len(results)}")
    print(f"  Keyword hits     : plain={total_plain}/{total_possible}  "
          f"rag={total_rag}/{total_possible}")
    plain_pct = round(100 * total_plain / total_possible) if total_possible else 0
    rag_pct = round(100 * total_rag / total_possible) if total_possible else 0
    print(f"  Hit rate         : plain={plain_pct}%  rag={rag_pct}%")
    print(f"  RAG wins         : {rag_wins}  plain wins: {plain_wins}  ties: {ties}")
    print(f"  Source precision : {source_hits}/{len(results)} questions hit expected source")
    print(sep)


def print_mode_results(results: List[MultiModeBenchmarkResult]) -> None:
    """4-mode benchmark output."""
    sep = "=" * 80
    mode_names = ["baseline", "filter ", "rewrite", "full   "]

    print(f"\n{sep}")
    print("  RAG BENCHMARK — 4-MODE COMPARISON")
    print(sep)

    for i, r in enumerate(results, 1):
        n = len(r.expected_keywords)
        modes = [r.baseline, r.filter_only, r.rewrite_only, r.full]

        print(f"\n{i}. {r.question}")
        print(f"   {'Mode':<10} {'KW hits':>8} {'%':>5} {'src':>4} {'chunks':>12} {'time':>6}")
        print(f"   {'-'*55}")

        best_kw = max(m.keyword_hits for m in modes)
        for name, m in zip(mode_names, modes):
            kw_pct = round(100 * m.keyword_hits / n) if n else 0
            src_mark = "✓" if m.source_hit else "✗"
            filter_info = f"{m.chunks_after}/{m.chunks_before}" if m.chunks_before != m.chunks_after else f"{m.chunks_after}"
            winner_mark = " ←" if m.keyword_hits == best_kw and best_kw > 0 else ""
            print(f"   {name:<10} {m.keyword_hits:>4}/{n:<3} {kw_pct:>4}% {src_mark:>4} {filter_info:>12} {m.elapsed:>5.1f}s{winner_mark}")

        # Short answer preview for the best mode
        best_mode = max(modes, key=lambda m: m.keyword_hits)
        preview = best_mode.answer[:100].replace("\n", " ")
        print(f"   Best »  {preview}…")

    # ── Summary table ─────────────────────────────────────────────────────
    total_possible = sum(len(r.expected_keywords) for r in results)
    mode_labels = ["baseline", "filter_only", "rewrite_only", "full"]
    mode_display = ["baseline", "filter  ", "rewrite ", "full    "]

    print(f"\n{sep}")
    print("  SUMMARY")
    print(f"  {'Mode':<12} {'KW hits':>10} {'Hit%':>6} {'Src acc':>8} {'Avg chunks kept':>16} {'Avg time':>9}")
    print(f"  {'-'*70}")

    for label, display in zip(mode_labels, mode_display):
        modes_list = [getattr(r, label) for r in results]
        total_kw = sum(m.keyword_hits for m in modes_list)
        kw_pct = round(100 * total_kw / total_possible) if total_possible else 0
        src_acc = round(100 * sum(1 for m in modes_list if m.source_hit) / len(results)) if results else 0
        avg_after = sum(m.chunks_after for m in modes_list) / len(results) if results else 0
        avg_time = sum(m.elapsed for m in modes_list) / len(results) if results else 0
        print(f"  {display:<12} {total_kw:>5}/{total_possible:<5} {kw_pct:>5}% {src_acc:>7}% {avg_after:>14.1f} {avg_time:>8.1f}s")

    print(sep)


def save_results(results: List[BenchmarkResult], path: Optional[str] = None) -> str:
    if path is None:
        path = str(_DATA_DIR / "benchmark_results.json")
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = [r.__dict__ for r in results]
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_mode_results(results: List[MultiModeBenchmarkResult], path: Optional[str] = None) -> str:
    if path is None:
        path = str(_DATA_DIR / "benchmark_modes_results.json")
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _serialize(r: MultiModeBenchmarkResult) -> Dict:
        def _m(m: ModeResult) -> Dict:
            return m.__dict__
        return {
            "question": r.question,
            "expected_keywords": r.expected_keywords,
            "expected_sources": r.expected_sources,
            "baseline": _m(r.baseline),
            "filter_only": _m(r.filter_only),
            "rewrite_only": _m(r.rewrite_only),
            "full": _m(r.full),
        }

    Path(path).write_text(
        json.dumps([_serialize(r) for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
