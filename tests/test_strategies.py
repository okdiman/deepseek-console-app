"""Unit tests for deepseek_chat/agents/strategies.py — UnifiedStrategy."""

from unittest.mock import MagicMock
import pytest

from deepseek_chat.agents.strategies import UnifiedStrategy, get_strategy
from deepseek_chat.core.session import ChatSession


# ── Helpers ──────────────────────────────────────────────

def make_strategy(summary="", compression_enabled=False, threshold=10, keep=4):
    client = MagicMock()
    client.config.compression_enabled = compression_enabled
    client.config.compression_threshold = threshold
    client.config.compression_keep = keep
    session = ChatSession(max_messages=40)
    session.summary = summary
    return UnifiedStrategy(client, session), session


# ── build_history_messages ───────────────────────────────

class TestBuildHistoryMessages:
    def test_first_message_is_system(self):
        strategy, _ = make_strategy()
        msgs = strategy.build_history_messages("You are helpful.")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are helpful."

    def test_no_summary_only_system_message(self):
        strategy, _ = make_strategy()
        msgs = strategy.build_history_messages("sys")
        # Only system message, no user messages
        assert len(msgs) == 1

    def test_summary_injected_as_system_message(self):
        strategy, _ = make_strategy(summary="Old conversation about Python")
        msgs = strategy.build_history_messages("sys")
        summary_msgs = [m for m in msgs if m["role"] == "system" and "Old conversation" in m["content"]]
        assert len(summary_msgs) == 1

    def test_summary_message_follows_system_prompt(self):
        strategy, _ = make_strategy(summary="Context")
        msgs = strategy.build_history_messages("sys")
        assert msgs[0]["content"] == "sys"
        assert "Context" in msgs[1]["content"]

    def test_user_messages_included(self):
        strategy, session = make_strategy()
        session.add_user("Hello")
        msgs = strategy.build_history_messages("sys")
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "Hello"

    def test_conversation_order_preserved(self):
        strategy, session = make_strategy()
        session.add_user("Q1")
        session.add_assistant("A1")
        session.add_user("Q2")
        msgs = strategy.build_history_messages("sys")
        roles = [m["role"] for m in msgs]
        assert roles[0] == "system"
        assert roles.index("user") < roles.index("assistant")

    def test_summary_comes_before_user_messages(self):
        strategy, session = make_strategy(summary="Old context")
        session.add_user("New question")
        msgs = strategy.build_history_messages("sys")
        summary_idx = next(i for i, m in enumerate(msgs) if "Old context" in m.get("content", ""))
        user_idx = next(i for i, m in enumerate(msgs) if m["role"] == "user")
        assert summary_idx < user_idx

    def test_empty_system_prompt_allowed(self):
        strategy, _ = make_strategy()
        msgs = strategy.build_history_messages("")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == ""

    def test_multiple_exchanges_included(self):
        strategy, session = make_strategy()
        for i in range(3):
            session.add_user(f"Q{i}")
            session.add_assistant(f"A{i}")
        msgs = strategy.build_history_messages("sys")
        user_count = sum(1 for m in msgs if m["role"] == "user")
        assistant_count = sum(1 for m in msgs if m["role"] == "assistant")
        assert user_count == 3
        assert assistant_count == 3


# ── get_system_message_for_response ─────────────────────

class TestGetSystemMessageForResponse:
    def test_not_compressed_returns_none(self):
        strategy, _ = make_strategy()
        assert strategy.get_system_message_for_response() is None

    def test_compressed_no_facts_returns_string(self):
        strategy, _ = make_strategy()
        strategy._compressed = True
        strategy._last_extracted_facts = []
        msg = strategy.get_system_message_for_response()
        assert msg is not None
        assert isinstance(msg, str)

    def test_compressed_no_facts_mentions_compression(self):
        strategy, _ = make_strategy()
        strategy._compressed = True
        strategy._last_extracted_facts = []
        msg = strategy.get_system_message_for_response()
        assert "сжат" in msg

    def test_compressed_with_facts_includes_them(self):
        strategy, _ = make_strategy()
        strategy._compressed = True
        strategy._last_extracted_facts = ["fact one", "fact two"]
        msg = strategy.get_system_message_for_response()
        assert "fact one" in msg
        assert "fact two" in msg

    def test_compressed_with_facts_different_from_no_facts(self):
        strategy, _ = make_strategy()
        strategy._compressed = True
        strategy._last_extracted_facts = ["some fact"]
        msg_with_facts = strategy.get_system_message_for_response()
        strategy._last_extracted_facts = []
        msg_no_facts = strategy.get_system_message_for_response()
        assert msg_with_facts != msg_no_facts


# ── process_context (no LLM path) ───────────────────────

class TestProcessContextNoCompression:
    @pytest.mark.asyncio
    async def test_disabled_does_not_call_llm(self):
        strategy, _ = make_strategy(compression_enabled=False)
        await strategy.process_context("sys", "user input")
        strategy._client.stream_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_below_threshold_does_not_call_llm(self):
        strategy, session = make_strategy(compression_enabled=True, threshold=10)
        # Add only 3 user messages — below threshold of 10
        for i in range(3):
            session.add_user(f"msg {i}")
        await strategy.process_context("sys", "user input")
        strategy._client.stream_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_compressed_flag_initially_false(self):
        strategy, _ = make_strategy()
        assert strategy._compressed is False

    @pytest.mark.asyncio
    async def test_no_compression_leaves_session_unchanged(self):
        strategy, session = make_strategy(compression_enabled=False)
        session.add_user("hello")
        session.add_assistant("world")
        before = len(session.messages())
        await strategy.process_context("sys", "new input")
        assert len(session.messages()) == before


# ── get_strategy ─────────────────────────────────────────

class TestGetStrategy:
    def test_returns_unified_strategy_instance(self):
        client = MagicMock()
        session = ChatSession()
        strategy = get_strategy(client, session)
        assert isinstance(strategy, UnifiedStrategy)

    def test_different_calls_return_different_instances(self):
        client = MagicMock()
        session = ChatSession()
        s1 = get_strategy(client, session)
        s2 = get_strategy(client, session)
        assert s1 is not s2
