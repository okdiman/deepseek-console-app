"""
Citation formatting for RAG responses.

Provides structured citation blocks injected into the system prompt to guide the LLM
to cite sources and quote relevant text. Also handles "I don't know" / "weak context"
instructions based on retrieval confidence scores.

Context confidence levels (based on max cosine similarity of retrieved chunks):
  empty:     no chunks passed the reranker filter
  weak:      max_score < idk_threshold       → must respond "I don't know"
  uncertain: max_score < weak_ctx_threshold  → answer but add confidence caveat
  confident: max_score >= weak_ctx_threshold → full citation required
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple


class ContextConfidence(str, Enum):
    EMPTY = "empty"
    WEAK = "weak"
    UNCERTAIN = "uncertain"
    CONFIDENT = "confident"


@dataclass
class CitationBlock:
    """Result of formatting retrieved chunks for injection into system prompt."""

    formatted: str
    confidence: ContextConfidence
    max_score: float
    chunk_count: int


def assess_confidence(
    results: List[Dict],
    idk_threshold: float,
    weak_context_threshold: float,
) -> Tuple[ContextConfidence, float]:
    """Determine context confidence based on max cosine score of retrieved chunks."""
    if not results:
        return ContextConfidence.EMPTY, 0.0

    max_score = max(r.get("score", 0.0) for r in results)
    if max_score < idk_threshold:
        return ContextConfidence.WEAK, max_score
    elif max_score < weak_context_threshold:
        return ContextConfidence.UNCERTAIN, max_score
    else:
        return ContextConfidence.CONFIDENT, max_score


def format_citation_block(
    results: List[Dict],
    idk_threshold: float,
    weak_context_threshold: float,
) -> CitationBlock:
    """
    Build the full RAG system prompt block including:
    - numbered citation list with source, section, chunk_id, score, and text
    - behavioral instruction matching the confidence level
    """
    confidence, max_score = assess_confidence(results, idk_threshold, weak_context_threshold)

    if confidence == ContextConfidence.EMPTY:
        return CitationBlock(
            formatted=_empty_block(),
            confidence=confidence,
            max_score=0.0,
            chunk_count=0,
        )

    lines: List[str] = [
        "",
        "---",
        "RETRIEVED CONTEXT (from local document index):",
        "",
    ]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        section = r.get("section", "")
        source = r.get("source", "")
        chunk_id = r.get("chunk_id", "")
        score = r.get("score", 0.0)
        text = r["text"].strip()[:500].replace("\n", " ")

        source_label = source + (f" § {section}" if section else "")
        lines.append(f"[{i}] {title} | {source_label} | score={score:.3f} | id={chunk_id}")
        lines.append(f'    "{text}"')
        lines.append("")

    if confidence == ContextConfidence.WEAK:
        lines += _weak_instruction_lines()
    elif confidence == ContextConfidence.UNCERTAIN:
        lines += _uncertain_instruction_lines()
    else:
        lines += _confident_instruction_lines()

    lines.append("---")

    return CitationBlock(
        formatted="\n".join(lines),
        confidence=confidence,
        max_score=max_score,
        chunk_count=len(results),
    )


# ── Instruction blocks ────────────────────────────────────────────────────────


def _empty_block() -> str:
    return (
        "\n---\n"
        "RETRIEVED CONTEXT: none (no relevant documents found in the index).\n"
        "\n"
        "INSTRUCTION: The knowledge base contains no relevant information for this query.\n"
        'You MUST respond with: "I don\'t have enough information to answer this question."\n'
        "Then ask the user to clarify or provide more context.\n"
        "Do NOT answer from general knowledge when RAG context is empty.\n"
        "---"
    )


def _weak_instruction_lines() -> List[str]:
    return [
        "INSTRUCTION (LOW CONFIDENCE — max similarity below threshold):",
        "The retrieved context is not sufficiently relevant to answer this question reliably.",
        "You MUST:",
        '  1. Say "I don\'t have enough information to answer this question confidently."',
        "  2. Briefly mention what context was found, citing [N] source numbers.",
        "  3. Ask the user to clarify or rephrase their question.",
        "Do NOT fabricate an answer from the weak context above.",
        "",
    ]


def _uncertain_instruction_lines() -> List[str]:
    return [
        "INSTRUCTION (MODERATE CONFIDENCE):",
        "The retrieved context is partially relevant. You MUST:",
        "  1. Answer based ONLY on the context provided above.",
        '  2. Cite every claim with [N] (e.g. "According to [1]...").',
        "  3. Include at least one direct quote per cited source (copy exact text in quotes).",
        '  4. End with: "Note: context confidence is moderate — verify if precision matters."',
        "  5. Do NOT add information not present in the context.",
        "",
    ]


def _confident_instruction_lines() -> List[str]:
    return [
        "INSTRUCTION (HIGH CONFIDENCE):",
        "Answer based ONLY on the context provided above. You MUST:",
        '  1. Cite every factual claim with [N] (e.g. "According to [1]...").',
        "  2. Include at least one direct quote per cited source (copy exact text in quotes).",
        '  3. End with a "Sources:" section listing all cited chunks by ID.',
        "  4. Do NOT add information not present in the retrieved context.",
        "",
    ]
