"""Tests for CodeReviewAgent — hook composition, system prompt, prompt building."""
from unittest.mock import MagicMock

import pytest

from deepseek_chat.agents.code_review_agent import CodeReviewAgent, SYSTEM_PROMPT
from deepseek_chat.agents.hooks.rag_hook import RagHook


def _make_agent(mcp_manager=None):
    client = MagicMock()
    session = MagicMock()
    session.messages.return_value = []
    session.summary = ""
    session.facts = []
    return CodeReviewAgent(client, session, mcp_manager=mcp_manager)


# ── System prompt ────────────────────────────────────────────────────────────

def test_system_prompt_has_review_sections():
    for section in ["Potential Bugs", "Architectural Issues", "Recommendations", "Summary"]:
        assert section in SYSTEM_PROMPT, f"Missing section: {section}"


def test_system_prompt_mentions_diff():
    assert "diff" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_rag():
    assert "rag" in SYSTEM_PROMPT.lower() or "context" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_risk_level():
    assert "risk" in SYSTEM_PROMPT.lower()


# ── Hook composition ─────────────────────────────────────────────────────────

def test_code_review_agent_has_rag_hook():
    agent = _make_agent()
    hook_types = [type(h) for h in agent._hooks]
    assert RagHook in hook_types


def test_code_review_agent_has_exactly_one_hook():
    agent = _make_agent()
    assert len(agent._hooks) == 1


def test_code_review_agent_no_mcp_by_default():
    agent = _make_agent()
    assert agent._mcp_manager is None


def test_code_review_agent_accepts_mcp_manager():
    manager = MagicMock()
    agent = _make_agent(mcp_manager=manager)
    assert agent._mcp_manager is manager


def test_code_review_agent_system_prompt():
    agent = _make_agent()
    assert agent.SYSTEM_PROMPT == SYSTEM_PROMPT


# ── Prompt builder (review_pr.py) ────────────────────────────────────────────

def test_build_prompt_includes_diff():
    from scripts.review_pr import _build_prompt
    prompt = _build_prompt("- old line\n+ new line\n", [])
    assert "- old line" in prompt
    assert "+ new line" in prompt


def test_build_prompt_includes_changed_files():
    from scripts.review_pr import _build_prompt
    prompt = _build_prompt("@@ -1 +1 @@\n+x = 1\n", ["foo.py", "bar.py"])
    assert "foo.py" in prompt
    assert "bar.py" in prompt


def test_build_prompt_truncates_large_diff(monkeypatch):
    import scripts.review_pr as mod
    monkeypatch.setattr(mod, "_MAX_DIFF_CHARS", 20)
    big_diff = "x" * 100
    prompt = _build_prompt(big_diff, [])
    assert "truncated" in prompt.lower()


def _build_prompt(diff, changed_files):
    """Re-import here to avoid module-level side effects during collection."""
    from scripts.review_pr import _build_prompt as _bp
    return _bp(diff, changed_files)


def test_build_prompt_empty_changed_files():
    from scripts.review_pr import _build_prompt
    prompt = _build_prompt("@@ -0,0 +1 @@\n+pass\n", [])
    assert "Changed files" not in prompt
    assert "```diff" in prompt
