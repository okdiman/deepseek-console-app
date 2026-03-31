"""Tests for deepseek_chat/core/change_store.py — persistence and concurrent access."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import deepseek_chat.core.change_store as cs
from deepseek_chat.core.change_store import Proposal


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    store_path = tmp_path / "pending_changes.json"
    monkeypatch.setattr(cs, "_STORE_PATH", store_path)
    yield store_path
    if store_path.exists():
        store_path.unlink()
    lock = Path(str(store_path) + ".lock")
    if lock.exists():
        lock.unlink()


# ── Basic CRUD ────────────────────────────────────────────────────────────────

def test_add_and_get():
    p = Proposal(id="abc12345", kind="write", path="foo.py", preview="+x=1", content="x=1\n")
    cs.add(p)
    result = cs.get("abc12345")
    assert result is not None
    assert result.id == "abc12345"
    assert result.kind == "write"
    assert result.content == "x=1\n"


def test_get_missing_returns_none():
    assert cs.get("deadbeef") is None


def test_remove_existing():
    p = Proposal(id="rm000001", kind="delete", path="bye.py", preview="Delete file: bye.py")
    cs.add(p)
    assert cs.remove("rm000001") is True
    assert cs.get("rm000001") is None


def test_remove_missing_returns_false():
    assert cs.remove("nope0000") is False


def test_list_all_empty():
    assert cs.list_all() == []


def test_list_all_multiple():
    cs.add(Proposal(id="id000001", kind="write", path="a.py", preview="+a", content="a\n"))
    cs.add(Proposal(id="id000002", kind="delete", path="b.py", preview="Delete b.py"))
    ids = {p.id for p in cs.list_all()}
    assert ids == {"id000001", "id000002"}


def test_clear_removes_file(isolated_store):
    cs.add(Proposal(id="cl000001", kind="write", path="x.py", preview="+x", content="x\n"))
    assert isolated_store.exists()
    cs.clear()
    assert not isolated_store.exists()


# ── Persistence (survives reload) ─────────────────────────────────────────────

def test_persists_across_reload(isolated_store):
    cs.add(Proposal(id="persist1", kind="write", path="p.py", preview="+p", content="p\n"))
    # reload by reading the raw file via a fresh _load call
    result = cs.get("persist1")
    assert result is not None
    assert result.path == "p.py"


# ── Concurrent access ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_adds_no_data_loss():
    """Five concurrent coroutines each adding one proposal — all must survive."""
    proposals = [
        Proposal(id=f"conc{i:04d}", kind="write", path=f"file{i}.py", preview=f"+{i}", content=f"{i}\n")
        for i in range(5)
    ]

    async def add_one(p: Proposal) -> None:
        await asyncio.get_event_loop().run_in_executor(None, cs.add, p)

    await asyncio.gather(*[add_one(p) for p in proposals])

    stored_ids = {p.id for p in cs.list_all()}
    expected_ids = {p.id for p in proposals}
    assert stored_ids == expected_ids, f"Missing: {expected_ids - stored_ids}"
