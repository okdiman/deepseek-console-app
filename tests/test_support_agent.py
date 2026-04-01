"""Tests for SupportAgent — hook composition and system prompt."""
from unittest.mock import MagicMock

from deepseek_chat.agents.support_agent import SupportAgent, SYSTEM_PROMPT
from deepseek_chat.agents.hooks.rag_hook import RagHook
from deepseek_chat.agents.hooks import AutoTitleHook


def _make_agent(mcp_manager=None):
    client = MagicMock()
    session = MagicMock()
    session.messages.return_value = []
    session.summary = ""
    session.facts = []
    return SupportAgent(client, session, mcp_manager=mcp_manager)


def test_system_prompt_mentions_support():
    assert "support" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_crm():
    assert "get_ticket" in SYSTEM_PROMPT or "crm" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_rag():
    assert "rag" in SYSTEM_PROMPT.lower() or "faq" in SYSTEM_PROMPT.lower()


def test_support_agent_has_rag_hook():
    agent = _make_agent()
    hook_types = [type(h) for h in agent._hooks]
    assert RagHook in hook_types


def test_support_agent_has_auto_title_hook():
    agent = _make_agent()
    hook_types = [type(h) for h in agent._hooks]
    assert AutoTitleHook in hook_types


def test_support_agent_has_exactly_two_hooks():
    agent = _make_agent()
    assert len(agent._hooks) == 2


def test_support_agent_rag_hook_allows_tools():
    agent = _make_agent()
    rag_hook = next(h for h in agent._hooks if isinstance(h, RagHook))
    assert rag_hook._allow_tools is True


def test_support_agent_accepts_mcp_manager():
    manager = MagicMock()
    agent = _make_agent(mcp_manager=manager)
    assert agent._mcp_manager is manager


def test_support_agent_system_prompt():
    agent = _make_agent()
    assert agent.SYSTEM_PROMPT == SYSTEM_PROMPT
