"""Unit tests for mcp_servers/scheduler_store.py"""

import os
import tempfile
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp_servers'))

from scheduler import scheduler_store as store


@pytest.fixture
def db_path():
    """Create a temporary database for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store.init_db(path)
    yield path
    os.unlink(path)


class TestInitDB:
    def test_creates_tables(self, db_path):
        """init_db should create tasks and task_results tables."""
        import sqlite3
        conn = sqlite3.connect(db_path)
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "tasks" in tables
        assert "task_results" in tables


class TestAddTask:
    def test_add_reminder(self, db_path):
        task = store.add_task(
            task_type="reminder",
            name="Test reminder",
            schedule="once",
            payload={"text": "hello"},
            db_path=db_path,
        )
        assert task["type"] == "reminder"
        assert task["name"] == "Test reminder"
        assert task["status"] == "active"
        assert task["schedule"] == "once"
        assert task["id"]  # has an ID

    def test_add_periodic(self, db_path):
        task = store.add_task(
            task_type="periodic_collect",
            name="Collect data",
            schedule="every_5m",
            payload={"url": "https://example.com"},
            db_path=db_path,
        )
        assert task["type"] == "periodic_collect"
        assert task["schedule"] == "every_5m"


class TestGetTask:
    def test_get_existing(self, db_path):
        created = store.add_task("reminder", "Test", db_path=db_path)
        fetched = store.get_task(created["id"], db_path=db_path)
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_get_nonexistent(self, db_path):
        assert store.get_task("nonexistent", db_path=db_path) is None


class TestGetTasks:
    def test_filter_by_status(self, db_path):
        store.add_task("reminder", "A", db_path=db_path)
        t2 = store.add_task("reminder", "B", db_path=db_path)
        store.update_task(t2["id"], db_path=db_path, status="paused")

        active = store.get_tasks(status="active", db_path=db_path)
        paused = store.get_tasks(status="paused", db_path=db_path)
        all_tasks = store.get_tasks(db_path=db_path)

        assert len(active) == 1
        assert len(paused) == 1
        assert len(all_tasks) == 2

    def test_filter_by_type(self, db_path):
        store.add_task("reminder", "R", db_path=db_path)
        store.add_task("periodic_collect", "C", db_path=db_path)

        reminders = store.get_tasks(task_type="reminder", db_path=db_path)
        assert len(reminders) == 1
        assert reminders[0]["type"] == "reminder"


class TestUpdateTask:
    def test_update_status(self, db_path):
        task = store.add_task("reminder", "Test", db_path=db_path)
        assert store.update_task(task["id"], db_path=db_path, status="paused")
        updated = store.get_task(task["id"], db_path=db_path)
        assert updated["status"] == "paused"

    def test_update_disallowed_field(self, db_path):
        task = store.add_task("reminder", "Test", db_path=db_path)
        assert not store.update_task(task["id"], db_path=db_path, id="hacked")

    def test_update_no_fields(self, db_path):
        task = store.add_task("reminder", "Test", db_path=db_path)
        assert not store.update_task(task["id"], db_path=db_path)


class TestDeleteTask:
    def test_delete_existing(self, db_path):
        task = store.add_task("reminder", "Test", db_path=db_path)
        assert store.delete_task(task["id"], db_path=db_path)
        assert store.get_task(task["id"], db_path=db_path) is None

    def test_delete_nonexistent(self, db_path):
        assert not store.delete_task("nonexistent", db_path=db_path)

    def test_cascade_results(self, db_path):
        task = store.add_task("reminder", "Test", db_path=db_path)
        store.add_result(task["id"], "result1", db_path=db_path)
        store.add_result(task["id"], "result2", db_path=db_path)
        store.delete_task(task["id"], db_path=db_path)
        results = store.get_results(task["id"], db_path=db_path)
        assert len(results) == 0


class TestResults:
    def test_add_and_get(self, db_path):
        task = store.add_task("reminder", "Test", db_path=db_path)
        row_id = store.add_result(task["id"], "Hello world", db_path=db_path)
        assert row_id > 0

        results = store.get_results(task["id"], db_path=db_path)
        assert len(results) == 1
        assert results[0]["result"] == "Hello world"
        assert results[0]["task_id"] == task["id"]

    def test_limit(self, db_path):
        task = store.add_task("reminder", "Test", db_path=db_path)
        for i in range(5):
            store.add_result(task["id"], f"result_{i}", db_path=db_path)

        results = store.get_results(task["id"], limit=3, db_path=db_path)
        assert len(results) == 3


class TestAggregatedSummary:
    def test_empty_db(self, db_path):
        summary = store.get_aggregated_summary(db_path=db_path)
        assert summary["total_tasks"] == 0
        assert summary["active"] == 0
        assert summary["recent_results"] == []

    def test_with_data(self, db_path):
        t1 = store.add_task("reminder", "A", db_path=db_path)
        t2 = store.add_task("reminder", "B", db_path=db_path)
        store.update_task(t2["id"], db_path=db_path, status="completed")
        store.add_result(t1["id"], "r1", db_path=db_path)

        summary = store.get_aggregated_summary(db_path=db_path)
        assert summary["total_tasks"] == 2
        assert summary["active"] == 1
        assert summary["completed"] == 1
        assert len(summary["recent_results"]) == 1
        assert summary["recent_results"][0]["task_name"] == "A"
