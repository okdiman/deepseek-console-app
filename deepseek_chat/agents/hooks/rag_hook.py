"""
RagHook — injects relevant document chunks into the system prompt before each LLM call.

Pipeline:
  1. (optional) Rewrite the user query via LLM for better retrieval
  2. Embed the (possibly rewritten) query via Ollama
  3. Fetch pre_rerank_top_k candidates from the local index
  4. Rerank / filter to final top_k chunks
  5. Format citation block based on context confidence level
  6. Append the citation block to the system prompt

Context confidence levels (Day 24):
  empty:     no chunks → must say "I don't know"
  weak:      max_score < RAG_IDK_THRESHOLD → must say "I don't know"
  uncertain: max_score < RAG_WEAK_CONTEXT_THRESHOLD → answer with caveat
  confident: max_score >= RAG_WEAK_CONTEXT_THRESHOLD → full citation required

Gracefully disabled when:
  - RAG_ENABLED=false (env var)
  - Ollama is not reachable
  - Index is empty (no chunks indexed yet)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Dict, List

from .base import AgentHook

if TYPE_CHECKING:
    from ..base_agent import BaseAgent

logger = logging.getLogger(__name__)

_RAG_ENABLED = os.getenv("RAG_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
_TOP_K = int(os.getenv("RAG_TOP_K", "3"))
_STRATEGY = os.getenv("RAG_SEARCH_STRATEGY", "structure")
_PRE_RERANK_TOP_K = int(os.getenv("RAG_PRE_RERANK_TOP_K", "10"))
_RERANKER_TYPE = os.getenv("RAG_RERANKER_TYPE", "threshold")
_RERANKER_THRESHOLD = float(os.getenv("RAG_RERANKER_THRESHOLD", "0.30"))
_QUERY_REWRITE_ENABLED = (
    os.getenv("RAG_QUERY_REWRITE_ENABLED", "false").strip().lower()
    not in {"0", "false", "no", "off"}
)
_CITATIONS_ENABLED = (
    os.getenv("RAG_CITATIONS_ENABLED", "true").strip().lower()
    not in {"0", "false", "no", "off"}
)
_IDK_THRESHOLD = float(os.getenv("RAG_IDK_THRESHOLD", "0.45"))
_WEAK_CONTEXT_THRESHOLD = float(os.getenv("RAG_WEAK_CONTEXT_THRESHOLD", "0.55"))


class RagHook(AgentHook):
    """
    Retrieval-Augmented Generation hook.

    On every before_stream call:
      1. Optionally rewrites the user query via LLM (RAG_QUERY_REWRITE_ENABLED)
      2. Embeds the query via Ollama (nomic-embed-text)
      3. Fetches RAG_PRE_RERANK_TOP_K candidates from the SQLite index
      4. Filters/reranks to RAG_TOP_K chunks (RAG_RERANKER_TYPE + RAG_RERANKER_THRESHOLD)
      5. Appends surviving chunks to the system_prompt

    If Ollama is unreachable or the index is empty, the hook silently
    returns the unchanged system_prompt — the agent continues normally.
    """

    def __init__(self) -> None:
        self._ready: bool | None = None  # None = not checked yet
        self.last_chunks: list = []  # last retrieved chunks; readable by the CLI for display

    def _check_ready(self) -> bool:
        """Lazy check: is Ollama running and index non-empty?"""
        if not _RAG_ENABLED:
            return False
        try:
            from deepseek_chat.core.rag.config import load_rag_config
            from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
            from deepseek_chat.core.rag.store import get_stats

            config = load_rag_config()
            stats = get_stats(config.db_path)
            if stats["total"] == 0:
                logger.debug("RagHook: index is empty, skipping")
                return False

            embedder = OllamaEmbeddingClient(config)
            if not embedder.health_check():
                logger.warning("RagHook: Ollama not reachable, RAG disabled")
                return False

            return True
        except Exception as exc:
            logger.warning("RagHook: init check failed: %s", exc)
            return False

    async def before_stream(
        self,
        agent: "BaseAgent",
        user_input: str,
        system_prompt: str,
        history: List[Dict[str, str]],
    ) -> str:
        if not _RAG_ENABLED:
            return system_prompt

        # Lazy-initialize readiness check (once per app lifetime)
        if self._ready is None:
            self._ready = self._check_ready()

        if not self._ready:
            return system_prompt

        try:
            from deepseek_chat.core.rag.config import load_rag_config
            from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
            from deepseek_chat.core.rag.query_rewriter import QueryRewriter
            from deepseek_chat.core.rag.reranker import rerank_and_filter
            from deepseek_chat.core.rag.store import search_by_embedding

            config = load_rag_config()

            # Step 1: enrich query with dialogue task goal (if available)
            query = user_input
            try:
                from deepseek_chat.core.dialogue_task import DialogueTask
                task = DialogueTask.load()
                if task.goal and len(user_input.split()) <= 12:
                    # Short follow-up questions benefit most from goal context
                    query = f"{task.goal}: {user_input}"
                    logger.debug("RagHook: enriched query with goal: %r", query[:80])
            except Exception:
                pass

            # Step 1b: optionally rewrite query via LLM
            if _QUERY_REWRITE_ENABLED:
                query = await QueryRewriter(agent._client).rewrite(query)

            # Step 2: embed
            embedder = OllamaEmbeddingClient(config)
            vec = embedder.embed([query])[0]

            # Step 3: fetch more candidates than needed (pre-rerank pool)
            pre_k = max(_PRE_RERANK_TOP_K, _TOP_K)
            candidates = search_by_embedding(
                vec,
                top_k=pre_k,
                strategy=_STRATEGY,
                db_path=config.db_path,
            )

            # Step 4: rerank / filter
            filter_result = rerank_and_filter(
                query=query,
                results=candidates,
                reranker_type=_RERANKER_TYPE,
                threshold=_RERANKER_THRESHOLD,
                final_top_k=_TOP_K,
            )
            results = filter_result.results
            self.last_chunks = results  # expose for display in CLI

            logger.debug(
                "RagHook: %d/%d chunks passed filter (threshold=%.2f, type=%s)",
                filter_result.post_filter_count,
                filter_result.pre_filter_count,
                _RERANKER_THRESHOLD,
                _RERANKER_TYPE,
            )

            # Step 5: format citation block (with confidence-based instructions)
            if _CITATIONS_ENABLED:
                from deepseek_chat.core.rag.citations import format_citation_block
                block = format_citation_block(results, _IDK_THRESHOLD, _WEAK_CONTEXT_THRESHOLD)
                logger.debug(
                    "RagHook: confidence=%s max_score=%.3f chunks=%d",
                    block.confidence,
                    block.max_score,
                    block.chunk_count,
                )
                return system_prompt + block.formatted
            else:
                if not results:
                    return system_prompt
                return system_prompt + _format_rag_block(results)

        except Exception as exc:
            logger.warning("RagHook: search failed: %s", exc)
            # Re-check readiness next time (Ollama may have restarted)
            self._ready = None
            return system_prompt

    async def after_stream(self, agent: "BaseAgent", full_response: str) -> None:
        pass


def _format_rag_block(results: list) -> str:
    """Format retrieved chunks as a system prompt appendix."""
    lines = [
        "",
        "---",
        "Relevant documentation (retrieved from local index):",
    ]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        section = r.get("section", "")
        source = Path(r.get("source", "")).name
        label = f"{title} › {section}" if section else f"{title} ({source})"
        text = r["text"].strip()[:400].replace("\n", " ")
        lines.append(f"\n[{i}] {label}")
        lines.append(f'"{text}"')
    lines.append("---")
    return "\n".join(lines)
