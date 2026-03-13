"""Unit tests for deepseek_chat/agents/hooks/auto_title.py — AutoTitleHook."""

from unittest.mock import MagicMock
import pytest

from deepseek_chat.agents.hooks.auto_title import AutoTitleHook


# ── Helpers ──────────────────────────────────────────────

def make_llm_gen(*chunks):
    """Return a callable that produces an async generator yielding chunks."""
    async def _gen(*args, **kwargs):
        for chunk in chunks:
            yield chunk
    return _gen


def make_agent(num_messages: int = 0, summary: str = ""):
    agent = MagicMock()
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(num_messages)
    ]
    agent._session.messages.return_value = messages
    agent._session.summary = summary
    # Wrap in MagicMock so assert_not_called() / assert_called() work
    agent._client.stream_message = MagicMock(side_effect=make_llm_gen("Test", " Title"))
    return agent


# ── before_stream ────────────────────────────────────────

class TestBeforeStream:
    @pytest.mark.asyncio
    async def test_returns_system_prompt_unchanged(self):
        hook = AutoTitleHook()
        agent = make_agent()
        result = await hook.before_stream(agent, "input", "system prompt", [])
        assert result == "system prompt"

    @pytest.mark.asyncio
    async def test_does_not_call_llm(self):
        hook = AutoTitleHook()
        agent = make_agent()
        await hook.before_stream(agent, "input", "sys", [])
        agent._client.stream_message.assert_not_called()


# ── after_stream — trigger conditions ───────────────────

class TestAfterStreamTrigger:
    @pytest.mark.asyncio
    async def test_fires_at_2_messages_no_summary(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2, summary="")
        await hook.after_stream(agent, "response")
        assert agent._session.summary == "Test Title"

    @pytest.mark.asyncio
    async def test_fires_at_4_messages_no_summary(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=4, summary="")
        await hook.after_stream(agent, "response")
        assert agent._session.summary == "Test Title"

    @pytest.mark.asyncio
    async def test_does_not_fire_at_1_message(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=1)
        await hook.after_stream(agent, "response")
        agent._client.stream_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_fire_at_3_messages(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=3)
        await hook.after_stream(agent, "response")
        agent._client.stream_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_fire_at_5_messages(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=5)
        await hook.after_stream(agent, "response")
        agent._client.stream_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_fire_at_6_messages(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=6)
        await hook.after_stream(agent, "response")
        agent._client.stream_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_fire_at_0_messages(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=0)
        await hook.after_stream(agent, "response")
        agent._client.stream_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_fire_if_summary_already_exists(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2, summary="Existing Title")
        await hook.after_stream(agent, "response")
        agent._client.stream_message.assert_not_called()
        assert agent._session.summary == "Existing Title"


# ── after_stream — title content ────────────────────────

class TestAfterStreamTitleContent:
    @pytest.mark.asyncio
    async def test_concatenates_chunks(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2)
        agent._client.stream_message = make_llm_gen("Hello", " World")
        await hook.after_stream(agent, "response")
        assert agent._session.summary == "Hello World"

    @pytest.mark.asyncio
    async def test_strips_double_quotes(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2)
        agent._client.stream_message = make_llm_gen('"Quoted Title"')
        await hook.after_stream(agent, "response")
        assert agent._session.summary == "Quoted Title"

    @pytest.mark.asyncio
    async def test_strips_single_quotes(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2)
        agent._client.stream_message = make_llm_gen("'Single Quoted'")
        await hook.after_stream(agent, "response")
        assert agent._session.summary == "Single Quoted"

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2)
        agent._client.stream_message = make_llm_gen("  Padded Title  ")
        await hook.after_stream(agent, "response")
        assert agent._session.summary == "Padded Title"

    @pytest.mark.asyncio
    async def test_empty_response_does_not_set_summary(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2)
        agent._client.stream_message = make_llm_gen("   ")
        await hook.after_stream(agent, "response")
        # Empty string after strip — summary stays as empty string (not set)
        assert agent._session.summary == ""


# ── after_stream — error resilience ─────────────────────

class TestAfterStreamErrors:
    @pytest.mark.asyncio
    async def test_llm_exception_does_not_propagate(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2)

        async def failing_gen(*args, **kwargs):
            raise RuntimeError("LLM unavailable")
            yield  # make it an async generator

        agent._client.stream_message = failing_gen
        # Must not raise
        await hook.after_stream(agent, "response")

    @pytest.mark.asyncio
    async def test_network_error_leaves_summary_empty(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2, summary="")

        async def failing_gen(*args, **kwargs):
            raise ConnectionError("timeout")
            yield

        agent._client.stream_message = failing_gen
        await hook.after_stream(agent, "response")
        assert agent._session.summary == ""

    @pytest.mark.asyncio
    async def test_empty_messages_list_no_llm_call(self):
        hook = AutoTitleHook()
        agent = make_agent(num_messages=2)
        agent._session.messages.return_value = []
        # _generate_title returns early if messages is empty
        await hook.after_stream(agent, "response")
        # summary remains unchanged (empty string from make_agent default)
