"""
Tests for deepseek_chat.core.rag.citations
"""

import pytest

from deepseek_chat.core.rag.citations import (
    CitationBlock,
    ContextConfidence,
    assess_confidence,
    format_citation_block,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_chunk(score: float, i: int = 1) -> dict:
    return {
        "chunk_id": f"doc_structure_{i}",
        "source": f"docs/corpus/doc_{i}.md",
        "title": f"Document {i}",
        "section": f"Section {i}",
        "score": score,
        "text": "The attention mechanism allows the model to focus on relevant tokens.",
    }


# ── assess_confidence ─────────────────────────────────────────────────────────


class TestAssessConfidence:
    def test_empty_results(self):
        conf, score = assess_confidence([], idk_threshold=0.45, weak_context_threshold=0.55)
        assert conf == ContextConfidence.EMPTY
        assert score == 0.0

    def test_weak_context(self):
        chunks = [_make_chunk(0.35), _make_chunk(0.28)]
        conf, score = assess_confidence(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert conf == ContextConfidence.WEAK
        assert score == pytest.approx(0.35)

    def test_exactly_at_idk_threshold_is_weak(self):
        # score == threshold → still WEAK (< is not <=)
        chunks = [_make_chunk(0.44)]
        conf, _ = assess_confidence(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert conf == ContextConfidence.WEAK

    def test_uncertain_context(self):
        chunks = [_make_chunk(0.50)]
        conf, score = assess_confidence(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert conf == ContextConfidence.UNCERTAIN
        assert score == pytest.approx(0.50)

    def test_confident_context(self):
        chunks = [_make_chunk(0.70), _make_chunk(0.60)]
        conf, score = assess_confidence(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert conf == ContextConfidence.CONFIDENT
        assert score == pytest.approx(0.70)

    def test_max_score_used(self):
        # Only the highest score should determine confidence
        chunks = [_make_chunk(0.20), _make_chunk(0.80)]
        conf, score = assess_confidence(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert conf == ContextConfidence.CONFIDENT
        assert score == pytest.approx(0.80)

    def test_score_missing_treated_as_zero(self):
        chunks = [{"chunk_id": "x", "text": "hello"}]  # no "score" key
        conf, score = assess_confidence(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert conf == ContextConfidence.WEAK
        assert score == 0.0


# ── format_citation_block ─────────────────────────────────────────────────────


class TestFormatCitationBlock:
    def test_empty_returns_idk_block(self):
        block = format_citation_block([], idk_threshold=0.45, weak_context_threshold=0.55)
        assert block.confidence == ContextConfidence.EMPTY
        assert block.chunk_count == 0
        assert block.max_score == 0.0
        assert "RETRIEVED CONTEXT: none" in block.formatted
        assert "Answer from your own knowledge or available tools" in block.formatted

    def test_weak_block_contains_idk_instruction(self):
        chunks = [_make_chunk(0.30)]
        block = format_citation_block(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert block.confidence == ContextConfidence.WEAK
        assert "LOW CONFIDENCE" in block.formatted
        assert "Answer from your own knowledge or available tools" in block.formatted

    def test_uncertain_block_instruction(self):
        chunks = [_make_chunk(0.50)]
        block = format_citation_block(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert block.confidence == ContextConfidence.UNCERTAIN
        assert "MODERATE CONFIDENCE" in block.formatted
        assert "context confidence is moderate" in block.formatted

    def test_confident_block_instruction(self):
        chunks = [_make_chunk(0.70)]
        block = format_citation_block(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert block.confidence == ContextConfidence.CONFIDENT
        assert "HIGH CONFIDENCE" in block.formatted
        assert "Sources:" in block.formatted

    def test_citation_numbers_in_block(self):
        chunks = [_make_chunk(0.80, i=1), _make_chunk(0.75, i=2)]
        block = format_citation_block(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert "[1]" in block.formatted
        assert "[2]" in block.formatted
        assert block.chunk_count == 2

    def test_source_and_section_in_block(self):
        chunks = [_make_chunk(0.80, i=1)]
        block = format_citation_block(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert "docs/corpus/doc_1.md" in block.formatted
        assert "Section 1" in block.formatted

    def test_chunk_id_in_block(self):
        chunks = [_make_chunk(0.80, i=5)]
        block = format_citation_block(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert "doc_structure_5" in block.formatted

    def test_text_quoted_in_block(self):
        chunk = _make_chunk(0.80)
        block = format_citation_block([chunk], idk_threshold=0.45, weak_context_threshold=0.55)
        # Text should appear inside quotes
        assert '"The attention mechanism' in block.formatted

    def test_score_in_block(self):
        chunks = [_make_chunk(0.823)]
        block = format_citation_block(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert "score=0.823" in block.formatted

    def test_block_wrapped_in_dashes(self):
        chunks = [_make_chunk(0.70)]
        block = format_citation_block(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert block.formatted.count("---") >= 2

    def test_returns_citation_block_dataclass(self):
        chunks = [_make_chunk(0.70)]
        block = format_citation_block(chunks, idk_threshold=0.45, weak_context_threshold=0.55)
        assert isinstance(block, CitationBlock)
        assert isinstance(block.confidence, ContextConfidence)

    def test_section_omitted_when_empty(self):
        chunk = {
            "chunk_id": "x_fixed_0",
            "source": "docs/corpus/doc.md",
            "title": "Doc",
            "section": "",
            "score": 0.70,
            "text": "some text",
        }
        block = format_citation_block([chunk], idk_threshold=0.45, weak_context_threshold=0.55)
        # No § separator when section is empty
        assert " § " not in block.formatted

    def test_text_truncated_at_500_chars(self):
        long_text = "x" * 1000
        chunk = {
            "chunk_id": "x_fixed_0",
            "source": "docs/corpus/doc.md",
            "title": "Doc",
            "section": "Sec",
            "score": 0.70,
            "text": long_text,
        }
        block = format_citation_block([chunk], idk_threshold=0.45, weak_context_threshold=0.55)
        # The quoted text in the block should not contain 1000 x's
        assert "x" * 501 not in block.formatted


# ── Integration: config picks up env vars ─────────────────────────────────────

class TestConfigIntegration:
    def test_new_fields_have_defaults(self):
        from deepseek_chat.core.rag.config import load_rag_config
        # Should not raise; defaults are applied
        cfg = load_rag_config()
        assert cfg.citations_enabled is True
        assert cfg.idk_threshold == pytest.approx(0.45)
        assert cfg.weak_context_threshold == pytest.approx(0.55)

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("RAG_CITATIONS_ENABLED", "false")
        monkeypatch.setenv("RAG_IDK_THRESHOLD", "0.40")
        monkeypatch.setenv("RAG_WEAK_CONTEXT_THRESHOLD", "0.60")
        from importlib import reload
        import deepseek_chat.core.rag.config as cfg_mod
        reload(cfg_mod)
        cfg = cfg_mod.load_rag_config()
        assert cfg.citations_enabled is False
        assert cfg.idk_threshold == pytest.approx(0.40)
        assert cfg.weak_context_threshold == pytest.approx(0.60)
        # Restore
        reload(cfg_mod)
