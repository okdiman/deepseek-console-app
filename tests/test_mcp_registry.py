"""Unit tests for deepseek_chat/core/mcp_registry.py — MCPRegistry CRUD and persistence."""

import os
import pytest

from deepseek_chat.core.mcp import MCPRegistry, MCPServerConfig


def make_config(server_id="srv1", name="Test Server", enabled=True):
    return MCPServerConfig(
        id=server_id, name=name, command="python", args=["script.py"], enabled=enabled
    )


# ── CRUD ─────────────────────────────────────────────────

class TestCRUD:
    def test_empty_on_init(self):
        r = MCPRegistry()
        assert r.get_all() == []

    def test_add_server(self):
        r = MCPRegistry()
        r.add_server(make_config())
        assert len(r.get_all()) == 1

    def test_add_multiple_distinct_ids(self):
        r = MCPRegistry()
        r.add_server(make_config(server_id="a"))
        r.add_server(make_config(server_id="b"))
        assert len(r.get_all()) == 2

    def test_add_replaces_existing_id(self):
        r = MCPRegistry()
        r.add_server(make_config(server_id="x", name="Old"))
        r.add_server(make_config(server_id="x", name="New"))
        assert len(r.get_all()) == 1
        assert r.get_server("x").name == "New"

    def test_get_server_found(self):
        r = MCPRegistry()
        r.add_server(make_config(server_id="find_me"))
        result = r.get_server("find_me")
        assert result is not None
        assert result.id == "find_me"

    def test_get_server_not_found(self):
        r = MCPRegistry()
        assert r.get_server("ghost") is None

    def test_remove_server_returns_true(self):
        r = MCPRegistry()
        r.add_server(make_config(server_id="del"))
        assert r.remove_server("del") is True

    def test_remove_server_gone(self):
        r = MCPRegistry()
        r.add_server(make_config(server_id="del"))
        r.remove_server("del")
        assert r.get_server("del") is None

    def test_remove_nonexistent_returns_false(self):
        r = MCPRegistry()
        assert r.remove_server("nothing") is False

    def test_remove_leaves_other_servers(self):
        r = MCPRegistry()
        r.add_server(make_config(server_id="keep"))
        r.add_server(make_config(server_id="drop"))
        r.remove_server("drop")
        assert r.get_server("keep") is not None
        assert len(r.get_all()) == 1

    def test_get_all_returns_correct_count(self):
        r = MCPRegistry()
        r.add_server(make_config(server_id="a"))
        r.add_server(make_config(server_id="b"))
        assert len(r.get_all()) == 2


# ── Persistence ──────────────────────────────────────────

class TestPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "registry.json")
        r = MCPRegistry()
        r.add_server(make_config(server_id="saved", name="Saved Server"))
        r.save(path)

        r2 = MCPRegistry.load(path)
        assert r2.get_server("saved") is not None
        assert r2.get_server("saved").name == "Saved Server"

    def test_save_and_load_preserves_all_fields(self, tmp_path):
        path = str(tmp_path / "registry.json")
        cfg = MCPServerConfig(
            id="full", name="Full Server",
            command="node", args=["server.js", "--port", "3000"],
            env={"KEY": "VAL"}, enabled=False
        )
        r = MCPRegistry()
        r.add_server(cfg)
        r.save(path)

        r2 = MCPRegistry.load(path)
        loaded = r2.get_server("full")
        assert loaded.command == "node"
        assert loaded.args == ["server.js", "--port", "3000"]
        assert loaded.env == {"KEY": "VAL"}
        assert loaded.enabled is False

    def test_save_creates_nested_directories(self, tmp_path):
        path = str(tmp_path / "nested" / "dirs" / "registry.json")
        r = MCPRegistry()
        r.save(path)
        assert os.path.exists(path)

    def test_load_missing_file_creates_defaults(self, tmp_path):
        path = str(tmp_path / "new_dir" / "registry.json")
        r = MCPRegistry.load(path)
        ids = [s.id for s in r.get_all()]
        assert "local_demo" in ids
        assert "scheduler" in ids

    def test_load_missing_file_saves_defaults(self, tmp_path):
        path = str(tmp_path / "new_dir" / "registry.json")
        MCPRegistry.load(path)
        assert os.path.exists(path)

    def test_load_corrupt_json_returns_empty(self, tmp_path):
        path = str(tmp_path / "bad.json")
        with open(path, "w") as f:
            f.write("not valid json {{{")
        r = MCPRegistry.load(path)
        assert r.get_all() == []

    def test_load_multiple_servers(self, tmp_path):
        path = str(tmp_path / "multi.json")
        r = MCPRegistry()
        for i in range(3):
            r.add_server(make_config(server_id=f"s{i}", name=f"Server {i}"))
        r.save(path)

        r2 = MCPRegistry.load(path)
        assert len(r2.get_all()) == 3
