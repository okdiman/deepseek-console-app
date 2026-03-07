"""Unit tests for ChatSession — CRUD, trim, clone, compression, persistence."""
import json
import os
import tempfile

import pytest

from deepseek_chat.core.session import ChatSession


# ── Fixtures ─────────────────────────────────────────────

@pytest.fixture
def session():
    return ChatSession(max_messages=40)


@pytest.fixture
def small_session():
    """Session with max_messages=4 — useful for testing trim."""
    return ChatSession(max_messages=4)


@pytest.fixture
def populated(session):
    session.add_user("Hello")
    session.add_assistant("Hi there")
    session.add_user("How are you?")
    session.add_assistant("I'm good!")
    return session


# ── Defaults ─────────────────────────────────────────────

class TestDefaults:
    def test_empty_on_init(self, session):
        assert session.messages() == []
        assert session.summary == ""

    def test_updated_at_is_set(self, session):
        assert session.updated_at.endswith("Z")


# ── Add messages ─────────────────────────────────────────

class TestAddMessages:
    def test_add_user(self, session):
        session.add_user("Hello")
        assert session.messages() == [{"role": "user", "content": "Hello"}]

    def test_add_assistant(self, session):
        session.add_assistant("Hi")
        assert session.messages() == [{"role": "assistant", "content": "Hi"}]

    def test_add_preserves_order(self, populated):
        msgs = populated.messages()
        assert len(msgs) == 4
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "user"
        assert msgs[3]["role"] == "assistant"

    def test_messages_returns_copy(self, populated):
        msgs = populated.messages()
        msgs.append({"role": "user", "content": "extra"})
        assert len(populated.messages()) == 4  # original unchanged


# ── Clear ────────────────────────────────────────────────

class TestClear:
    def test_clear_messages(self, populated):
        populated.clear()
        assert populated.messages() == []

    def test_clear_summary(self, populated):
        populated.summary = "some summary"
        populated.clear()
        assert populated.summary == ""


# ── Trim ─────────────────────────────────────────────────

class TestTrim:
    def test_auto_trim_on_add(self, small_session):
        for i in range(6):
            small_session.add_user(f"msg {i}")
        assert len(small_session.messages()) == 4

    def test_trim_keeps_newest(self, small_session):
        for i in range(6):
            small_session.add_user(f"msg {i}")
        msgs = small_session.messages()
        assert msgs[0]["content"] == "msg 2"
        assert msgs[-1]["content"] == "msg 5"


# ── Clone ────────────────────────────────────────────────

class TestClone:
    def test_full_clone(self, populated):
        clone = populated.clone()
        assert clone.messages() == populated.messages()
        assert clone.summary == populated.summary

    def test_clone_is_independent(self, populated):
        clone = populated.clone()
        clone.add_user("extra")
        assert len(populated.messages()) == 4
        assert len(clone.messages()) == 5

    def test_clone_up_to_index(self, populated):
        clone = populated.clone(up_to_index=2)
        assert len(clone.messages()) == 2
        assert clone.messages()[0]["content"] == "Hello"

    def test_clone_up_to_zero_no_summary(self, populated):
        populated.summary = "test summary"
        clone = populated.clone(up_to_index=0)
        assert clone.messages() == []
        assert clone.summary == ""


# ── Compression ──────────────────────────────────────────

class TestCompression:
    def test_apply_compression(self, populated):
        populated.apply_compression("compressed summary", keep_count=2)
        assert populated.summary == "compressed summary"
        assert len(populated.messages()) == 2

    def test_compression_keeps_newest(self, populated):
        populated.apply_compression("s", keep_count=2)
        msgs = populated.messages()
        assert msgs[0]["content"] == "How are you?"
        assert msgs[1]["content"] == "I'm good!"

    def test_compression_keep_zero(self, populated):
        populated.apply_compression("all gone", keep_count=0)
        assert populated.messages() == []
        assert populated.summary == "all gone"


# ── Persistence ──────────────────────────────────────────

class TestPersistence:
    def test_save_and_load(self, populated):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            populated.summary = "test summary"
            populated.save(path, "deepseek", "deepseek-chat")

            loaded = ChatSession()
            loaded.load(path)
            assert loaded.messages() == populated.messages()
            assert loaded.summary == "test summary"
        finally:
            os.unlink(path)

    def test_save_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "dir", "context.json")
            s = ChatSession()
            s.add_user("hello")
            s.save(path, "deepseek", "deepseek-chat")
            assert os.path.exists(path)

    def test_load_missing_file(self, session):
        session.load("/nonexistent/path.json")
        assert session.messages() == []

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("not valid json{{{")
            path = f.name
        try:
            s = ChatSession()
            s.load(path)
            assert s.messages() == []
            assert s.summary == ""
        finally:
            os.unlink(path)

    def test_load_filters_invalid_messages(self):
        payload = {
            "format_version": 1,
            "summary": "",
            "messages": [
                {"role": "user", "content": "valid"},
                {"role": "system", "content": "should be filtered"},
                {"role": "user"},  # missing content
                {"role": "assistant", "content": "also valid"},
                "not a dict",
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(payload, f)
            path = f.name
        try:
            s = ChatSession()
            s.load(path)
            msgs = s.messages()
            assert len(msgs) == 2
            assert msgs[0] == {"role": "user", "content": "valid"}
            assert msgs[1] == {"role": "assistant", "content": "also valid"}
        finally:
            os.unlink(path)

    def test_save_empty_path(self, session):
        session.save("", None, None)  # should not crash

    def test_load_empty_path(self, session):
        session.load("")  # should not crash
        assert session.messages() == []
