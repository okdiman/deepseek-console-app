"""Unit tests for UserProfile — defaults, is_empty, serialization, persistence."""
import json
import os
import tempfile

import pytest

from deepseek_chat.core.profile import UserProfile


# ── Defaults ─────────────────────────────────────────────

class TestDefaults:
    def test_empty_on_init(self):
        profile = UserProfile()
        assert profile.name == ""
        assert profile.role == ""
        assert profile.style_preferences == ""
        assert profile.formatting_rules == ""
        assert profile.constraints == ""

    def test_is_empty_true(self):
        assert UserProfile().is_empty() is True


# ── is_empty ─────────────────────────────────────────────

class TestIsEmpty:
    @pytest.mark.parametrize("field", [
        "name", "role", "style_preferences", "formatting_rules", "constraints"
    ])
    def test_any_field_makes_not_empty(self, field):
        profile = UserProfile(**{field: "something"})
        assert profile.is_empty() is False

    def test_all_fields_filled(self):
        profile = UserProfile(
            name="Dmitriy",
            role="Developer",
            style_preferences="concise",
            formatting_rules="markdown",
            constraints="Russian lang"
        )
        assert profile.is_empty() is False


# ── Serialization ────────────────────────────────────────

class TestSerialization:
    def test_model_dump_contains_all_fields(self):
        profile = UserProfile(name="Test", role="Dev")
        d = profile.model_dump()
        assert d["name"] == "Test"
        assert d["role"] == "Dev"
        assert "style_preferences" in d
        assert "formatting_rules" in d
        assert "constraints" in d

    def test_roundtrip(self):
        original = UserProfile(name="A", role="B", constraints="C")
        restored = UserProfile(**original.model_dump())
        assert restored == original


# ── Persistence ──────────────────────────────────────────

class TestPersistence:
    def test_save_and_load(self):
        profile = UserProfile(name="Dmitriy", role="Android Dev")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            original = UserProfile.get_storage_path
            UserProfile.get_storage_path = classmethod(lambda cls: path)

            profile.save()

            loaded = UserProfile.load()
            assert loaded.name == "Dmitriy"
            assert loaded.role == "Android Dev"
        finally:
            UserProfile.get_storage_path = original
            os.unlink(path)

    def test_load_missing_file(self):
        original = UserProfile.get_storage_path
        UserProfile.get_storage_path = classmethod(lambda cls: "/nonexistent/path.json")
        try:
            profile = UserProfile.load()
            assert profile.is_empty() is True
        finally:
            UserProfile.get_storage_path = original
