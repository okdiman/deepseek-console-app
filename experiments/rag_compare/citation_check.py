"""
Day 24 — RAG Citation & Anti-Hallucination Verification

Runs test questions through the full RAG pipeline (embed → search → rerank →
citation formatting) and then calls the LLM with the citation-augmented system prompt.

For each answer checks:
  has_sources   — response contains at least one [N] reference
  has_quotes    — response contains at least one quoted text fragment
  quote_exact   — (check A) extracted quotes are substrings of retrieved chunks
  semantic_sim  — (check B) cosine similarity between response embedding and best chunk
  idk_triggered — response contains "I don't have enough information" or equivalent
  confidence    — context confidence level: empty / weak / uncertain / confident
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

_DATA_DIR = Path(__file__).parent / "data"

# ── Test questions ─────────────────────────────────────────────────────────────

TEST_QUESTIONS = [
    # Questions that should be in the corpus (attention / transformers)
    "How does the attention mechanism work in transformers?",
    "What is the difference between encoder and decoder in the transformer architecture?",
    "What is multi-head attention and why is it used?",
    "How does positional encoding work in transformer models?",
    "What is the feed-forward network inside a transformer block?",
    "How does BERT differ from GPT in terms of architecture?",
    "What is layer normalization and why is it important in transformers?",
    # Questions about the project itself
    "What is the RAG pipeline in this project and how does it work?",
    # Off-topic questions — should trigger IDK
    "What is the capital of Mars and who lives there?",
    "How to make the perfect pasta carbonara?",
]

_IDK_PATTERNS = re.compile(
    r"(i don'?t have enough information"
    r"|i cannot answer"
    r"|no relevant (context|information|documents)"
    r"|not (enough|sufficient) (context|information)"
    r"|unable to (find|answer)"
    r"|outside (the|my) (knowledge|context))",
    re.IGNORECASE,
)

_CITATION_PATTERN = re.compile(r"\[(\d+)\]")
_QUOTE_PATTERN = re.compile(r'"([^"]{15,})"')


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class CitationCheckResult:
    question: str
    confidence: str
    max_score: float
    chunk_count: int
    has_sources: bool
    has_quotes: bool
    quote_exact: bool
    semantic_sim: float
    semantic_match: bool
    idk_triggered: bool
    llm_response: str
    duration_s: float
    error: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    denom = na * nb
    return dot / denom if denom > 1e-10 else 0.0


def _check_quote_exact(response: str, chunks: List[Dict]) -> bool:
    """Check A: are any quoted fragments in the response verbatim substrings of chunks?"""
    quotes = _QUOTE_PATTERN.findall(response)
    if not quotes:
        return False
    chunk_texts = " ".join(c.get("text", "").lower() for c in chunks)
    return any(q.lower().strip() in chunk_texts for q in quotes)


async def _call_llm(
    system_prompt: str,
    question: str,
    api_key: str,
    api_url: str,
    model: str,
    timeout: int,
) -> tuple[str, float]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "max_tokens": 800,
        "temperature": 0.1,
    }
    t0 = perf_counter()
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(sock_read=timeout)
    ) as session:
        async with session.post(api_url, headers=headers, json=payload) as resp:
            body = await resp.text()
            duration = perf_counter() - t0
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {body[:200]}")
            data = json.loads(body)
            return (data["choices"][0]["message"]["content"] or "").strip(), duration


# ── Core check ─────────────────────────────────────────────────────────────────

async def check_question(
    question: str,
    embedder,
    config,
    api_key: str,
    api_url: str,
    model: str,
    timeout: int,
    top_k: int,
    pre_rerank_top_k: int,
    reranker_type: str,
    reranker_threshold: float,
    idk_threshold: float,
    weak_context_threshold: float,
    strategy: str,
    semantic_threshold: float,
) -> CitationCheckResult:
    from deepseek_chat.core.rag.citations import format_citation_block
    from deepseek_chat.core.rag.reranker import rerank_and_filter
    from deepseek_chat.core.rag.store import search_by_embedding

    t0 = perf_counter()
    try:
        vec = embedder.embed([question])[0]

        candidates = search_by_embedding(
            vec, top_k=pre_rerank_top_k, strategy=strategy, db_path=config.db_path
        )
        filter_result = rerank_and_filter(
            query=question,
            results=candidates,
            reranker_type=reranker_type,
            threshold=reranker_threshold,
            final_top_k=top_k,
        )
        results = filter_result.results

        block = format_citation_block(results, idk_threshold, weak_context_threshold)

        base_system = (
            "You are a helpful assistant that answers questions "
            "strictly based on provided documentation context."
        )
        response, duration = await _call_llm(
            base_system + block.formatted, question, api_key, api_url, model, timeout
        )

        # Check A: exact quote match
        quote_exact = _check_quote_exact(response, results)

        # Check B: cosine similarity between response embedding and best chunk
        semantic_sim = 0.0
        if results:
            resp_vec = embedder.embed([response[:1000]])[0]
            sims = [_cosine_sim(resp_vec, json.loads(c["embedding"])) for c in results]
            semantic_sim = max(sims) if sims else 0.0

        return CitationCheckResult(
            question=question,
            confidence=block.confidence.value,
            max_score=block.max_score,
            chunk_count=block.chunk_count,
            has_sources=bool(_CITATION_PATTERN.search(response)),
            has_quotes=bool(_QUOTE_PATTERN.search(response)),
            quote_exact=quote_exact,
            semantic_sim=round(semantic_sim, 3),
            semantic_match=semantic_sim >= semantic_threshold,
            idk_triggered=bool(_IDK_PATTERNS.search(response)),
            llm_response=response,
            duration_s=round(perf_counter() - t0, 2),
        )

    except Exception as exc:
        return CitationCheckResult(
            question=question,
            confidence="error",
            max_score=0.0,
            chunk_count=0,
            has_sources=False,
            has_quotes=False,
            quote_exact=False,
            semantic_sim=0.0,
            semantic_match=False,
            idk_triggered=False,
            llm_response="",
            duration_s=round(perf_counter() - t0, 2),
            error=str(exc),
        )


async def run_citation_check(
    top_k: int = 3,
    pre_rerank_top_k: int = 10,
    reranker_type: str = "threshold",
    reranker_threshold: float = 0.30,
    idk_threshold: float = 0.45,
    weak_context_threshold: float = 0.55,
    strategy: str = "structure",
    semantic_threshold: float = 0.60,
    verbose: bool = True,
) -> List[CitationCheckResult]:
    from deepseek_chat.core.rag.config import load_rag_config
    from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
    from deepseek_chat.core.rag.store import get_stats

    load_dotenv()
    provider = os.getenv("PROVIDER", "deepseek").lower()
    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        api_url = os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
        model = os.getenv("GROQ_API_MODEL", "moonshotai/kimi-k2-instruct")
        timeout = int(os.getenv("GROQ_API_TIMEOUT_SECONDS", "60"))
    else:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        api_url = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
        model = os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat")
        timeout = int(os.getenv("DEEPSEEK_API_TIMEOUT_SECONDS", "60"))

    if not api_key:
        raise RuntimeError(f"{provider.upper()}_API_KEY not set")

    config = load_rag_config()
    embedder = OllamaEmbeddingClient(config)

    if not embedder.health_check():
        raise RuntimeError("Ollama not reachable. Start with: ollama serve")

    stats = get_stats(config.db_path)
    if stats["total"] == 0:
        raise RuntimeError("RAG index is empty. Run: python3 experiments/rag_compare/cli.py index")

    if verbose:
        print(f"Index: {stats['total']} chunks | Provider: {provider} | Model: {model}")
        print(
            f"Thresholds: reranker={reranker_threshold} | "
            f"idk={idk_threshold} | weak={weak_context_threshold}"
        )
        print(f"Running {len(TEST_QUESTIONS)} questions...\n")

    results: List[CitationCheckResult] = []
    for i, q in enumerate(TEST_QUESTIONS, 1):
        if verbose:
            print(f"  [{i}/{len(TEST_QUESTIONS)}] {q[:65]}", end=" ... ", flush=True)
        r = await check_question(
            question=q,
            embedder=embedder,
            config=config,
            api_key=api_key,
            api_url=api_url,
            model=model,
            timeout=timeout,
            top_k=top_k,
            pre_rerank_top_k=pre_rerank_top_k,
            reranker_type=reranker_type,
            reranker_threshold=reranker_threshold,
            idk_threshold=idk_threshold,
            weak_context_threshold=weak_context_threshold,
            strategy=strategy,
            semantic_threshold=semantic_threshold,
        )
        results.append(r)
        if verbose:
            status = r.error if r.error else f"{r.confidence} | {r.duration_s}s"
            print(status)

    return results


# ── Report ─────────────────────────────────────────────────────────────────────

def _icon(v: bool) -> str:
    return "✅" if v else "❌"


def print_results(results: List[CitationCheckResult]) -> None:
    print("\n" + "=" * 92)
    print("RAG CITATION CHECK REPORT — Day 24")
    print("=" * 92)
    print(
        f"{'#':>2}  {'Confidence':<12} {'Score':>6} {'Src':>4} {'Quo':>4} "
        f"{'Exact':>6} {'Sem':>6} {'IDK':>4}  Question"
    )
    print("-" * 92)

    for i, r in enumerate(results, 1):
        if r.error:
            print(f"{i:>2}  ERROR: {r.error[:72]}")
            continue
        print(
            f"{i:>2}  {r.confidence:<12} {r.max_score:>6.3f} "
            f"{_icon(r.has_sources):>4} {_icon(r.has_quotes):>4} "
            f"{_icon(r.quote_exact):>6} {r.semantic_sim:>6.3f} "
            f"{_icon(r.idk_triggered):>4}  {r.question[:52]}"
        )

    ok = [r for r in results if not r.error]
    n = len(ok)
    if not n:
        return

    print("=" * 92)
    print(f"SUMMARY ({n} questions):")
    print(f"  has_sources:    {sum(r.has_sources for r in ok)}/{n}")
    print(f"  has_quotes:     {sum(r.has_quotes for r in ok)}/{n}")
    print(f"  quote_exact:    {sum(r.quote_exact for r in ok)}/{n}")
    print(f"  semantic_match: {sum(r.semantic_match for r in ok)}/{n}")
    idk_expected = [r for r in ok if r.confidence in ("empty", "weak")]
    if idk_expected:
        print(
            f"  idk_mode:       {sum(r.idk_triggered for r in idk_expected)}/{len(idk_expected)}"
            f" (of empty/weak context questions)"
        )
    print("=" * 92)

    print("\nFULL RESPONSES:")
    for i, r in enumerate(results, 1):
        print(f"\n{'─' * 72}")
        print(f"Q{i}: {r.question}")
        print(f"Confidence: {r.confidence} | max_score={r.max_score:.3f} | chunks={r.chunk_count}")
        if r.error:
            print(f"ERROR: {r.error}")
        else:
            print(r.llm_response)


def save_results(results: List[CitationCheckResult], path: Optional[str] = None) -> str:
    if path is None:
        path = str(_DATA_DIR / "citation_check_report.json")
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
