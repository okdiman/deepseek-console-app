"""
RAG vs no-RAG benchmark.

For each EvalCase in eval_set:
  1. plain_query(question)  — LLM with no extra context
  2. rag_query(question)    — LLM with top-k chunks injected into system prompt

Metrics per question:
  - keyword_hits_plain / keyword_hits_rag: how many expected keywords appear in the answer
  - source_hit: True if any expected source was retrieved by RAG
"""

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from deepseek_chat.core.agent_factory import build_client
from deepseek_chat.core.rag.config import load_rag_config
from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
from deepseek_chat.core.rag.store import search_by_embedding
from experiments.rag_compare.eval_set import EvalCase, EVAL_SET

_DATA_DIR = Path(__file__).parent / "data"

_SYSTEM_PLAIN = "You are a helpful assistant. Answer the question concisely and accurately."
_SYSTEM_RAG_PREFIX = (
    "You are a helpful assistant. "
    "Use the provided documentation context to answer the question accurately."
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
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


# ── LLM helpers ───────────────────────────────────────────────────────────────

async def _collect_stream(client, messages: list) -> Tuple[str, float]:
    """Drain the streaming LLM response into a string. Returns (text, elapsed_s)."""
    t0 = time.perf_counter()
    tokens = []
    async for chunk in client.stream_message(messages):
        if chunk.startswith('{"__type__"'):  # tool-call events — skip
            continue
        tokens.append(chunk)
    return "".join(tokens), time.perf_counter() - t0


async def plain_query(client, question: str) -> Tuple[str, float]:
    """LLM call without any RAG context."""
    messages = [
        {"role": "system", "content": _SYSTEM_PLAIN},
        {"role": "user", "content": question},
    ]
    return await _collect_stream(client, messages)


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
    system_prompt = _SYSTEM_RAG_PREFIX + _build_rag_block(results)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    answer, elapsed = await _collect_stream(client, messages)
    return answer, sources, elapsed


# ── Metrics ───────────────────────────────────────────────────────────────────

def _keyword_hits(answer: str, keywords: List[str]) -> int:
    lower = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in lower)


def _source_hit(retrieved: List[str], expected: List[str]) -> bool:
    retrieved_lower = {s.lower() for s in retrieved}
    return any(e.lower() in retrieved_lower for e in expected)


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_benchmark(
    eval_cases: Optional[List[EvalCase]] = None,
    top_k: int = 3,
    strategy: str = "structure",
    verbose: bool = True,
) -> List[BenchmarkResult]:
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


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(results: List[BenchmarkResult]) -> None:
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

        # Short answer previews
        plain_preview = r.plain_answer[:120].replace("\n", " ")
        rag_preview = r.rag_answer[:120].replace("\n", " ")
        print(f"   Plain »   {plain_preview}…")
        print(f"   RAG   »   {rag_preview}…")

    # ── Summary ───────────────────────────────────────────────────────────
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


def save_results(results: List[BenchmarkResult], path: Optional[str] = None) -> str:
    if path is None:
        path = str(_DATA_DIR / "benchmark_results.json")
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = [r.__dict__ for r in results]
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
