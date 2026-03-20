"""Unit tests for DialogueTaskHook — before_stream injection, after_stream marker parsing."""
import os
from unittest.mock import MagicMock

import pytest

from deepseek_chat.agents.hooks.dialogue_task_hook import DialogueTaskHook
from deepseek_chat.core.memory import DialogueTask


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_agent():
    return MagicMock()


def make_history():
    return [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]


# ── before_stream ─────────────────────────────────────────────────────────────

class TestBeforeStream:
    @pytest.mark.asyncio
    async def test_injects_task_memory_section(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIALOGUE_TASK_PATH", str(tmp_path / "task.json"))
        hook = DialogueTaskHook()
        result = await hook.before_stream(
            make_agent(), "user question", "base prompt", make_history()
        )
        assert "## Dialogue Task Memory" in result

    @pytest.mark.asyncio
    async def test_appended_to_system_prompt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIALOGUE_TASK_PATH", str(tmp_path / "task.json"))
        hook = DialogueTaskHook()
        result = await hook.before_stream(
            make_agent(), "q", "MY BASE PROMPT", make_history()
        )
        assert result.startswith("MY BASE PROMPT")
        assert "## Dialogue Task Memory" in result

    @pytest.mark.asyncio
    async def test_existing_goal_shown(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        t = DialogueTask(goal="understand transformers")
        t.save()

        hook = DialogueTaskHook()
        result = await hook.before_stream(
            make_agent(), "q", "prompt", make_history()
        )
        assert "understand transformers" in result


# ── after_stream ──────────────────────────────────────────────────────────────

class TestAfterStream:
    @pytest.mark.asyncio
    async def test_goal_marker_saved(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()
        response = "Here is the answer. [GOAL: learn attention mechanism]"
        await hook.after_stream(make_agent(), response)

        loaded = DialogueTask.load()
        assert loaded.goal == "learn attention mechanism"

    @pytest.mark.asyncio
    async def test_clarified_marker_saved(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()
        response = "Sure. [CLARIFIED: user prefers math notation]"
        await hook.after_stream(make_agent(), response)

        loaded = DialogueTask.load()
        assert "user prefers math notation" in loaded.clarifications

    @pytest.mark.asyncio
    async def test_constraint_marker_saved(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()
        response = "Noted. [CONSTRAINT: no BERT examples]"
        await hook.after_stream(make_agent(), response)

        loaded = DialogueTask.load()
        assert "no BERT examples" in loaded.constraints

    @pytest.mark.asyncio
    async def test_topic_marker_saved(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()
        response = "We covered this. [TOPIC: self-attention basics]"
        await hook.after_stream(make_agent(), response)

        loaded = DialogueTask.load()
        assert "self-attention basics" in loaded.explored_topics

    @pytest.mark.asyncio
    async def test_multiple_markers_in_one_response(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()
        response = (
            "Great question! [GOAL: understand RAG] "
            "[CLARIFIED: user wants Python examples] "
            "[TOPIC: embeddings overview]"
        )
        await hook.after_stream(make_agent(), response)

        loaded = DialogueTask.load()
        assert loaded.goal == "understand RAG"
        assert "user wants Python examples" in loaded.clarifications
        assert "embeddings overview" in loaded.explored_topics

    @pytest.mark.asyncio
    async def test_no_markers_no_save(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()
        response = "This response has no task markers at all."
        await hook.after_stream(make_agent(), response)

        # File should not exist (no save triggered)
        assert not os.path.exists(path)

    @pytest.mark.asyncio
    async def test_case_insensitive_markers(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()
        response = "[goal: lowercase goal] [CLARIFIED: mixed Case Fact]"
        await hook.after_stream(make_agent(), response)

        loaded = DialogueTask.load()
        assert loaded.goal == "lowercase goal"
        assert "mixed Case Fact" in loaded.clarifications

    @pytest.mark.asyncio
    async def test_unresolved_marker_saved(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()
        response = "I cannot answer this. [UNRESOLVED: how does sqrt(d_k) work?]"
        await hook.after_stream(make_agent(), response)

        loaded = DialogueTask.load()
        assert "how does sqrt(d_k) work?" in loaded.unresolved_questions

    @pytest.mark.asyncio
    async def test_topic_clears_unresolved(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()
        # First turn: mark as unresolved
        await hook.after_stream(make_agent(), "[UNRESOLVED: scaled dot-product attention]")
        # Second turn: now answered
        await hook.after_stream(make_agent(), "[TOPIC: scaled dot-product attention]")

        loaded = DialogueTask.load()
        assert "scaled dot-product attention" in loaded.explored_topics
        assert loaded.unresolved_questions == []

    @pytest.mark.asyncio
    async def test_markers_accumulate_across_calls(self, tmp_path, monkeypatch):
        path = str(tmp_path / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", path)

        hook = DialogueTaskHook()

        await hook.after_stream(make_agent(), "[CLARIFIED: fact one]")
        await hook.after_stream(make_agent(), "[CLARIFIED: fact two]")

        loaded = DialogueTask.load()
        assert "fact one" in loaded.clarifications
        assert "fact two" in loaded.clarifications
