"""Tests for DevHelpAgent — hook composition and system prompt."""
from unittest.mock import MagicMock

import pytest

from deepseek_chat.agents.dev_help_agent import DevHelpAgent, SYSTEM_PROMPT
from deepseek_chat.agents.hooks.rag_hook import RagHook


def _make_agent(mcp_manager=None):
    client = MagicMock()
    session = MagicMock()
    session.messages.return_value = []
    session.summary = ""
    session.facts = []
    return DevHelpAgent(client, session, mcp_manager=mcp_manager)


def test_system_prompt_mentions_project():
    assert "project" in SYSTEM_PROMPT.lower()
    assert "rag" in SYSTEM_PROMPT.lower() or "knowledge base" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_git():
    assert "git" in SYSTEM_PROMPT.lower()


def test_dev_help_agent_has_rag_hook():
    agent = _make_agent()
    hook_types = [type(h) for h in agent._hooks]
    assert RagHook in hook_types


def test_dev_help_agent_has_rag_and_auto_title_hooks():
    from deepseek_chat.agents.hooks import AutoTitleHook
    agent = _make_agent()
    hook_types = [type(h) for h in agent._hooks]
    assert RagHook in hook_types
    assert AutoTitleHook in hook_types
    assert len(agent._hooks) == 2


def test_dev_help_agent_accepts_mcp_manager():
    manager = MagicMock()
    agent = _make_agent(mcp_manager=manager)
    assert agent._mcp_manager is manager


def test_dev_help_agent_system_prompt():
    agent = _make_agent()
    assert agent.SYSTEM_PROMPT == SYSTEM_PROMPT
