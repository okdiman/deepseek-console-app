"""
Day 29 — Local LLM Optimization

Tests multiple optimization profiles on the local Ollama model.
Each profile varies temperature, max_tokens, context window (num_ctx), and the
system prompt (generic vs. RAG-task-specific).

Profiles:
  baseline      — default params (temp=1.0, max_tokens=4000, num_ctx=default, generic prompt)
  fast          — temp=0.1, max_tokens=512,  num_ctx=2048, task-specific prompt
  quality       — temp=0.1, max_tokens=1024, num_ctx=4096, task-specific prompt
  quality_large — temp=0.1, max_tokens=1024, num_ctx=8192, task-specific prompt

Metrics per profile (aggregated over 10 eval questions):
  - keyword hit rate %  (expected keywords found in answer)
  - source accuracy %   (expected source file was retrieved)
  - avg / median latency (seconds)
  - avg tokens/sec      (from Ollama usage stats when available)
  - timeouts

Usage:
  python3 experiments/rag_compare/optimize.py
  # or via CLI:
  python3 experiments/rag_compare/cli.py optimize [--profiles baseline,fast] [--save]
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import statistics
import time
from asyncio import TimeoutError as AsyncTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from deepseek_chat.core.client import DeepSeekClient
from deepseek_chat.core.config import ClientConfig, OptionalRequestParams
from deepseek_chat.core.rag.config import load_rag_config
from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
from deepseek_chat.core.rag.reranker import rerank_and_filter
from deepseek_chat.core.rag.store import search_by_embedding
from experiments.rag_compare.eval_set import EVAL_SET, EvalCase

_DATA_DIR = Path(__file__).parent / "data"
BENCHMARK_TIMEOUT = 120.0


# ── Prompt templates ──────────────────────────────────────────────────────────

GENERIC_SYSTEM = (
    "You are a helpful assistant. "
    "Use the provided documentation context to answer the question accurately and concisely."
)

RAG_OPTIMIZED_SYSTEM = (
    "You are a precise documentation assistant. "
    "You will receive numbered source excerpts tagged [1], [2], … above the question.\n\n"
    "Rules:\n"
    "1. Base your answer ONLY on the provided excerpts.\n"
    "2. Cite sources inline using [N] notation (e.g. 'Attention uses softmax [1].').\n"
    "3. Be concise — 3–6 sentences maximum. No preamble, no padding.\n"
    "4. If the excerpts do not contain the answer, reply: "
    "'The provided sources do not cover this topic.'\n"
    "5. Never invent information absent from the excerpts."
)


# ── Optimization profiles ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class OptimizationProfile:
    name: str
    description: str
    temperature: float
    max_tokens: int
    num_ctx: Optional[int]   # None → Ollama model default
    system_prompt: str


ALL_PROFILES: List[OptimizationProfile] = [
    OptimizationProfile(
        name="baseline",
        description="Default: temp=1.0, max_tokens=4000, num_ctx=default, generic prompt",
        temperature=1.0,
        max_tokens=4000,
        num_ctx=None,
        system_prompt=GENERIC_SYSTEM,
    ),
    OptimizationProfile(
        name="fast",
        description="Speed: temp=0.1, max_tokens=512, num_ctx=2048, task prompt",
        temperature=0.1,
        max_tokens=512,
        num_ctx=2048,
        system_prompt=RAG_OPTIMIZED_SYSTEM,
    ),
    OptimizationProfile(
        name="quality",
        description="Balanced: temp=0.1, max_tokens=1024, num_ctx=4096, task prompt",
        temperature=0.1,
        max_tokens=1024,
        num_ctx=4096,
        system_prompt=RAG_OPTIMIZED_SYSTEM,
    ),
    OptimizationProfile(
        name="quality_large",
        description="Large ctx: temp=0.1, max_tokens=1024, num_ctx=8192, task prompt",
        temperature=0.1,
        max_tokens=1024,
        num_ctx=8192,
        system_prompt=RAG_OPTIMIZED_SYSTEM,
    ),
]

PROFILE_MAP = {p.name: p for p in ALL_PROFILES}


# ── Config builder ────────────────────────────────────────────────────────────

def _build_config(profile: OptimizationProfile) -> ClientConfig:
    load_dotenv()
    base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    return ClientConfig(
        provider="ollama",
        api_key="ollama",
        api_url=f"{base_url}/v1/chat/completions",
        models_url=f"{base_url}/v1/models",
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
        max_tokens=profile.max_tokens,
        read_timeout_seconds=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
        price_per_1k_prompt_usd=0.0,
        price_per_1k_completion_usd=0.0,
        persist_context=False,
        context_path="",
        context_max_messages=40,
        compression_enabled=False,
        compression_threshold=10,
        compression_keep=4,
        ollama_num_ctx=profile.num_ctx,
    )


# ── RAG helpers ───────────────────────────────────────────────────────────────

def _build_rag_block(results: list) -> str:
    lines = ["", "---", "Relevant documentation:"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        section = r.get("section", "")
        label = f"{title} › {section}" if section else title
        text = r["text"].strip()[:400].replace("\n", " ")
        lines.append(f"\n[{i}] {label}")
        lines.append(f'"{text}"')
    lines.append("---")
    return "\n".join(lines)


def _kw_hits(answer: str, keywords: List[str]) -> int:
    lower = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in lower)


def _src_hit(retrieved: List[str], expected: List[str]) -> bool:
    r_lower = {s.lower() for s in retrieved}
    return any(e.lower() in r_lower for e in expected)


# ── Per-question runner ───────────────────────────────────────────────────────

async def _run_question(
    client: DeepSeekClient,
    profile: OptimizationProfile,
    case: EvalCase,
    embedder: OllamaEmbeddingClient,
    rag_config,
    top_k: int,
    pre_rerank_top_k: int,
    threshold: float,
    strategy: str,
) -> "QuestionResult":
    t0 = time.perf_counter()
    timed_out = False

    vec = embedder.embed([case.question])[0]
    candidates = search_by_embedding(
        vec, top_k=pre_rerank_top_k, strategy=strategy, db_path=rag_config.db_path
    )
    fr = rerank_and_filter(
        query=case.question,
        results=candidates,
        reranker_type="threshold",
        threshold=threshold,
        final_top_k=top_k,
    )
    chunks = fr.results or candidates[:top_k]
    sources = [Path(r["source"]).name for r in chunks]

    system_prompt = profile.system_prompt + _build_rag_block(chunks)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": case.question},
    ]

    tokens: list[str] = []

    async def _drain() -> None:
        async for chunk in client.stream_message(messages, temperature=profile.temperature):
            if not chunk.startswith('{"__type__"'):
                tokens.append(chunk)

    try:
        await asyncio.wait_for(_drain(), timeout=BENCHMARK_TIMEOUT)
    except AsyncTimeoutError:
        tokens.append(f"[TIMEOUT after {BENCHMARK_TIMEOUT:.0f}s]")
        timed_out = True

    elapsed = round(time.perf_counter() - t0, 2)
    answer = "".join(tokens)

    metrics = client.last_metrics()
    completion_tokens = metrics.completion_tokens if metrics else None
    tokens_per_sec: Optional[float] = None
    if completion_tokens and elapsed > 0:
        tokens_per_sec = round(completion_tokens / elapsed, 1)

    return QuestionResult(
        profile_name=profile.name,
        question=case.question,
        answer=answer,
        sources=sources,
        keyword_hits=_kw_hits(answer, case.expected_keywords),
        keyword_total=len(case.expected_keywords),
        source_hit=_src_hit(sources, case.expected_sources),
        elapsed_s=elapsed,
        timed_out=timed_out,
        completion_tokens=completion_tokens,
        tokens_per_sec=tokens_per_sec,
    )


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class QuestionResult:
    profile_name: str
    question: str
    answer: str
    sources: List[str]
    keyword_hits: int
    keyword_total: int
    source_hit: bool
    elapsed_s: float
    timed_out: bool
    completion_tokens: Optional[int]
    tokens_per_sec: Optional[float]


@dataclass
class ProfileSummary:
    name: str
    description: str
    kw_hits: int
    kw_possible: int
    src_hits: int
    n_questions: int
    avg_elapsed: float
    median_elapsed: float
    timeouts: int
    avg_tokens_per_sec: Optional[float]

    @property
    def kw_pct(self) -> int:
        return round(100 * self.kw_hits / self.kw_possible) if self.kw_possible else 0

    @property
    def src_pct(self) -> int:
        return round(100 * self.src_hits / self.n_questions) if self.n_questions else 0


@dataclass
class OptimizationReport:
    model: str
    strategy: str
    top_k: int
    profiles_tested: List[str]
    summaries: List[ProfileSummary]
    results: List[QuestionResult]


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_optimization(
    profiles: Optional[List[OptimizationProfile]] = None,
    eval_cases: Optional[List[EvalCase]] = None,
    top_k: int = 3,
    pre_rerank_top_k: int = 10,
    threshold: float = 0.30,
    strategy: str = "structure",
    verbose: bool = True,
) -> OptimizationReport:
    if profiles is None:
        profiles = ALL_PROFILES
    if eval_cases is None:
        eval_cases = EVAL_SET

    rag_config = load_rag_config()
    embedder = OllamaEmbeddingClient(rag_config)

    load_dotenv()
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    if verbose:
        print(f"\nModel  : {model}")
        print(f"RAG    : strategy={strategy}  top_k={top_k}  threshold={threshold}")
        print(f"Profiles: {[p.name for p in profiles]}")
        print(f"Questions: {len(eval_cases)}\n")

    all_results: List[QuestionResult] = []

    for profile in profiles:
        if verbose:
            print(f"── Profile: {profile.name}  ({profile.description})")

        client = DeepSeekClient(_build_config(profile))

        for i, case in enumerate(eval_cases, 1):
            if verbose:
                short_q = case.question[:55]
                print(f"  [{i:2}/{len(eval_cases)}] {short_q} ... ", end="", flush=True)

            result = await _run_question(
                client, profile, case, embedder, rag_config,
                top_k, pre_rerank_top_k, threshold, strategy,
            )
            all_results.append(result)

            if verbose:
                to_mark = " TIMEOUT" if result.timed_out else ""
                tps = f"  {result.tokens_per_sec:.0f} tok/s" if result.tokens_per_sec else ""
                print(f"{result.elapsed_s:.1f}s{to_mark}{tps}")

        if verbose:
            print()

    # Build summaries
    summaries: List[ProfileSummary] = []
    for profile in profiles:
        rs = [r for r in all_results if r.profile_name == profile.name]
        kw_hits = sum(r.keyword_hits for r in rs)
        kw_possible = sum(r.keyword_total for r in rs)
        src_hits = sum(1 for r in rs if r.source_hit)
        elapsed_non_to = [r.elapsed_s for r in rs if not r.timed_out]
        tps_values = [r.tokens_per_sec for r in rs if r.tokens_per_sec is not None]
        summaries.append(ProfileSummary(
            name=profile.name,
            description=profile.description,
            kw_hits=kw_hits,
            kw_possible=kw_possible,
            src_hits=src_hits,
            n_questions=len(rs),
            avg_elapsed=round(statistics.mean(elapsed_non_to), 2) if elapsed_non_to else 0.0,
            median_elapsed=round(statistics.median(elapsed_non_to), 2) if elapsed_non_to else 0.0,
            timeouts=sum(1 for r in rs if r.timed_out),
            avg_tokens_per_sec=round(statistics.mean(tps_values), 1) if tps_values else None,
        ))

    return OptimizationReport(
        model=model,
        strategy=strategy,
        top_k=top_k,
        profiles_tested=[p.name for p in profiles],
        summaries=summaries,
        results=all_results,
    )


# ── Output ────────────────────────────────────────────────────────────────────

def print_report(report: OptimizationReport) -> None:
    sep = "=" * 80
    print(f"\n{sep}")
    print("  DAY 29 — LOCAL LLM OPTIMIZATION")
    print(sep)
    print(f"  Model    : {report.model}")
    print(f"  RAG      : strategy={report.strategy}  top_k={report.top_k}")
    print(sep)

    # Summary table
    hdr = f"  {'Profile':<16} {'KW hit%':>8} {'Src%':>6} {'Avg s':>7} {'Med s':>7} {'tok/s':>7} {'TO':>4}"
    print(f"\n{hdr}")
    print(f"  {'-'*16} {'-'*8} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*4}")
    for s in report.summaries:
        tps = f"{s.avg_tokens_per_sec:.0f}" if s.avg_tokens_per_sec is not None else "  n/a"
        print(
            f"  {s.name:<16} {s.kw_pct:>7}% {s.src_pct:>5}% "
            f"{s.avg_elapsed:>7.1f} {s.median_elapsed:>7.1f} {tps:>7} {s.timeouts:>4}"
        )

    # Per-question keyword table (first profile vs best)
    if len(report.summaries) >= 2:
        base_name = report.summaries[0].name
        best = max(report.summaries, key=lambda s: s.kw_pct)
        best_name = best.name

        print(f"\n{sep}")
        print(f"  Per-question keyword hits  [{base_name}] vs [{best_name}]")
        print(f"  {'#':<3} {'Question (truncated)':<46} {base_name:>10} {best_name:>14}")
        print(f"  {'-'*3} {'-'*46} {'-'*10} {'-'*14}")

        base_rs = {r.question: r for r in report.results if r.profile_name == base_name}
        best_rs = {r.question: r for r in report.results if r.profile_name == best_name}

        for i, (q, br) in enumerate(base_rs.items(), 1):
            bestr = best_rs.get(q)
            b_pct = round(100 * br.keyword_hits / br.keyword_total) if br.keyword_total else 0
            best_pct = round(100 * bestr.keyword_hits / bestr.keyword_total) if bestr and bestr.keyword_total else 0
            delta = best_pct - b_pct
            delta_str = f"+{delta}%" if delta > 0 else (f"{delta}%" if delta < 0 else "=")
            print(f"  {i:<3} {q[:46]:<46} {b_pct:>8}% {best_pct:>12}% {delta_str:>5}")

    # Answer previews for 2 questions
    print(f"\n{sep}")
    print("  ANSWER PREVIEWS — Q1 across all profiles\n")
    q1 = EVAL_SET[0].question if EVAL_SET else None
    if q1:
        print(f"  Q: {q1}\n")
        for s in report.summaries:
            rs = [r for r in report.results if r.profile_name == s.name and r.question == q1]
            if rs:
                preview = rs[0].answer[:200].replace("\n", " ")
                print(f"  [{s.name}]")
                print(f"  {preview}...\n")

    print(sep)


def save_report(report: OptimizationReport, path: Optional[str] = None) -> str:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        path = str(_DATA_DIR / "day29_optimization_report.json")

    data = {
        "model": report.model,
        "strategy": report.strategy,
        "top_k": report.top_k,
        "profiles_tested": report.profiles_tested,
        "summaries": [dataclasses.asdict(s) for s in report.summaries],
        "results": [dataclasses.asdict(r) for r in report.results],
    }
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(report: OptimizationReport, path: Optional[str] = None) -> str:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        path = str(_DATA_DIR / "day29_optimization_report.md")

    lines = [
        "# Day 29 — Local LLM Optimization Report",
        "",
        f"**Model:** `{report.model}`  ",
        f"**RAG:** strategy={report.strategy}, top_k={report.top_k}",
        "",
        "## Summary",
        "",
        "| Profile | KW Hit % | Src % | Avg (s) | Median (s) | tok/s | Timeouts |",
        "|---------|----------|-------|---------|------------|-------|----------|",
    ]
    for s in report.summaries:
        tps = f"{s.avg_tokens_per_sec:.0f}" if s.avg_tokens_per_sec is not None else "n/a"
        lines.append(
            f"| `{s.name}` | {s.kw_pct}% | {s.src_pct}% | "
            f"{s.avg_elapsed:.1f} | {s.median_elapsed:.1f} | {tps} | {s.timeouts} |"
        )

    lines += [
        "",
        "## Profile Descriptions",
        "",
    ]
    for s in report.summaries:
        lines.append(f"- **`{s.name}`**: {s.description}")

    lines += [
        "",
        "## Per-question Results",
        "",
    ]
    for s in report.summaries:
        rs = [r for r in report.results if r.profile_name == s.name]
        lines += [
            f"### Profile: `{s.name}`",
            "",
            "| # | Question | KW hits | Source | Time (s) | tok/s |",
            "|---|----------|---------|--------|----------|-------|",
        ]
        for i, r in enumerate(rs, 1):
            kw_str = f"{r.keyword_hits}/{r.keyword_total}"
            src_str = "✓" if r.source_hit else "✗"
            tps_str = f"{r.tokens_per_sec:.0f}" if r.tokens_per_sec else "n/a"
            q_short = r.question[:50]
            lines.append(f"| {i} | {q_short} | {kw_str} | {src_str} | {r.elapsed_s:.1f} | {tps_str} |")
        lines.append("")

    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return path


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    report = asyncio.run(run_optimization(verbose=True))
    print_report(report)
    json_path = save_report(report)
    md_path = save_markdown_report(report)
    print(f"\nJSON report : {json_path}")
    print(f"MD report   : {md_path}")
