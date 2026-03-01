"""
Lightweight token counting helpers with optional tiktoken support.

If tiktoken is unavailable, falls back to a rough heuristic:
- 1 token per ~4 characters (rounded up), minimum 1 for non-empty text.

This is intentionally simple so it can be used without extra deps.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    method: str  # "tiktoken" or "heuristic"


def _try_get_tiktoken_encoder(model: Optional[str] = None):
    try:
        import tiktoken  # type: ignore
    except Exception:
        return None

    # Prefer model-specific encoding if possible
    if model:
        try:
            return tiktoken.encoding_for_model(model)
        except Exception:
            pass

    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_text_tokens(text: str, model: Optional[str] = None) -> TokenCount:
    """
    Count tokens for a single text string.

    Uses tiktoken if available; otherwise falls back to heuristic.
    """
    if not text:
        return TokenCount(tokens=0, method="heuristic")

    encoder = _try_get_tiktoken_encoder(model)
    if encoder is not None:
        return TokenCount(tokens=len(encoder.encode(text)), method="tiktoken")

    # Heuristic: ~4 chars per token (roughly GPT-like)
    tokens = max(1, ceil(len(text) / 4))
    return TokenCount(tokens=tokens, method="heuristic")


def count_messages_tokens(
    messages: Iterable[Dict[str, str]],
    model: Optional[str] = None,
    per_message_overhead: int = 3,
    per_name_overhead: int = 1,
) -> TokenCount:
    """
    Count tokens for a list of chat messages.

    Notes:
    - This uses a simplified heuristic for chat-format overhead.
    - If tiktoken is available, it is applied to content strings, while
      overhead remains approximate.

    Overhead defaults are aligned with common OpenAI chat counting rules,
    but may differ per provider/model.
    """
    total = 0
    method = "heuristic"

    encoder = _try_get_tiktoken_encoder(model)
    if encoder is not None:
        method = "tiktoken"

    for msg in messages:
        # Role contributes tokens too (small but non-zero)
        role = msg.get("role", "")
        name = msg.get("name", "")
        content = msg.get("content", "")

        if encoder is not None:
            total += len(encoder.encode(role))
            total += len(encoder.encode(content))
            if name:
                total += len(encoder.encode(name))
        else:
            if role:
                total += max(1, ceil(len(role) / 4))
            if content:
                total += max(1, ceil(len(content) / 4))
            if name:
                total += max(1, ceil(len(name) / 4))

        total += per_message_overhead
        if name:
            total += per_name_overhead

    return TokenCount(tokens=total, method=method)
