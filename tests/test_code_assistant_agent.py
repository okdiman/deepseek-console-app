"""Tests for CodeAssistantAgent — hook composition and system prompt."""
from unittest.mock import MagicMock

from deepseek_chat.agents.code_assistant_agent import CodeAssistantAgent, SYSTEM_PROMPT
from deepseek_chat.agents.hooks.auto_title import AutoTitleHook


def _make_agent(mcp_manager=None):
    client = MagicMock()
    session = MagicMock()
    session.messages.return_value = []
    session.summary = ""
    session.facts = []
    return CodeAssistantAgent(client, session, mcp_manager=mcp_manager)


# ── System prompt ────────────────────────────────────────────────────────────

def test_system_prompt_mentions_file_operations():
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "read_file" in prompt_lower or "search_in_files" in prompt_lower


def test_system_prompt_mentions_propose():
    assert "propose_edit" in SYSTEM_PROMPT or "propose_write" in SYSTEM_PROMPT


def test_system_prompt_covers_search_scenario():
    assert "search" in SYSTEM_PROMPT.lower()


def test_system_prompt_covers_doc_update_scenario():
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "document" in prompt_lower or "doc" in prompt_lower


def test_system_prompt_covers_generate_scenario():
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "changelog" in prompt_lower or "generate" in prompt_lower or "adr" in prompt_lower


def test_system_prompt_covers_audit_scenario():
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "check" in prompt_lower or "audit" in prompt_lower or "invariant" in prompt_lower


def test_system_prompt_enforces_proposal_protocol():
    # Must mention the two-phase write protocol
    assert "propose_edit" in SYSTEM_PROMPT
    assert "propose_write" in SYSTEM_PROMPT


def test_system_prompt_no_rag():
    # CodeAssistantAgent must NOT use RAG infrastructure — it goes straight to filesystem tools.
    # The word "rag" may appear in examples (e.g. "RagHook") but the hook itself must be absent.
    from deepseek_chat.agents.hooks.rag_hook import RagHook
    agent = _make_agent()
    hook_types = [type(h) for h in agent._hooks]
    assert RagHook not in hook_types
    # Also: no RAG-specific injection keywords in the system prompt
    assert "rag context" not in SYSTEM_PROMPT.lower()
    assert "citation block" not in SYSTEM_PROMPT.lower()


# ── Hook composition ─────────────────────────────────────────────────────────

def test_code_assistant_has_auto_title_hook():
    agent = _make_agent()
    hook_types = [type(h) for h in agent._hooks]
    assert AutoTitleHook in hook_types


def test_code_assistant_has_exactly_one_hook():
    agent = _make_agent()
    assert len(agent._hooks) == 1


def test_code_assistant_no_rag_hook():
    from deepseek_chat.agents.hooks.rag_hook import RagHook
    agent = _make_agent()
    hook_types = [type(h) for h in agent._hooks]
    assert RagHook not in hook_types


def test_code_assistant_accepts_mcp_manager():
    manager = MagicMock()
    agent = _make_agent(mcp_manager=manager)
    assert agent._mcp_manager is manager


def test_code_assistant_system_prompt_matches_module_constant():
    agent = _make_agent()
    assert agent.SYSTEM_PROMPT == SYSTEM_PROMPT


# ── Registry integration ─────────────────────────────────────────────────────

def test_code_assistant_registered_in_agent_registry():
    from deepseek_chat.web.state import get_agent_registry
    registry = get_agent_registry()
    assert "code_assistant" in registry


def test_code_assistant_registry_name():
    from deepseek_chat.web.state import get_agent_registry
    registry = get_agent_registry()
    assert registry["code_assistant"] == "Code Assistant"


def test_get_agent_returns_code_assistant():
    from unittest.mock import patch
    from deepseek_chat.web import state

    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_session.messages.return_value = []
    mock_session.summary = ""
    mock_session.facts = []

    with patch.object(state, "get_client", return_value=mock_client), \
         patch.object(state, "get_session", return_value=mock_session), \
         patch.object(state, "get_task_machine", return_value=MagicMock()):
        agent = state.get_agent("code_assistant", session_id="test")

    assert isinstance(agent, CodeAssistantAgent)
