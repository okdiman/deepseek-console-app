"""
Query rewriting for improved RAG retrieval.

LLM-based rewriting: expands the query with synonyms, removes conversational filler.
Heuristic cleaning: regex-based, no LLM call needed.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_REWRITE_SYSTEM_PROMPT = (
    "You are a search query optimizer for semantic document retrieval.\n"
    "Your task: expand the query with related technical terms — do NOT remove or rephrase the original.\n"
    "Rules:\n"
    "- Keep ALL original words exactly as-is\n"
    "- Append 3-5 technical synonyms or related concepts after the original\n"
    "- Total output under 30 words\n"
    "- Return ONLY the expanded query as a single line, no explanations"
)

_FILLER_PATTERNS = [
    r"^(?:please\s+)?(?:can you\s+)?(?:tell me\s+)?",
    r"^(?:what (?:is|are)|how (?:does|do|is)|why (?:is|are)|explain)\s+",
]


class QueryRewriter:
    """
    Rewrites user queries before embedding to improve RAG retrieval.

    Two modes:
      - rewrite(query): LLM-based, makes a short streaming call.
      - clean(query):   Heuristic-only, no LLM.
    """

    def __init__(self, client) -> None:
        self._client = client

    async def rewrite(self, query: str) -> str:
        """
        Ask the LLM to expand and clean the query for better semantic search.
        Falls back to the original query on any error or empty response.
        """
        messages = [
            {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        try:
            tokens = []
            async for chunk in self._client.stream_message(messages, temperature=0.1):
                if chunk.startswith('{"__type__"'):
                    continue
                tokens.append(chunk)
            expanded = "".join(tokens).strip()
            # Sanity check: original keywords must be preserved
            original_words = set(query.lower().split())
            expanded_words = set(expanded.lower().split())
            overlap = len(original_words & expanded_words) / max(len(original_words), 1)
            if expanded and len(expanded) <= 300 and overlap >= 0.5:
                logger.debug("QueryRewriter: %r → %r", query, expanded)
                return expanded
        except Exception as exc:
            logger.warning("QueryRewriter: LLM call failed: %s", exc)
        return query

    @staticmethod
    def clean(query: str) -> str:
        """
        Heuristic query cleaning without an LLM call.
        Strips conversational prefixes and trailing punctuation.
        """
        q = query.strip()
        for pattern in _FILLER_PATTERNS:
            q = re.sub(pattern, "", q, flags=re.IGNORECASE).strip()
        q = q.rstrip("?").strip()
        return q if q else query
