"""Unit tests for DialogueTask — apply_marker, get_injection, persistence."""
import json
import os
import tempfile

import pytest

from deepseek_chat.core.dialogue_task import DialogueTask


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_path_str(tmp_path):
    return str(tmp_path / "dialogue_task.json")


@pytest.fixture
def task_with_path(tmp_path_str, monkeypatch):
    monkeypatch.setenv("DIALOGUE_TASK_PATH", tmp_path_str)
    return DialogueTask()


# ── apply_marker ──────────────────────────────────────────────────────────────

class TestApplyMarker:
    def test_goal_set(self):
        t = DialogueTask()
        t.apply_marker("GOAL", "understand attention mechanism")
        assert t.goal == "understand attention mechanism"

    def test_goal_update(self):
        t = DialogueTask(goal="old goal")
        t.apply_marker("GOAL", "new goal")
        assert t.goal == "new goal"

    def test_clarified_appended(self):
        t = DialogueTask()
        t.apply_marker("CLARIFIED", "prefers math notation")
        assert "prefers math notation" in t.clarifications

    def test_clarified_no_duplicates(self):
        t = DialogueTask()
        t.apply_marker("CLARIFIED", "same fact")
        t.apply_marker("CLARIFIED", "same fact")
        assert t.clarifications.count("same fact") == 1

    def test_constraint_appended(self):
        t = DialogueTask()
        t.apply_marker("CONSTRAINT", "no BERT examples")
        assert "no BERT examples" in t.constraints

    def test_constraint_no_duplicates(self):
        t = DialogueTask()
        t.apply_marker("CONSTRAINT", "rule")
        t.apply_marker("CONSTRAINT", "rule")
        assert t.constraints.count("rule") == 1

    def test_topic_appended(self):
        t = DialogueTask()
        t.apply_marker("TOPIC", "self-attention")
        assert "self-attention" in t.explored_topics

    def test_topic_no_duplicates(self):
        t = DialogueTask()
        t.apply_marker("TOPIC", "attention")
        t.apply_marker("TOPIC", "attention")
        assert t.explored_topics.count("attention") == 1

    def test_case_insensitive(self):
        t = DialogueTask()
        t.apply_marker("goal", "lowercase goal")
        assert t.goal == "lowercase goal"
        t.apply_marker("Clarified", "mixed case")
        assert "mixed case" in t.clarifications

    def test_empty_value_ignored(self):
        t = DialogueTask()
        t.apply_marker("GOAL", "   ")
        assert t.goal == ""

    def test_unknown_marker_ignored(self):
        t = DialogueTask()
        t.apply_marker("UNKNOWN", "value")
        assert t.goal == ""
        assert t.clarifications == []

    def test_unresolved_appended(self):
        t = DialogueTask()
        t.apply_marker("UNRESOLVED", "how does sqrt(d_k) work?")
        assert "how does sqrt(d_k) work?" in t.unresolved_questions

    def test_unresolved_no_duplicates(self):
        t = DialogueTask()
        t.apply_marker("UNRESOLVED", "same question")
        t.apply_marker("UNRESOLVED", "same question")
        assert t.unresolved_questions.count("same question") == 1

    def test_topic_clears_matching_unresolved(self):
        t = DialogueTask(unresolved_questions=["scaled dot-product attention"])
        t.apply_marker("TOPIC", "scaled dot-product attention")
        assert "scaled dot-product attention" not in t.unresolved_questions
        assert "scaled dot-product attention" in t.explored_topics

    def test_topic_clears_substring_unresolved(self):
        t = DialogueTask(unresolved_questions=["attention mechanism"])
        t.apply_marker("TOPIC", "scaled dot-product attention mechanism")
        assert t.unresolved_questions == []

    def test_unresolved_survives_unrelated_topic(self):
        t = DialogueTask(unresolved_questions=["positional encoding"])
        t.apply_marker("TOPIC", "multi-head attention")
        assert "positional encoding" in t.unresolved_questions


# ── clear ─────────────────────────────────────────────────────────────────────

class TestClear:
    def test_clears_all_fields(self):
        t = DialogueTask(
            goal="some goal",
            clarifications=["c1"],
            constraints=["r1"],
            explored_topics=["t1"],
            unresolved_questions=["q1"],
        )
        t.clear()
        assert t.goal == ""
        assert t.clarifications == []
        assert t.constraints == []
        assert t.explored_topics == []
        assert t.unresolved_questions == []


# ── get_injection ─────────────────────────────────────────────────────────────

class TestGetInjection:
    def test_empty_task_shows_placeholder(self):
        t = DialogueTask()
        injection = t.get_injection()
        assert "## Dialogue Task Memory" in injection
        assert "No goal established yet" in injection
        assert "[GOAL:" in injection

    def test_goal_shown(self):
        t = DialogueTask(goal="understand RAG")
        injection = t.get_injection()
        assert "Goal: understand RAG" in injection

    def test_clarifications_listed(self):
        t = DialogueTask(goal="g", clarifications=["prefers math", "no code"])
        injection = t.get_injection()
        assert "prefers math" in injection
        assert "no code" in injection

    def test_constraints_listed(self):
        t = DialogueTask(goal="g", constraints=["no Java", "Python only"])
        injection = t.get_injection()
        assert "no Java" in injection
        assert "Python only" in injection

    def test_explored_topics_listed(self):
        t = DialogueTask(goal="g", explored_topics=["self-attention"])
        injection = t.get_injection()
        assert "self-attention" in injection

    def test_unresolved_listed(self):
        t = DialogueTask(goal="g", unresolved_questions=["how does sqrt(d_k) work?"])
        injection = t.get_injection()
        assert "how does sqrt(d_k) work?" in injection
        assert "Unresolved" in injection

    def test_marker_instructions_always_present(self):
        t = DialogueTask()
        assert "[GOAL:" in t.get_injection()
        assert "[UNRESOLVED:" in t.get_injection()

        t2 = DialogueTask(goal="something")
        assert "[GOAL:" in t2.get_injection()
        assert "[UNRESOLVED:" in t2.get_injection()


# ── persistence ───────────────────────────────────────────────────────────────

class TestPersistence:
    def test_save_and_load(self, tmp_path_str, monkeypatch):
        monkeypatch.setenv("DIALOGUE_TASK_PATH", tmp_path_str)

        t = DialogueTask(
            goal="test goal",
            clarifications=["c1", "c2"],
            constraints=["r1"],
            explored_topics=["topic1"],
            unresolved_questions=["pending?"],
        )
        t.save()

        loaded = DialogueTask.load()
        assert loaded.goal == "test goal"
        assert loaded.clarifications == ["c1", "c2"]
        assert loaded.constraints == ["r1"]
        assert loaded.explored_topics == ["topic1"]
        assert loaded.unresolved_questions == ["pending?"]

    def test_load_missing_file_returns_empty(self, tmp_path_str, monkeypatch):
        monkeypatch.setenv("DIALOGUE_TASK_PATH", tmp_path_str)
        # File does not exist
        result = DialogueTask.load()
        assert result.goal == ""
        assert result.clarifications == []

    def test_load_corrupt_file_returns_empty(self, tmp_path_str, monkeypatch):
        monkeypatch.setenv("DIALOGUE_TASK_PATH", tmp_path_str)
        with open(tmp_path_str, "w") as f:
            f.write("not valid json {{{{")
        result = DialogueTask.load()
        assert result.goal == ""

    def test_save_creates_directory(self, tmp_path, monkeypatch):
        nested = str(tmp_path / "nested" / "dir" / "task.json")
        monkeypatch.setenv("DIALOGUE_TASK_PATH", nested)
        t = DialogueTask(goal="nested save")
        t.save()
        assert os.path.exists(nested)

    def test_roundtrip_preserves_all_fields(self, tmp_path_str, monkeypatch):
        monkeypatch.setenv("DIALOGUE_TASK_PATH", tmp_path_str)
        t = DialogueTask(
            goal="full roundtrip",
            clarifications=["a", "b"],
            constraints=["x"],
            explored_topics=["y", "z"],
        )
        t.save()
        loaded = DialogueTask.load()
        assert loaded.goal == t.goal
        assert loaded.clarifications == t.clarifications
        assert loaded.constraints == t.constraints
        assert loaded.explored_topics == t.explored_topics
