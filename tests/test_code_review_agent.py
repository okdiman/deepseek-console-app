"""Tests for CodeReviewAgent — hook composition, system prompt, diff parser, JSON extraction."""
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


# ── System prompt ─────────────────────────────────────────────────────────────

def test_system_prompt_requires_json_output():
    assert "JSON" in SYSTEM_PROMPT


def test_system_prompt_has_verdict_field():
    assert "verdict" in SYSTEM_PROMPT


def test_system_prompt_has_verdict_values():
    for v in ("APPROVE", "COMMENT", "REQUEST_CHANGES"):
        assert v in SYSTEM_PROMPT


def test_system_prompt_has_comments_field():
    assert "comments" in SYSTEM_PROMPT


def test_system_prompt_mentions_line_validation():
    assert "MUST be" in SYSTEM_PROMPT or "must" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_rag():
    assert "RAG" in SYSTEM_PROMPT or "context" in SYSTEM_PROMPT.lower()


# ── Hook composition ──────────────────────────────────────────────────────────

def test_code_review_agent_has_rag_hook():
    agent = _make_agent()
    assert any(isinstance(h, RagHook) for h in agent._hooks)


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


# ── Diff parser ───────────────────────────────────────────────────────────────

from scripts.review_pr import parse_changed_lines, _build_prompt, extract_review_json, validate_comments


_SIMPLE_DIFF = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -10,4 +10,5 @@ class Foo:
 context
-old line
+new line
+another new line
 context2
"""


def test_parse_changed_lines_detects_file():
    result = parse_changed_lines(_SIMPLE_DIFF)
    assert "foo.py" in result


def test_parse_changed_lines_correct_line_numbers():
    result = parse_changed_lines(_SIMPLE_DIFF)
    # @@ -10,4 +10,5 @@ → new side starts at 10
    # line 10: "context" (context, advances)
    # line 11: "new line" (+, collected)
    # line 12: "another new line" (+, collected)
    assert 11 in result["foo.py"]
    assert 12 in result["foo.py"]


def test_parse_changed_lines_skips_deleted():
    result = parse_changed_lines(_SIMPLE_DIFF)
    # "-old line" is deleted — should not appear as a new-side line
    lines = result["foo.py"]
    assert len(lines) == 2  # only the two '+' lines


def test_parse_changed_lines_empty_diff():
    assert parse_changed_lines("") == {}


def test_parse_changed_lines_multiple_files():
    diff = (
        "+++ b/alpha.py\n@@ -1 +1 @@\n+x = 1\n"
        "+++ b/beta.py\n@@ -1 +1 @@\n+y = 2\n"
    )
    result = parse_changed_lines(diff)
    assert "alpha.py" in result
    assert "beta.py" in result


# ── Prompt builder ────────────────────────────────────────────────────────────

def test_build_prompt_includes_diff():
    changed = {"foo.py": [11, 12]}
    prompt = _build_prompt("- old\n+ new\n", changed)
    assert "- old" in prompt
    assert "+ new" in prompt


def test_build_prompt_includes_changed_lines_section():
    changed = {"foo.py": [11, 12]}
    prompt = _build_prompt("@@ @@\n+x\n", changed)
    assert "foo.py" in prompt
    assert "11" in prompt


def test_build_prompt_truncates_large_diff(monkeypatch):
    import scripts.review_pr as mod
    monkeypatch.setattr(mod, "_MAX_DIFF_CHARS", 20)
    prompt = _build_prompt("x" * 100, {})
    assert "truncated" in prompt.lower()


def test_build_prompt_no_changed_lines_section_when_empty():
    prompt = _build_prompt("@@ @@\n+x\n", {})
    assert "Changed lines" not in prompt


# ── JSON extraction ───────────────────────────────────────────────────────────

_VALID_REVIEW = {
    "verdict": "REQUEST_CHANGES",
    "summary": "High risk.",
    "comments": [{"path": "foo.py", "line": 11, "body": "🐛 Bug here"}],
}


def test_extract_review_json_raw():
    import json
    result = extract_review_json(json.dumps(_VALID_REVIEW))
    assert result["verdict"] == "REQUEST_CHANGES"


def test_extract_review_json_fenced():
    import json
    text = f"```json\n{json.dumps(_VALID_REVIEW)}\n```"
    result = extract_review_json(text)
    assert result["summary"] == "High risk."


def test_extract_review_json_embedded_in_prose():
    import json
    text = f"Here is my review:\n{json.dumps(_VALID_REVIEW)}\nDone."
    result = extract_review_json(text)
    assert len(result["comments"]) == 1


def test_extract_review_json_raises_on_no_json():
    with pytest.raises((ValueError, Exception)):
        extract_review_json("No JSON here at all.")


# ── Comment validation ────────────────────────────────────────────────────────

def test_validate_comments_accepts_valid():
    comments = [{"path": "foo.py", "line": 11, "body": "ok"}]
    changed = {"foo.py": [11, 12]}
    valid, skipped = validate_comments(comments, changed)
    assert len(valid) == 1
    assert len(skipped) == 0


def test_validate_comments_rejects_wrong_line():
    comments = [{"path": "foo.py", "line": 99, "body": "hallucinated"}]
    changed = {"foo.py": [11, 12]}
    valid, skipped = validate_comments(comments, changed)
    assert len(valid) == 0
    assert len(skipped) == 1


def test_validate_comments_rejects_unknown_file():
    comments = [{"path": "ghost.py", "line": 1, "body": "?"}]
    changed = {"foo.py": [1]}
    valid, skipped = validate_comments(comments, changed)
    assert len(skipped) == 1


def test_validate_comments_mixed():
    comments = [
        {"path": "foo.py", "line": 11, "body": "valid"},
        {"path": "foo.py", "line": 99, "body": "invalid"},
    ]
    changed = {"foo.py": [11]}
    valid, skipped = validate_comments(comments, changed)
    assert len(valid) == 1
    assert len(skipped) == 1
