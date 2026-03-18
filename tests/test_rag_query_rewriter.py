"""Unit tests for deepseek_chat.core.rag.query_rewriter."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from deepseek_chat.core.rag.query_rewriter import QueryRewriter


# ── QueryRewriter.clean ────────────────────────────────────────────────────────

class TestClean:
    def test_removes_what_is_prefix(self):
        assert "transformer" in QueryRewriter.clean("what is a transformer?").lower()

    def test_removes_how_does_prefix(self):
        result = QueryRewriter.clean("how does attention work?")
        assert result.lower().startswith("attention")

    def test_removes_trailing_question_mark(self):
        result = QueryRewriter.clean("attention mechanism?")
        assert not result.endswith("?")

    def test_removes_can_you_tell_me(self):
        result = QueryRewriter.clean("can you tell me about RAG?")
        assert "can you" not in result.lower()

    def test_removes_please_explain(self):
        result = QueryRewriter.clean("please explain attention mechanism")
        assert not result.lower().startswith("please")

    def test_preserves_technical_query(self):
        q = "transformer self-attention key query value"
        assert QueryRewriter.clean(q) == q

    def test_empty_string_returns_original(self):
        assert QueryRewriter.clean("") == ""

    def test_only_filler_returns_original(self):
        # If stripping filler leaves nothing, return original
        original = "what is"
        result = QueryRewriter.clean(original)
        assert result  # not empty


# ── QueryRewriter.rewrite ──────────────────────────────────────────────────────

class TestRewrite:
    def _make_client(self, response: str):
        """Build a mock client whose stream_message yields the response."""
        async def _gen(messages, **kwargs):
            for char in response:
                yield char

        client = MagicMock()
        client.stream_message = _gen
        return client

    @pytest.mark.asyncio
    async def test_returns_expanded_query_preserving_original(self):
        # Expansion must keep original words — "attention mechanism" is in both
        client = self._make_client("attention mechanism self-attention transformer query key value")
        rewriter = QueryRewriter(client)
        result = await rewriter.rewrite("attention mechanism")
        assert result == "attention mechanism self-attention transformer query key value"

    @pytest.mark.asyncio
    async def test_falls_back_when_keywords_lost(self):
        # LLM dropped all original words → should fall back to original
        client = self._make_client("neural network deep learning")
        rewriter = QueryRewriter(client)
        original = "MCP tool execution agent"
        result = await rewriter.rewrite(original)
        assert result == original  # overlap too low

    @pytest.mark.asyncio
    async def test_falls_back_on_empty_response(self):
        client = self._make_client("")
        rewriter = QueryRewriter(client)
        original = "how does RAG work?"
        result = await rewriter.rewrite(original)
        assert result == original

    @pytest.mark.asyncio
    async def test_falls_back_on_too_long_response(self):
        client = self._make_client("x" * 301)
        rewriter = QueryRewriter(client)
        original = "what is RAG?"
        result = await rewriter.rewrite(original)
        assert result == original

    @pytest.mark.asyncio
    async def test_falls_back_on_exception(self):
        async def _broken(messages, **kwargs):
            raise RuntimeError("connection refused")
            yield  # make it a generator

        client = MagicMock()
        client.stream_message = _broken
        rewriter = QueryRewriter(client)
        original = "how does attention work?"
        result = await rewriter.rewrite(original)
        assert result == original

    @pytest.mark.asyncio
    async def test_skips_tool_call_events(self):
        async def _gen(messages, **kwargs):
            yield '{"__type__": "tool_call_start", "name": "search"}'
            yield "attention mechanism self-attention"

        client = MagicMock()
        client.stream_message = _gen
        rewriter = QueryRewriter(client)
        result = await rewriter.rewrite("attention mechanism")
        assert result == "attention mechanism self-attention"

    @pytest.mark.asyncio
    async def test_passes_low_temperature(self):
        """Rewrite must call stream_message with temperature=0.1 for determinism."""
        captured = {}

        async def _capturing(messages, **kwargs):
            captured["temperature"] = kwargs.get("temperature")
            yield "attention mechanism transformer"

        client = MagicMock()
        client.stream_message = _capturing
        rewriter = QueryRewriter(client)
        await rewriter.rewrite("attention mechanism")
        assert captured.get("temperature") == 0.1
