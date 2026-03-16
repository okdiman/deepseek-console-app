"""
RagHook — injects relevant document chunks into the system prompt before each LLM call.

Embeds the user's query via Ollama, searches the local RAG index,
and appends the top-k results to the system prompt as reference context.

Gracefully disabled when:
  - RAG_ENABLED=false (env var)
  - Ollama is not reachable
  - Index is empty (no chunks indexed yet)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

from .base import AgentHook

if TYPE_CHECKING:
    from ..base_agent import BaseAgent

logger = logging.getLogger(__name__)

_RAG_ENABLED = os.getenv("RAG_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
_TOP_K = int(os.getenv("RAG_TOP_K", "3"))
_STRATEGY = os.getenv("RAG_SEARCH_STRATEGY", "structure")


class RagHook(AgentHook):
    """
    Retrieval-Augmented Generation hook.

    On every before_stream call:
      1. Embeds user_input via Ollama (nomic-embed-text)
      2. Searches the local SQLite index for top-k relevant chunks
      3. Appends them to the system_prompt as a "Relevant documentation" block

    If Ollama is unreachable or the index is empty, the hook silently
    returns the unchanged system_prompt — the agent continues normally.
    """

    def __init__(self) -> None:
        self._ready: bool | None = None  # None = not checked yet

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
            from deepseek_chat.core.rag.store import search_by_embedding

            config = load_rag_config()
            embedder = OllamaEmbeddingClient(config)

            vec = embedder.embed([user_input])[0]
            results = search_by_embedding(
                vec,
                top_k=_TOP_K,
                strategy=_STRATEGY,
                db_path=config.db_path,
            )

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
