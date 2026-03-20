# Scheduler — How It Works

The scheduler is a background task system built on top of MCP. It consists of three parts: an MCP tool server (the interface), a runner loop (the execution engine), and a SQLite store (persistence).

---

## Components

```
mcp_servers/scheduler/
├── scheduler_server.py  — MCP tool server: exposes tools to the LLM
├── scheduler_runner.py  — background loop: finds and executes due tasks
├── scheduler_store.py   — SQLite persistence layer
└── scheduler_utils.py  — compute_next_run(): schedule string parser
```

---

## Architecture

```
Web app lifespan (app.py)
    │
    ├── starts MCPManager → spawns scheduler_server.py as subprocess
    │       (agent can now call scheduler tools)
    │
    └── starts run_scheduler_loop() as asyncio background task
            │
            every 30s: _tick()
                │
                ├── queries SQLite for due active tasks
                └── executes each task in parallel (max 3 concurrent)
                        │
                        ├── reminder         → returns text immediately
                        ├── periodic_collect → runs BackgroundAgent with prompt
                        └── periodic_summary → aggregates stored results
```

Both `scheduler_server.py` and `scheduler_runner.py` read/write the **same SQLite database** (WAL mode for concurrent access).

---

## scheduler_store.py — SQLite schema

**Path:** `~/.deepseek_chat/scheduler.db` (or `DEEPSEEK_DATA_DIR/scheduler.db`)

```sql
tasks (
    id          TEXT PRIMARY KEY,   -- 8-char UUID prefix
    type        TEXT,               -- reminder | periodic_collect | periodic_summary
    name        TEXT,
    payload     TEXT,               -- JSON: task-type-specific data
    schedule    TEXT,               -- once | every_Nm | every_Nh | daily_HH:MM
    next_run_at TEXT,               -- ISO 8601 UTC
    last_run_at TEXT,
    status      TEXT,               -- active | paused | completed | failed
    created_at  TEXT
)

task_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    result      TEXT,               -- text output of the execution
    executed_at TEXT                -- ISO 8601 UTC
)
```

WAL journal mode is always enabled. Foreign keys cascade: deleting a task removes all its results.

---

## scheduler_utils.py — Schedule formats

`compute_next_run(schedule, from_time)` parses schedule strings:

| Format | Example | Meaning |
|--------|---------|---------|
| `once` | `once` | No next run after first execution |
| `every_Nm` | `every_5m` | Every N minutes |
| `every_Nh` | `every_1h` | Every N hours |
| `daily_HH:MM` | `daily_09:00` | Daily at HH:MM UTC |

Returns an ISO 8601 string or `None` (for `once`). Used both when creating a task (initial `next_run_at`) and after each execution (computing the next one).

---

## scheduler_server.py — MCP tools

Runs as an MCP subprocess. Exposes 8 tools to the LLM:

| Tool | Description |
|------|-------------|
| `create_reminder(text, delay_minutes, schedule, name)` | Create a reminder, fires after `delay_minutes` |
| `create_periodic_task(task_type, name, schedule, prompt, target_task_id)` | Create a periodic collect or summary task |
| `list_tasks(status, task_type)` | List all tasks, optionally filtered |
| `get_task_results(task_id, limit)` | Get last N execution results for a task |
| `get_summary()` | Aggregated stats: counts + recent results across all tasks |
| `pause_task(task_id)` | Pause an active task |
| `resume_task(task_id)` | Resume a paused task |
| `delete_task(task_id)` | Delete a task and all its results |

**Entry point:** `if __name__ == "__main__": store.init_db(); mcp.run()`

The server is stateless — it writes to SQLite and returns formatted strings. All scheduling logic lives in the runner.

---

## scheduler_runner.py — Execution loop

`run_scheduler_loop(db_path, client, manager)` is the main entry point.

**Tick interval:** 30 seconds (`CHECK_INTERVAL_SECONDS`)

**Concurrency:** max 3 simultaneous LLM calls (`_AI_CONCURRENCY` semaphore)

### Tick logic

```
_tick()
  1. SELECT active tasks WHERE next_run_at <= now
  2. asyncio.gather(*[_run_single_task(t) for t in due])
```

### Per-task execution

```
_run_single_task()
  1. Acquire semaphore slot
  2. Dispatch to executor by task type
  3. Release semaphore
  4. store.add_result(task_id, result)
  5. If schedule == "once": mark completed
     Else: compute_next_run() → update next_run_at
```

### Task executors

**`reminder`** — returns the payload `text` directly, no LLM call.

**`periodic_collect`** — creates a fresh `BackgroundAgent` + `ChatSession` per execution (no context bleed between runs), calls `stream_reply(prompt)`, stores the response. `client` and `manager` are passed in from the web app lifespan to avoid re-initialization.

**`periodic_summary`** — reads stored results from SQLite (for a specific task or aggregated) and formats them as a summary string. No LLM call.

### Two run modes

| Mode | How | When |
|------|-----|------|
| **Embedded** | `web/app.py` calls `run_scheduler_loop(client=client, manager=manager)` in lifespan | Normal web app usage |
| **Standalone** | `python3 mcp_servers/scheduler/scheduler_runner.py` | Debugging / running without web UI |

In standalone mode, the runner builds its own `DeepSeekClient` and `MCPManager` via `agent_factory`.

---

## Payload formats

```json
// reminder
{"text": "Buy groceries"}

// periodic_collect
{"prompt": "Summarize top 5 Hacker News stories", "max_length": 4000}

// periodic_summary
{"target_task_id": "abc12345"}   // omit for global summary
```

---

## Not cleared on /clear

The scheduler database is independent of the chat session. `/clear` only clears conversation history and dialogue task memory — scheduled tasks and their results persist.
