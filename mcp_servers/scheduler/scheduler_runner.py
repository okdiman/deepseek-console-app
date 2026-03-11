"""
Background scheduler runner.
Periodically checks the SQLite tasks table and executes due tasks.
Runs as an asyncio background task inside the MCP server process.
"""

import asyncio
import json
import logging
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

import sys
import os
# Add the scheduler package directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scheduler_store as store

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 30


# ── Schedule parsing ─────────────────────────────────────

def compute_next_run(schedule: str, from_time: Optional[datetime] = None) -> Optional[str]:
    """
    Compute the next run time based on a simplified schedule string.
    Supported formats:
      - 'once'           → None (no next run)
      - 'every_Nm'       → N minutes from now  (e.g. every_5m)
      - 'every_Nh'       → N hours from now     (e.g. every_1h)
      - 'daily_HH:MM'    → next occurrence of HH:MM UTC
    """
    now = from_time or datetime.now(timezone.utc)

    if schedule == "once":
        return None

    # every_Nm
    m = re.match(r"^every_(\d+)m$", schedule)
    if m:
        minutes = int(m.group(1))
        return (now + timedelta(minutes=minutes)).isoformat()

    # every_Nh
    m = re.match(r"^every_(\d+)h$", schedule)
    if m:
        hours = int(m.group(1))
        return (now + timedelta(hours=hours)).isoformat()

    # daily_HH:MM
    m = re.match(r"^daily_(\d{2}):(\d{2})$", schedule)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.isoformat()

    logger.warning(f"Unknown schedule format: {schedule}")
    return None


# ── Task executors ───────────────────────────────────────

def _execute_reminder(task: dict) -> str:
    """Execute a reminder task — simply returns the reminder text."""
    payload = json.loads(task["payload"]) if isinstance(task["payload"], str) else task["payload"]
    text = payload.get("text", "(без текста)")
    return f"🔔 Напоминание: {text}"


def _execute_periodic_collect(task: dict) -> str:
    """Execute a periodic data collection — runs an AI agent prompt in the background."""
    payload = json.loads(task["payload"]) if isinstance(task["payload"], str) else task["payload"]
    prompt = payload.get("prompt", "")
    if not prompt:
        # Fallback for old tasks that used "url" instead of "prompt"
        url = payload.get("url", "")
        if url:
            prompt = f"Возьми данные с {url} и сделай краткую выжимку."
        else:
            return "❌ Промпт не указан в payload задачи"

    try:
        # Instead of running the LLM in this process (which creates a second isolated
        # instance of the entire web app and its MCP managers, causing infinite loops),
        # we ask the main running FastAPI application to execute the agent.
        req_data = json.dumps({
            "prompt": prompt,
            "max_length": payload.get("max_length", 4000)
        }).encode("utf-8")
        
        req = urllib.request.Request(
            "http://127.0.0.1:8000/scheduler/execute_agent",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        # We give it a generous timeout because Agent execution takes a while
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read().decode("utf-8")
            result = json.loads(data)
            
            if not result.get("ok"):
                error_msg = result.get("error", "Unknown error")
                return f"❌ Ошибка агента: {error_msg}"
                
            return f"🤖 Результат:\n{result.get('text', '')}"
            
    except Exception as e:
        logger.error("Error executing periodic_collect agent task: %s", e, exc_info=True)
        return f"❌ Ошибка вызова AI-агента (возможно, локальный сервер не запущен): {e}"

def _execute_periodic_summary(task: dict) -> str:
    """Execute a summary task — aggregates recent results for a target task."""
    payload = json.loads(task["payload"]) if isinstance(task["payload"], str) else task["payload"]
    target_task_id = payload.get("target_task_id", "")

    if target_task_id:
        results = store.get_results(target_task_id, limit=50)
        if not results:
            return "📋 Нет данных для сводки"
        summary_lines = [f"📋 Сводка по задаче {target_task_id} ({len(results)} записей):"]
        for r in results[:10]:
            summary_lines.append(f"  • [{r['executed_at']}] {r['result'][:200]}")
        if len(results) > 10:
            summary_lines.append(f"  ... и ещё {len(results) - 10} записей")
        return "\n".join(summary_lines)
    else:
        # General summary across all tasks
        agg = store.get_aggregated_summary()
        lines = [
            f"📋 Общая сводка планировщика:",
            f"  Всего задач: {agg['total_tasks']}",
            f"  Активных: {agg['active']} | На паузе: {agg['paused']} | Завершено: {agg['completed']}",
        ]
        if agg["recent_results"]:
            lines.append(f"  Последние результаты:")
            for r in agg["recent_results"][:5]:
                lines.append(f"    • [{r['task_name']}] {r['result'][:150]}")
        return "\n".join(lines)


_EXECUTORS = {
    "reminder": _execute_reminder,
    "periodic_collect": _execute_periodic_collect,
    "periodic_summary": _execute_periodic_summary,
}


# ── Main runner loop ─────────────────────────────────────

async def run_scheduler_loop(db_path: str = store.DB_PATH) -> None:
    """
    Main scheduler loop. Checks for due tasks every CHECK_INTERVAL_SECONDS
    and executes them.
    """
    logger.info("Scheduler runner started (interval=%ds)", CHECK_INTERVAL_SECONDS)
    store.init_db(db_path)

    while True:
        try:
            await _tick(db_path)
        except Exception as e:
            logger.error("Scheduler tick error: %s", e, exc_info=True)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _tick(db_path: str = store.DB_PATH) -> None:
    """Single scheduler tick: find and execute all due tasks."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    tasks = store.get_tasks(status="active", db_path=db_path)

    for task in tasks:
        next_run = task.get("next_run_at")
        if not next_run:
            continue

        # Is it time to run?
        if next_run > now_iso:
            continue

        task_id = task["id"]
        task_type = task["type"]

        executor = _EXECUTORS.get(task_type)
        if not executor:
            logger.warning("No executor for task type: %s (task %s)", task_type, task_id)
            continue

        logger.info("Executing task %s (%s): %s", task_id, task_type, task["name"])

        # Run the executor (sync functions, run in thread to not block)
        try:
            result = await asyncio.to_thread(executor, task)
        except Exception as e:
            result = f"❌ Ошибка выполнения: {e}"
            logger.error("Task %s execution failed: %s", task_id, e)

        # Save result
        store.add_result(task_id, result, db_path=db_path)

        # Update task timing
        schedule = task.get("schedule", "once")
        if schedule == "once":
            store.update_task(task_id, db_path=db_path, status="completed", last_run_at=now_iso)
            logger.info("One-time task %s completed", task_id)
        else:
            next_run_new = compute_next_run(schedule, from_time=now)
            store.update_task(
                task_id, db_path=db_path,
                last_run_at=now_iso,
                next_run_at=next_run_new,
            )
            logger.info("Periodic task %s next run: %s", task_id, next_run_new)
