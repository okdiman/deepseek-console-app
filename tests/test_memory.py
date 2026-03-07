"""Unit tests for MemoryStore — CRUD, clear, prompt injection, persistence."""
import json
import os
import tempfile

import pytest

from deepseek_chat.core.memory import MemoryStore


# ── Defaults ─────────────────────────────────────────────

class TestDefaults:
    def test_empty_on_init(self):
        store = MemoryStore()
        assert store.working_memory == []
        assert store.long_term_memory == []


# ── Working Memory CRUD ──────────────────────────────────

class TestWorkingMemory:
    def test_add(self):
        store = MemoryStore()
        store.add_working_memory("fact 1")
        assert store.working_memory == ["fact 1"]

    def test_no_duplicates(self):
        store = MemoryStore()
        store.add_working_memory("fact 1")
        store.add_working_memory("fact 1")
        assert len(store.working_memory) == 1

    def test_set(self):
        store = MemoryStore()
        store.set_working_memory(["a", "b", "c"])
        assert store.working_memory == ["a", "b", "c"]

    def test_remove(self):
        store = MemoryStore()
        store.set_working_memory(["a", "b", "c"])
        store.remove_working_memory(1)
        assert store.working_memory == ["a", "c"]

    def test_remove_out_of_bounds(self):
        store = MemoryStore()
        store.add_working_memory("a")
        store.remove_working_memory(99)
        assert store.working_memory == ["a"]

    def test_remove_negative_index(self):
        store = MemoryStore()
        store.add_working_memory("a")
        store.remove_working_memory(-1)
        assert store.working_memory == ["a"]

    def test_clear(self):
        store = MemoryStore()
        store.set_working_memory(["a", "b"])
        store.clear_working_memory()
        assert store.working_memory == []


# ── Long-term Memory CRUD ────────────────────────────────

class TestLongTermMemory:
    def test_add(self):
        store = MemoryStore()
        store.add_long_term_memory("long fact")
        assert store.long_term_memory == ["long fact"]

    def test_no_duplicates(self):
        store = MemoryStore()
        store.add_long_term_memory("fact")
        store.add_long_term_memory("fact")
        assert len(store.long_term_memory) == 1

    def test_set(self):
        store = MemoryStore()
        store.set_long_term_memory(["x", "y"])
        assert store.long_term_memory == ["x", "y"]

    def test_remove(self):
        store = MemoryStore()
        store.set_long_term_memory(["x", "y", "z"])
        store.remove_long_term_memory(0)
        assert store.long_term_memory == ["y", "z"]

    def test_remove_out_of_bounds(self):
        store = MemoryStore()
        store.add_long_term_memory("x")
        store.remove_long_term_memory(10)
        assert store.long_term_memory == ["x"]

    def test_clear_working_does_not_affect_long_term(self):
        store = MemoryStore()
        store.set_working_memory(["w"])
        store.set_long_term_memory(["lt"])
        store.clear_working_memory()
        assert store.working_memory == []
        assert store.long_term_memory == ["lt"]


# ── Prompt Injection ─────────────────────────────────────

class TestPromptInjection:
    def test_empty_returns_empty(self):
        store = MemoryStore()
        assert store.get_system_prompt_injection() == ""

    def test_long_term_only(self):
        store = MemoryStore()
        store.set_long_term_memory(["Python 3.10+"])
        injection = store.get_system_prompt_injection()
        assert "[LONG-TERM MEMORY" in injection
        assert "1. Python 3.10+" in injection
        assert "GROUND TRUTH" in injection

    def test_working_only(self):
        store = MemoryStore()
        store.set_working_memory(["Optimize queries"])
        injection = store.get_system_prompt_injection()
        assert "[WORKING MEMORY" in injection
        assert "1. Optimize queries" in injection

    def test_both_memories(self):
        store = MemoryStore()
        store.set_long_term_memory(["LT fact"])
        store.set_working_memory(["WM fact"])
        injection = store.get_system_prompt_injection()
        assert "[LONG-TERM MEMORY" in injection
        assert "[WORKING MEMORY" in injection
        assert "GROUND TRUTH" in injection


# ── Serialization ────────────────────────────────────────

class TestSerialization:
    def test_to_dict(self):
        store = MemoryStore()
        store.set_working_memory(["w1"])
        store.set_long_term_memory(["lt1"])
        d = store.to_dict()
        assert d == {"working_memory": ["w1"], "long_term_memory": ["lt1"]}

    def test_to_dict_empty(self):
        store = MemoryStore()
        assert store.to_dict() == {"working_memory": [], "long_term_memory": []}


# ── Persistence ──────────────────────────────────────────

class TestPersistence:
    def test_save_and_load(self):
        store = MemoryStore()
        store.set_working_memory(["w1", "w2"])
        store.set_long_term_memory(["lt1"])

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            original = MemoryStore.get_storage_path
            MemoryStore.get_storage_path = classmethod(lambda cls: path)

            store.save()

            loaded = MemoryStore.load()
            assert loaded.working_memory == ["w1", "w2"]
            assert loaded.long_term_memory == ["lt1"]
        finally:
            MemoryStore.get_storage_path = original
            os.unlink(path)

    def test_load_missing_file(self):
        original = MemoryStore.get_storage_path
        MemoryStore.get_storage_path = classmethod(lambda cls: "/nonexistent/path.json")
        try:
            store = MemoryStore.load()
            assert store.working_memory == []
            assert store.long_term_memory == []
        finally:
            MemoryStore.get_storage_path = original
