"""Tests for mcp_servers/filesystem_server.py — two-phase filesystem tools."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Patch _PROJECT_ROOT to a tmp dir so tests never touch the real project
import mcp_servers.filesystem_server as fs_mod


@pytest.fixture(autouse=True)
def isolated_root(tmp_path, monkeypatch):
    """Redirect all filesystem_server operations to a temp directory."""
    monkeypatch.setattr(fs_mod, "_PROJECT_ROOT", tmp_path)
    fs_mod._pending.clear()
    yield tmp_path
    fs_mod._pending.clear()


# ── read_file ─────────────────────────────────────────────────────────────────���

def test_read_file_existing(isolated_root):
    (isolated_root / "hello.py").write_text("print('hi')")
    assert fs_mod.read_file("hello.py") == "print('hi')"


def test_read_file_not_found(isolated_root):
    result = fs_mod.read_file("nope.py")
    assert "not found" in result.lower()


def test_read_file_path_escape(isolated_root):
    result = fs_mod.read_file("../../etc/passwd")
    assert "escape" in result.lower() or "error" in result.lower()


# ── list_directory ───��────────────────────────────────────────────────────────

def test_list_directory_default(isolated_root):
    (isolated_root / "a.py").write_text("")
    (isolated_root / "b.md").write_text("")
    result = fs_mod.list_directory()
    assert "a.py" in result
    assert "b.md" in result


def test_list_directory_pattern(isolated_root):
    (isolated_root / "a.py").write_text("")
    (isolated_root / "b.md").write_text("")
    result = fs_mod.list_directory(pattern="*.py")
    assert "a.py" in result
    assert "b.md" not in result


def test_list_directory_skips_pycache(isolated_root):
    (isolated_root / "__pycache__").mkdir()
    (isolated_root / "__pycache__" / "x.pyc").write_text("")
    result = fs_mod.list_directory()
    assert "__pycache__" not in result


# ── search_in_files ──���────────────────────────────────────────────────────────

def test_search_finds_match(isolated_root):
    (isolated_root / "foo.py").write_text("class MyClass:\n    pass\n")
    result = fs_mod.search_in_files("MyClass", glob="*.py")
    assert "foo.py" in result
    assert "MyClass" in result


def test_search_no_match(isolated_root):
    (isolated_root / "foo.py").write_text("x = 1\n")
    result = fs_mod.search_in_files("ZZZ_NOTFOUND", glob="*.py")
    assert "No matches" in result


def test_search_invalid_regex(isolated_root):
    result = fs_mod.search_in_files("[invalid")
    assert "Invalid regex" in result


# ── propose_write ─────────────────────────────────────────────────────────────

def test_propose_write_new_file(isolated_root):
    result = fs_mod.propose_write("new.py", "x = 1\n")
    assert "create" in result.lower()
    assert len(fs_mod._pending) == 1


def test_propose_write_existing_file(isolated_root):
    (isolated_root / "existing.py").write_text("x = 1\n")
    result = fs_mod.propose_write("existing.py", "x = 2\n")
    assert "overwrite" in result.lower()
    assert "-x = 1" in result or "x = 1" in result


def test_propose_write_returns_proposal_id(isolated_root):
    result = fs_mod.propose_write("f.py", "pass\n")
    pid = list(fs_mod._pending.keys())[0]
    assert pid in result
    assert len(pid) == 8


def test_propose_write_path_escape(isolated_root):
    result = fs_mod.propose_write("../../evil.py", "bad")
    assert "escape" in result.lower() or "error" in result.lower()
    assert len(fs_mod._pending) == 0


# ── propose_edit ──────────────────────────────────────────────────────────────

def test_propose_edit_found(isolated_root):
    (isolated_root / "code.py").write_text("x = 1\ny = 2\n")
    result = fs_mod.propose_edit("code.py", "x = 1", "x = 99")
    assert "edit" in result.lower()
    assert len(fs_mod._pending) == 1


def test_propose_edit_not_found(isolated_root):
    (isolated_root / "code.py").write_text("x = 1\n")
    result = fs_mod.propose_edit("code.py", "ZZZ", "AAA")
    assert "not found" in result.lower()
    assert len(fs_mod._pending) == 0


def test_propose_edit_ambiguous(isolated_root):
    (isolated_root / "code.py").write_text("x = 1\nx = 1\n")
    result = fs_mod.propose_edit("code.py", "x = 1", "x = 2")
    assert "2 times" in result
    assert len(fs_mod._pending) == 0


def test_propose_edit_file_not_found(isolated_root):
    result = fs_mod.propose_edit("ghost.py", "old", "new")
    assert "not found" in result.lower()


# ── propose_delete ────────────────────────────────────────────────────────────

def test_propose_delete_existing(isolated_root):
    (isolated_root / "del.py").write_text("")
    result = fs_mod.propose_delete("del.py")
    assert "delete" in result.lower()
    assert len(fs_mod._pending) == 1
    assert (isolated_root / "del.py").exists()  # not deleted yet


def test_propose_delete_not_found(isolated_root):
    result = fs_mod.propose_delete("ghost.py")
    assert "not found" in result.lower()
    assert len(fs_mod._pending) == 0


# ── apply_change ──────────────────────────────────────────────────────────────

def test_apply_write_creates_file(isolated_root):
    fs_mod.propose_write("new.py", "hello\n")
    pid = list(fs_mod._pending.keys())[0]
    result = fs_mod.apply_change(pid)
    assert "✅" in result
    assert (isolated_root / "new.py").read_text() == "hello\n"
    assert len(fs_mod._pending) == 0


def test_apply_edit_modifies_file(isolated_root):
    (isolated_root / "code.py").write_text("x = 1\n")
    fs_mod.propose_edit("code.py", "x = 1", "x = 99")
    pid = list(fs_mod._pending.keys())[0]
    fs_mod.apply_change(pid)
    assert (isolated_root / "code.py").read_text() == "x = 99\n"


def test_apply_delete_removes_file(isolated_root):
    f = isolated_root / "bye.py"
    f.write_text("bye")
    fs_mod.propose_delete("bye.py")
    pid = list(fs_mod._pending.keys())[0]
    fs_mod.apply_change(pid)
    assert not f.exists()


def test_apply_unknown_id(isolated_root):
    result = fs_mod.apply_change("deadbeef")
    assert "not found" in result.lower()


def test_apply_consumes_proposal(isolated_root):
    fs_mod.propose_write("f.py", "x\n")
    pid = list(fs_mod._pending.keys())[0]
    fs_mod.apply_change(pid)
    # second apply should fail
    result = fs_mod.apply_change(pid)
    assert "not found" in result.lower()


# ── discard_change ────────────────────────────────────────────────────────────

def test_discard_removes_proposal(isolated_root):
    fs_mod.propose_write("f.py", "x\n")
    pid = list(fs_mod._pending.keys())[0]
    result = fs_mod.discard_change(pid)
    assert "discarded" in result.lower()
    assert len(fs_mod._pending) == 0


def test_discard_unknown_id(isolated_root):
    result = fs_mod.discard_change("deadbeef")
    assert "not found" in result.lower()


# ── list_pending_changes ──────────────────────────────────────────────────────

def test_list_pending_empty(isolated_root):
    result = fs_mod.list_pending_changes()
    assert "no pending" in result.lower()


def test_list_pending_shows_proposals(isolated_root):
    fs_mod.propose_write("a.py", "x\n")
    fs_mod.propose_write("b.py", "y\n")
    result = fs_mod.list_pending_changes()
    assert "a.py" in result
    assert "b.py" in result


# ── write creates parent dirs ─────────────────────────────────────────────────

def test_apply_write_creates_parent_dirs(isolated_root):
    fs_mod.propose_write("deep/nested/file.py", "content\n")
    pid = list(fs_mod._pending.keys())[0]
    fs_mod.apply_change(pid)
    assert (isolated_root / "deep" / "nested" / "file.py").read_text() == "content\n"
