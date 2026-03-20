"""Unit tests for InvariantStore — CRUD, persistence, prompt injection."""
import json
import os
import tempfile

import pytest

from deepseek_chat.core.memory import InvariantStore


# ── Defaults ─────────────────────────────────────────────

class TestDefaults:
    def test_empty_on_init(self):
        store = InvariantStore()
        assert store.invariants == []
        assert store.get_all() == []


# ── Add / Remove ─────────────────────────────────────────

class TestAdd:
    def test_add_single(self):
        store = InvariantStore()
        store.add("Only Kotlin")
        assert store.get_all() == ["Only Kotlin"]

    def test_no_duplicates(self):
        store = InvariantStore()
        store.add("Only Kotlin")
        store.add("Only Kotlin")
        assert len(store.get_all()) == 1

    def test_add_empty_string_ignored(self):
        store = InvariantStore()
        store.add("")
        assert store.get_all() == []

    def test_add_multiple(self):
        store = InvariantStore()
        store.add("Clean Architecture")
        store.add("No Java")
        assert store.get_all() == ["Clean Architecture", "No Java"]


class TestRemove:
    def test_remove_by_index(self):
        store = InvariantStore()
        store.add("A")
        store.add("B")
        store.add("C")
        store.remove(1)
        assert store.get_all() == ["A", "C"]

    def test_remove_out_of_bounds(self):
        store = InvariantStore()
        store.add("A")
        store.remove(5)  # Should not crash
        assert store.get_all() == ["A"]

    def test_remove_negative_index(self):
        store = InvariantStore()
        store.add("A")
        store.remove(-1)  # Should not crash
        assert store.get_all() == ["A"]


# ── Persistence ──────────────────────────────────────────

class TestPersistence:
    def test_save_and_load(self):
        store = InvariantStore()
        store.add("Only Kotlin")
        store.add("Clean Architecture")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            # Monkey-patch storage path
            original = InvariantStore.get_storage_path
            InvariantStore.get_storage_path = classmethod(lambda cls: path)

            store.save()

            loaded = InvariantStore.load()
            assert loaded.get_all() == ["Only Kotlin", "Clean Architecture"]
        finally:
            InvariantStore.get_storage_path = original
            os.unlink(path)

    def test_load_missing_file(self):
        original = InvariantStore.get_storage_path
        InvariantStore.get_storage_path = classmethod(lambda cls: "/nonexistent/path.json")
        try:
            store = InvariantStore.load()
            assert store.invariants == []
        finally:
            InvariantStore.get_storage_path = original


# ── Serialization ────────────────────────────────────────

class TestSerialization:
    def test_to_dict(self):
        store = InvariantStore()
        store.add("Rule A")
        store.add("Rule B")
        d = store.to_dict()
        assert d == {"invariants": ["Rule A", "Rule B"]}

    def test_to_dict_empty(self):
        store = InvariantStore()
        assert store.to_dict() == {"invariants": []}


# ── Prompt Injection ─────────────────────────────────────

class TestPromptInjection:
    def test_empty_returns_empty_string(self):
        store = InvariantStore()
        assert store.get_system_prompt_injection() == ""

    def test_injection_contains_rules(self):
        store = InvariantStore()
        store.add("Only Kotlin")
        store.add("Clean Architecture")
        injection = store.get_system_prompt_injection()
        assert "STRICT INVARIANTS" in injection
        assert "#1: Only Kotlin" in injection
        assert "#2: Clean Architecture" in injection

    def test_injection_contains_refusal_instruction(self):
        store = InvariantStore()
        store.add("No Java")
        injection = store.get_system_prompt_injection()
        assert "REFUSE" in injection
        assert "FORBIDDEN" in injection
        assert "Never break them" in injection
