"""
Scheduler MCP Server — provides tools for creating and managing
scheduled tasks (reminders, periodic data collection, summaries).
Runs a background scheduler loop alongside the MCP stdio transport.
"""

import asyncio
import json
import logging
import sys
import os
from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

# Since this runs as a standalone script, we need direct imports
# Add parent directory so we can import sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scheduler_store as store
from scheduler_runner import run_scheduler_loop, compute_next_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("scheduler_server")

mcp = FastMCP("Scheduler Server")


# ── Helper ───────────────────────────────────────────────

def _format_task(t: dict) -> str:
    """Format a task dict into a readable string."""
    status_icons = {"active": "🟢", "paused": "⏸️", "completed": "✅", "failed": "❌"}
    icon = status_icons.get(t["status"], "❓")
    lines = [
        f"{icon} **{t['name']}** (`{t['id']}`)",
        f"   Тип: {t['type']} | Расписание: {t['schedule']} | Статус: {t['status']}",
    ]
    if t.get("next_run_at"):
        lines.append(f"   Следующий запуск: {t['next_run_at']}")
    if t.get("last_run_at"):
        lines.append(f"   Последний запуск: {t['last_run_at']}")
    return "\n".join(lines)


# ── MCP Tools ────────────────────────────────────────────

@mcp.tool()
def create_reminder(
    text: str,
    delay_minutes: int = 1,
    schedule: str = "once",
    name: str = "",
) -> str:
    """Создаёт напоминание. По умолчанию — однократное, через delay_minutes минут.
    Можно указать schedule для периодических: 'every_1m', 'every_5m', 'every_1h', 'daily_09:00'.
    text: Текст напоминания.
    delay_minutes: Через сколько минут первый раз сработает (по умолчанию 1).
    schedule: Расписание — 'once', 'every_Nm', 'every_Nh', 'daily_HH:MM'.
    name: Название напоминания (необязательно).
    """
    if not name:
        name = f"Напоминание: {text[:40]}"

    next_run = (datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)).isoformat()

    task = store.add_task(
        task_type="reminder",
        name=name,
        schedule=schedule,
        payload={"text": text},
        next_run_at=next_run,
    )
    return f"✅ Напоминание создано!\n\n{_format_task(task)}"


@mcp.tool()
def create_periodic_task(
    task_type: str = "periodic_collect",
    name: str = "Периодический сбор",
    schedule: str = "every_1m",
    prompt: str = "",
    target_task_id: str = "",
) -> str:
    """Создаёт периодическую задачу сбора данных или генерации сводки.
    task_type: 'periodic_collect' (сбор данных через AI) или 'periodic_summary' (генерация сводки).
    name: Название задачи.
    schedule: Расписание — 'every_1m', 'every_5m', 'every_30m', 'every_1h', 'daily_HH:MM'.
    prompt: Инструкция для искусственного интеллекта (только для periodic_collect). Например: 'Получи топ-10 статей с Hacker News'.
    target_task_id: ID задачи для сводки (только для periodic_summary, необязательно).
    """
    if task_type not in ("periodic_collect", "periodic_summary"):
        return "❌ task_type должен быть 'periodic_collect' или 'periodic_summary'"

    if task_type == "periodic_collect" and not prompt:
        return "❌ Для periodic_collect нужно указать prompt (задачу для агента)"

    payload = {}
    if prompt:
        payload["prompt"] = prompt
    if target_task_id:
        payload["target_task_id"] = target_task_id

    next_run = compute_next_run(schedule) or (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    task = store.add_task(
        task_type=task_type,
        name=name,
        schedule=schedule,
        payload=payload,
        next_run_at=next_run,
    )
    return f"✅ Периодическая задача создана!\n\n{_format_task(task)}"


@mcp.tool()
def list_tasks(status: str = "", task_type: str = "") -> str:
    """Показывает все задачи планировщика.
    status: Фильтр по статусу ('active', 'paused', 'completed'). Пустое = все.
    task_type: Фильтр по типу ('reminder', 'periodic_collect', 'periodic_summary'). Пустое = все.
    """
    tasks = store.get_tasks(
        status=status or None,
        task_type=task_type or None,
    )
    if not tasks:
        return "📋 Нет задач" + (f" со статусом '{status}'" if status else "")

    lines = [f"📋 Задачи планировщика ({len(tasks)}):"]
    for t in tasks:
        lines.append("")
        lines.append(_format_task(t))

    return "\n".join(lines)


@mcp.tool()
def get_task_results(task_id: str, limit: int = 10) -> str:
    """Возвращает последние результаты выполнения задачи.
    task_id: ID задачи.
    limit: Максимальное количество результатов (по умолчанию 10).
    """
    task = store.get_task(task_id)
    if not task:
        return f"❌ Задача с ID '{task_id}' не найдена"

    results = store.get_results(task_id, limit=limit)
    if not results:
        return f"📭 Нет результатов для задачи '{task['name']}'"

    lines = [f"📊 Результаты задачи '{task['name']}' (последние {len(results)}):"]
    for r in results:
        lines.append(f"\n🕐 {r['executed_at']}:")
        lines.append(r["result"])

    return "\n".join(lines)


@mcp.tool()
def get_summary() -> str:
    """Возвращает агрегированную сводку планировщика: статистику задач и последние результаты."""
    agg = store.get_aggregated_summary()

    lines = [
        "📊 **Сводка планировщика**",
        "",
        f"Всего задач: {agg['total_tasks']}",
        f"🟢 Активных: {agg['active']}",
        f"⏸️ На паузе: {agg['paused']}",
        f"✅ Завершено: {agg['completed']}",
    ]

    if agg["recent_results"]:
        lines.append("")
        lines.append("**Последние результаты:**")
        for r in agg["recent_results"]:
            lines.append(f"• [{r['task_name']}] {r['executed_at']}: {r['result'][:200]}")

    return "\n".join(lines)


@mcp.tool()
def pause_task(task_id: str) -> str:
    """Ставит задачу на паузу. Она не будет выполняться до возобновления.
    task_id: ID задачи.
    """
    task = store.get_task(task_id)
    if not task:
        return f"❌ Задача с ID '{task_id}' не найдена"
    if task["status"] != "active":
        return f"⚠️ Задача '{task['name']}' не активна (статус: {task['status']})"

    store.update_task(task_id, status="paused")
    return f"⏸️ Задача '{task['name']}' поставлена на паузу"


@mcp.tool()
def resume_task(task_id: str) -> str:
    """Возобновляет задачу, поставленную на паузу.
    task_id: ID задачи.
    """
    task = store.get_task(task_id)
    if not task:
        return f"❌ Задача с ID '{task_id}' не найдена"
    if task["status"] != "paused":
        return f"⚠️ Задача '{task['name']}' не на паузе (статус: {task['status']})"

    store.update_task(task_id, status="active")
    return f"▶️ Задача '{task['name']}' возобновлена"


@mcp.tool()
def delete_task(task_id: str) -> str:
    """Удаляет задачу и все её результаты.
    task_id: ID задачи.
    """
    task = store.get_task(task_id)
    if not task:
        return f"❌ Задача с ID '{task_id}' не найдена"

    name = task["name"]
    store.delete_task(task_id)
    return f"🗑️ Задача '{name}' удалена"


# ── Entry point ──────────────────────────────────────────

if __name__ == "__main__":
    # Initialize DB
    store.init_db()

    # We need to run both the scheduler loop and the MCP server.
    # FastMCP.run() uses its own event loop. We hook into it via atexit-style
    # by starting the scheduler as a background task before running MCP.

    import threading

    def _run_scheduler_in_thread():
        """Run the scheduler loop in a separate thread with its own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_scheduler_loop())
        except Exception as e:
            logger.error("Scheduler thread crashed: %s", e)

    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=_run_scheduler_in_thread, daemon=True)
    scheduler_thread.start()
    logger.info("Scheduler background thread started")

    # Run MCP server (blocking)
    mcp.run()
