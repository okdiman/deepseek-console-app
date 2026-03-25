"""
Day 28 — Local LLM vs Cloud LLM RAG comparison.

Runs the same 10 RAG eval questions through:
  LOCAL : Ollama (OLLAMA_MODEL, default qwen2.5:7b) + local Ollama embeddings
  CLOUD : DeepSeek or Groq (read from .env)         + local Ollama embeddings

Retrieval is identical for both — only the generator LLM differs.
This isolates the comparison to generation quality, speed, and stability.

Metrics per question:
  - keyword_hits  — how many expected keywords appear in the answer
  - source_hit    — whether an expected source was retrieved
  - elapsed_s     — wall-clock seconds for the whole RAG+generate call
  - timed_out     — whether the call exceeded BENCHMARK_TIMEOUT

Summary:
  - keyword hit rate %
  - source accuracy %
  - avg / median response time
  - timeout count
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import statistics
import time
from asyncio import TimeoutError as AsyncTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv

# Allow running from repo root
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

BENCHMARK_TIMEOUT = 120.0   # seconds per question
_TEMPERATURE = 0.1          # low for reproducible results
_SYSTEM = (
    "You are a helpful assistant. "
    "Use the provided documentation context to answer the question accurately and concisely."
)


# ── Config builders ────────────────────────────────────────────────────────────

def _base_config_kwargs() -> dict:
    """Fields that are the same regardless of provider."""
    return dict(
        persist_context=False,
        context_path="",
        context_max_messages=40,
        compression_enabled=False,
        compression_threshold=10,
        compression_keep=4,
        optional_params=OptionalRequestParams(),
    )


def build_ollama_config() -> ClientConfig:
    """Build a ClientConfig that routes to local Ollama."""
    load_dotenv()
    base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    return ClientConfig(
        provider="ollama",
        api_key="ollama",
        api_url=f"{base_url}/v1/chat/completions",
        models_url=f"{base_url}/v1/models",
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
        max_tokens=int(os.getenv("OLLAMA_MAX_TOKENS", "4000")),
        read_timeout_seconds=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
        price_per_1k_prompt_usd=0.0,
        price_per_1k_completion_usd=0.0,
        **_base_config_kwargs(),
    )


def build_cloud_config() -> Optional[ClientConfig]:
    """
    Build a ClientConfig for the cloud provider available in .env.
    Checks DeepSeek first, then Groq.
    Returns None if no cloud credentials are found.
    """
    load_dotenv()

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        return ClientConfig(
            provider="deepseek",
            api_key=deepseek_key,
            api_url=os.getenv(
                "DEEPSEEK_API_URL",
                "https://api.deepseek.com/v1/chat/completions",
            ),
            models_url=os.getenv("DEEPSEEK_MODELS_URL", ""),
            model=os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat"),
            max_tokens=int(os.getenv("DEEPSEEK_API_MAX_TOKENS", "4000")),
            read_timeout_seconds=int(os.getenv("DEEPSEEK_API_TIMEOUT_SECONDS", "60")),
            price_per_1k_prompt_usd=float(
                os.getenv("DEEPSEEK_PRICE_PER_1K_PROMPT_USD", "0.00028")
            ),
            price_per_1k_completion_usd=float(
                os.getenv("DEEPSEEK_PRICE_PER_1K_COMPLETION_USD", "0.00042")
            ),
            **_base_config_kwargs(),
        )

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        return ClientConfig(
            provider="groq",
            api_key=groq_key,
            api_url=os.getenv(
                "GROQ_API_URL",
                "https://api.groq.com/openai/v1/chat/completions",
            ),
            models_url=os.getenv(
                "GROQ_MODELS_URL",
                "https://api.groq.com/openai/v1/models",
            ),
            model=os.getenv("GROQ_API_MODEL", "moonshotai/kimi-k2-instruct"),
            max_tokens=int(os.getenv("GROQ_API_MAX_TOKENS", "4000")),
            read_timeout_seconds=int(os.getenv("GROQ_API_TIMEOUT_SECONDS", "60")),
            price_per_1k_prompt_usd=float(
                os.getenv("GROQ_PRICE_PER_1K_PROMPT_USD", "0.0")
            ),
            price_per_1k_completion_usd=float(
                os.getenv("GROQ_PRICE_PER_1K_COMPLETION_USD", "0.0")
            ),
            **_base_config_kwargs(),
        )

    return None


# ── RAG + generate ─────────────────────────────────────────────────────────────

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


async def _run_rag_question(
    client: DeepSeekClient,
    question: str,
    embedder: OllamaEmbeddingClient,
    rag_config,
    top_k: int,
    pre_rerank_top_k: int,
    threshold: float,
    strategy: str,
) -> Tuple[str, List[str], float, bool]:
    """
    Run one RAG question through the given client.
    Returns (answer, retrieved_source_basenames, elapsed_s, timed_out).
    """
    t0 = time.perf_counter()
    timed_out = False

    vec = embedder.embed([question])[0]
    candidates = search_by_embedding(
        vec, top_k=pre_rerank_top_k, strategy=strategy, db_path=rag_config.db_path
    )
    fr = rerank_and_filter(
        query=question,
        results=candidates,
        reranker_type="threshold",
        threshold=threshold,
        final_top_k=top_k,
    )
    chunks = fr.results or candidates[:top_k]  # fallback if filter removed everything
    sources = [Path(r["source"]).name for r in chunks]

    system_prompt = _SYSTEM + _build_rag_block(chunks)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    tokens: list[str] = []

    async def _drain() -> None:
        async for chunk in client.stream_message(messages, temperature=_TEMPERATURE):
            if not chunk.startswith('{"__type__"'):
                tokens.append(chunk)

    try:
        await asyncio.wait_for(_drain(), timeout=BENCHMARK_TIMEOUT)
    except AsyncTimeoutError:
        tokens.append(f"[TIMEOUT after {BENCHMARK_TIMEOUT:.0f}s]")
        timed_out = True

    elapsed = round(time.perf_counter() - t0, 2)
    return "".join(tokens), sources, elapsed, timed_out


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class QuestionResult:
    question: str
    expected_keywords: List[str]
    expected_sources: List[str]
    local_answer: str
    local_sources: List[str]
    local_elapsed: float
    local_timed_out: bool
    local_keyword_hits: int
    local_source_hit: bool
    cloud_answer: str
    cloud_sources: List[str]
    cloud_elapsed: float
    cloud_timed_out: bool
    cloud_keyword_hits: int
    cloud_source_hit: bool


@dataclass
class ComparisonReport:
    local_model: str
    cloud_model: str
    cloud_provider: str
    strategy: str
    top_k: int
    results: List[QuestionResult]

    # summary fields (filled by build_summary)
    local_kw_total: int = 0
    local_kw_possible: int = 0
    local_src_hits: int = 0
    local_timeouts: int = 0
    local_avg_elapsed: float = 0.0
    local_median_elapsed: float = 0.0

    cloud_kw_total: int = 0
    cloud_kw_possible: int = 0
    cloud_src_hits: int = 0
    cloud_timeouts: int = 0
    cloud_avg_elapsed: float = 0.0
    cloud_median_elapsed: float = 0.0


def _kw_hits(answer: str, keywords: List[str]) -> int:
    lower = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in lower)


def _src_hit(retrieved: List[str], expected: List[str]) -> bool:
    r_lower = {s.lower() for s in retrieved}
    return any(e.lower() in r_lower for e in expected)


def _build_summary(report: ComparisonReport) -> ComparisonReport:
    rs = report.results
    possible = sum(len(r.expected_keywords) for r in rs)
    local_elapsed = [r.local_elapsed for r in rs if not r.local_timed_out]
    cloud_elapsed = [r.cloud_elapsed for r in rs if not r.cloud_timed_out]
    return dataclasses.replace(
        report,
        local_kw_total=sum(r.local_keyword_hits for r in rs),
        local_kw_possible=possible,
        local_src_hits=sum(1 for r in rs if r.local_source_hit),
        local_timeouts=sum(1 for r in rs if r.local_timed_out),
        local_avg_elapsed=round(statistics.mean(local_elapsed), 2) if local_elapsed else 0,
        local_median_elapsed=round(statistics.median(local_elapsed), 2) if local_elapsed else 0,
        cloud_kw_total=sum(r.cloud_keyword_hits for r in rs),
        cloud_kw_possible=possible,
        cloud_src_hits=sum(1 for r in rs if r.cloud_source_hit),
        cloud_timeouts=sum(1 for r in rs if r.cloud_timed_out),
        cloud_avg_elapsed=round(statistics.mean(cloud_elapsed), 2) if cloud_elapsed else 0,
        cloud_median_elapsed=round(statistics.median(cloud_elapsed), 2) if cloud_elapsed else 0,
    )


# ── Runner ─────────────────────────────────────────────────────────────────────

async def run_comparison(
    eval_cases: Optional[List[EvalCase]] = None,
    top_k: int = 3,
    pre_rerank_top_k: int = 10,
    threshold: float = 0.30,
    strategy: str = "structure",
    verbose: bool = True,
) -> ComparisonReport:
    if eval_cases is None:
        eval_cases = EVAL_SET

    rag_config = load_rag_config()
    embedder = OllamaEmbeddingClient(rag_config)

    ollama_cfg = build_ollama_config()
    cloud_cfg = build_cloud_config()

    if cloud_cfg is None:
        raise RuntimeError(
            "No cloud provider credentials found. "
            "Set DEEPSEEK_API_KEY or GROQ_API_KEY in .env"
        )

    local_client = DeepSeekClient(ollama_cfg)
    cloud_client = DeepSeekClient(cloud_cfg)

    if verbose:
        print(f"\nLOCAL : {ollama_cfg.model} ({ollama_cfg.provider})")
        print(f"CLOUD : {cloud_cfg.model} ({cloud_cfg.provider})")
        print(f"RAG   : strategy={strategy}  top_k={top_k}  threshold={threshold}")
        print(f"Questions: {len(eval_cases)}\n")

    results: List[QuestionResult] = []

    for i, case in enumerate(eval_cases, 1):
        if verbose:
            short_q = case.question[:60]
            print(f"[{i:2}/{len(eval_cases)}] {short_q}")
            print("        local  ... ", end="", flush=True)

        local_ans, local_src, local_t, local_to = await _run_rag_question(
            local_client, case.question, embedder, rag_config,
            top_k, pre_rerank_top_k, threshold, strategy,
        )
        if verbose:
            to_mark = " TIMEOUT" if local_to else ""
            print(f"{local_t:.1f}s{to_mark}  |  cloud  ... ", end="", flush=True)

        cloud_ans, cloud_src, cloud_t, cloud_to = await _run_rag_question(
            cloud_client, case.question, embedder, rag_config,
            top_k, pre_rerank_top_k, threshold, strategy,
        )
        if verbose:
            to_mark = " TIMEOUT" if cloud_to else ""
            print(f"{cloud_t:.1f}s{to_mark}")

        results.append(QuestionResult(
            question=case.question,
            expected_keywords=case.expected_keywords,
            expected_sources=case.expected_sources,
            local_answer=local_ans,
            local_sources=local_src,
            local_elapsed=local_t,
            local_timed_out=local_to,
            local_keyword_hits=_kw_hits(local_ans, case.expected_keywords),
            local_source_hit=_src_hit(local_src, case.expected_sources),
            cloud_answer=cloud_ans,
            cloud_sources=cloud_src,
            cloud_elapsed=cloud_t,
            cloud_timed_out=cloud_to,
            cloud_keyword_hits=_kw_hits(cloud_ans, case.expected_keywords),
            cloud_source_hit=_src_hit(cloud_src, case.expected_sources),
        ))

    report = ComparisonReport(
        local_model=ollama_cfg.model,
        cloud_model=cloud_cfg.model,
        cloud_provider=cloud_cfg.provider,
        strategy=strategy,
        top_k=top_k,
        results=results,
    )
    return _build_summary(report)


# ── Output ─────────────────────────────────────────────────────────────────────

def print_report(report: ComparisonReport) -> None:
    sep = "=" * 76
    n = len(report.results)
    possible = report.local_kw_possible

    print(f"\n{sep}")
    print("  DAY 28 — LOCAL LLM vs CLOUD LLM  (RAG-grounded answers)")
    print(sep)
    print(f"  Local : {report.local_model}")
    print(f"  Cloud : {report.cloud_model}  [{report.cloud_provider}]")
    print(f"  RAG   : strategy={report.strategy}  top_k={report.top_k}")
    print(sep)

    # Per-question table
    print(f"\n  {'#':<3} {'Question (truncated)':<44} {'LOCAL':>7} {'CLOUD':>7}")
    print(f"  {'-'*3} {'-'*44} {'-'*7} {'-'*7}")

    for i, r in enumerate(report.results, 1):
        n_kw = len(r.expected_keywords)
        l_pct = round(100 * r.local_keyword_hits / n_kw) if n_kw else 0
        c_pct = round(100 * r.cloud_keyword_hits / n_kw) if n_kw else 0
        winner = "←L" if r.local_keyword_hits > r.cloud_keyword_hits else (
                 "←C" if r.cloud_keyword_hits > r.local_keyword_hits else "TIE")
        q_short = r.question[:44]
        print(f"  {i:<3} {q_short:<44} {l_pct:>5}%  {c_pct:>5}%  {winner}")

    print(f"\n{sep}")
    print(f"  {'Metric':<30} {'LOCAL':>12} {'CLOUD':>12}  {'Winner':>7}")
    print(f"  {'-'*65}")

    def _row(label: str, lv, cv, fmt: str = "", higher_is_better: bool = True) -> None:
        if fmt:
            ls, cs = f"{lv:{fmt}}", f"{cv:{fmt}}"
        else:
            ls, cs = str(lv), str(cv)
        if higher_is_better:
            winner = "LOCAL" if lv > cv else ("CLOUD" if cv > lv else "tie")
        else:
            winner = "LOCAL" if lv < cv else ("CLOUD" if cv < lv else "tie")
        print(f"  {label:<30} {ls:>12} {cs:>12}  {winner:>7}")

    l_kw_pct = round(100 * report.local_kw_total / possible) if possible else 0
    c_kw_pct = round(100 * report.cloud_kw_total / possible) if possible else 0
    _row("Keyword hits", f"{report.local_kw_total}/{possible} ({l_kw_pct}%)",
         f"{report.cloud_kw_total}/{possible} ({c_kw_pct}%)",
         higher_is_better=True)

    l_src_pct = round(100 * report.local_src_hits / n) if n else 0
    c_src_pct = round(100 * report.cloud_src_hits / n) if n else 0
    _row("Source accuracy",
         f"{report.local_src_hits}/{n} ({l_src_pct}%)",
         f"{report.cloud_src_hits}/{n} ({c_src_pct}%)",
         higher_is_better=True)

    _row("Avg response time", f"{report.local_avg_elapsed:.1f}s",
         f"{report.cloud_avg_elapsed:.1f}s", higher_is_better=False)
    _row("Median response time", f"{report.local_median_elapsed:.1f}s",
         f"{report.cloud_median_elapsed:.1f}s", higher_is_better=False)
    _row("Timeouts", report.local_timeouts, report.cloud_timeouts,
         higher_is_better=False)

    print(sep)

    # Answer previews for first 3 questions
    print("\n  ANSWER PREVIEWS (first 3 questions)\n")
    for r in report.results[:3]:
        print(f"  Q: {r.question}")
        lp = r.local_answer[:160].replace("\n", " ")
        cp = r.cloud_answer[:160].replace("\n", " ")
        print(f"  LOCAL » {lp}...")
        print(f"  CLOUD » {cp}...")
        print()

    print(sep)


def save_report(report: ComparisonReport, path: Optional[str] = None) -> str:
    if path is None:
        path = str(_DATA_DIR / "local_vs_cloud_report.json")
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _serialize_result(r: QuestionResult) -> dict:
        return dataclasses.asdict(r)

    data = {
        "local_model": report.local_model,
        "cloud_model": report.cloud_model,
        "cloud_provider": report.cloud_provider,
        "strategy": report.strategy,
        "top_k": report.top_k,
        "summary": {
            "local_keyword_hits": report.local_kw_total,
            "local_keyword_possible": report.local_kw_possible,
            "local_kw_hit_rate_pct": (
                round(100 * report.local_kw_total / report.local_kw_possible)
                if report.local_kw_possible else 0
            ),
            "local_source_accuracy_pct": (
                round(100 * report.local_src_hits / len(report.results))
                if report.results else 0
            ),
            "local_avg_elapsed_s": report.local_avg_elapsed,
            "local_median_elapsed_s": report.local_median_elapsed,
            "local_timeouts": report.local_timeouts,
            "cloud_keyword_hits": report.cloud_kw_total,
            "cloud_keyword_possible": report.cloud_kw_possible,
            "cloud_kw_hit_rate_pct": (
                round(100 * report.cloud_kw_total / report.cloud_kw_possible)
                if report.cloud_kw_possible else 0
            ),
            "cloud_source_accuracy_pct": (
                round(100 * report.cloud_src_hits / len(report.results))
                if report.results else 0
            ),
            "cloud_avg_elapsed_s": report.cloud_avg_elapsed,
            "cloud_median_elapsed_s": report.cloud_median_elapsed,
            "cloud_timeouts": report.cloud_timeouts,
        },
        "results": [_serialize_result(r) for r in report.results],
    }
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
