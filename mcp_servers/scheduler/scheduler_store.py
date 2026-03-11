"""
SQLite persistence layer for the Scheduler MCP server.
Stores tasks (reminders, periodic jobs) and their execution results.
"""

import json
import sqlite3
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


DB_PATH = os.path.expanduser("~/.deepseek_chat/scheduler.db")


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Create tables if they don't exist."""
    _ensure_dir()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL,
            name        TEXT NOT NULL,
            payload     TEXT NOT NULL DEFAULT '{}',
            schedule    TEXT NOT NULL DEFAULT 'once',
            next_run_at TEXT,
            last_run_at TEXT,
            status      TEXT NOT NULL DEFAULT 'active',
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS task_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     TEXT NOT NULL,
            result      TEXT NOT NULL,
            executed_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


# ── Helpers ──────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


# ── CRUD: Tasks ──────────────────────────────────────────

def add_task(
    task_type: str,
    name: str,
    schedule: str = "once",
    payload: Optional[Dict[str, Any]] = None,
    next_run_at: Optional[str] = None,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    """Create a new scheduled task. Returns the created task dict."""
    task_id = str(uuid.uuid4())[:8]
    now = _now_iso()
    payload_json = json.dumps(payload or {}, ensure_ascii=False)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """INSERT INTO tasks (id, type, name, payload, schedule, next_run_at, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'active', ?)""",
        (task_id, task_type, name, payload_json, schedule, next_run_at or now, now),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def get_task(task_id: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Get a single task by ID."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def get_tasks(
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """Get all tasks, optionally filtered by status and/or type."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM tasks WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if task_type:
        query += " AND type = ?"
        params.append(task_type)
    query += " ORDER BY created_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def update_task(task_id: str, db_path: str = DB_PATH, **fields) -> bool:
    """Update specific fields of a task. Returns True if row was updated."""
    if not fields:
        return False
    allowed = {"status", "next_run_at", "last_run_at", "payload", "schedule", "name"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [task_id]

    conn = sqlite3.connect(db_path)
    cur = conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def delete_task(task_id: str, db_path: str = DB_PATH) -> bool:
    """Delete a task and its results."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


# ── CRUD: Results ────────────────────────────────────────

def add_result(task_id: str, result: str, db_path: str = DB_PATH) -> int:
    """Record an execution result for a task. Returns the result row id."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO task_results (task_id, result, executed_at) VALUES (?, ?, ?)",
        (task_id, result, _now_iso()),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id  # type: ignore[return-value]


def get_results(
    task_id: str, limit: int = 20, db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """Get execution results for a task, newest first."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM task_results WHERE task_id = ? ORDER BY executed_at DESC LIMIT ?",
        (task_id, limit),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_aggregated_summary(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return an aggregated summary across all tasks."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) as cnt FROM tasks").fetchone()["cnt"]
    active = conn.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status='active'").fetchone()["cnt"]
    paused = conn.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status='paused'").fetchone()["cnt"]
    completed = conn.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status='completed'").fetchone()["cnt"]

    # Last 10 results across all tasks
    recent = conn.execute("""
        SELECT tr.*, t.name as task_name, t.type as task_type
        FROM task_results tr
        JOIN tasks t ON t.id = tr.task_id
        ORDER BY tr.executed_at DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    return {
        "total_tasks": total,
        "active": active,
        "paused": paused,
        "completed": completed,
        "recent_results": [_row_to_dict(r) for r in recent],
    }


def get_results_since(since_iso: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get all results executed after the given ISO timestamp, with task info."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT tr.*, t.name as task_name, t.type as task_type
        FROM task_results tr
        JOIN tasks t ON t.id = tr.task_id
        WHERE tr.executed_at > ?
        ORDER BY tr.executed_at ASC
    """, (since_iso,)).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]
