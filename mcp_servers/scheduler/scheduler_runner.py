"""
Background scheduler runner — standalone process.

Periodically checks the SQLite tasks table and executes due tasks.
Can be run directly:  python mcp_servers/scheduler/scheduler_runner.py

Architecture:
  - Accepts a DeepSeekClient + MCPManager directly (no agent carrier needed)
  - Creates a fresh BackgroundAgent + ChatSession per task to avoid context bleed
  - Executes due tasks in parallel, bounded by _AI_CONCURRENCY semaphore
  - Shares the same SQLite DB as scheduler_server.py (WAL mode)
  - No HTTP dependency on FastAPI
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

# Project root on path when run as a script
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import scheduler_store as store
from scheduler_utils import compute_next_run

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 30
_AI_CONCURRENCY = 3  # max concurrent LLM calls per tick


# ── Task executors ───────────────────────────────────────

async def _execute_reminder(task: dict) -> str:
    payload = json.loads(task["payload"]) if isinstance(task["payload"], str) else task["payload"]
    return f"🔔 Напоминание: {payload.get('text', '(без текста)')}"


async def _execute_periodic_collect(task: dict, client, manager) -> str:
    """Execute periodic data collection via a fresh BackgroundAgent per task."""
    from deepseek_chat.core.config import load_config
    from deepseek_chat.core.session import ChatSession
    from deepseek_chat.agents.background_agent import BackgroundAgent

    payload = json.loads(task["payload"]) if isinstance(task["payload"], str) else task["payload"]
    prompt = payload.get("prompt", "")
    if not prompt:
        url = payload.get("url", "")
        prompt = f"Возьми данные с {url} и сделай краткую выжимку." if url else ""
    if not prompt:
        return "❌ Промпт не указан в payload задачи"

    config = load_config()
    fresh_session = ChatSession(max_messages=config.context_max_messages)
    task_agent = BackgroundAgent(client, fresh_session, mcp_manager=manager)

    try:
        chunks = []
        async for chunk in task_agent.stream_reply(prompt, temperature=0.3):
            chunks.append(chunk)
        result_text = "".join(chunks).strip()
        max_length = payload.get("max_length", 4000)
        if len(result_text) > max_length:
            result_text = result_text[:max_length] + f"\n... (обрезано, всего {len(result_text)} символов)"
        return f"🤖 Результат:\n{result_text}"
    except Exception as e:
        logger.error("periodic_collect failed for task %s: %s", task["id"], e, exc_info=True)
        return f"❌ Ошибка выполнения агента: {e}"


async def _execute_periodic_summary(task: dict) -> str:
    payload = json.loads(task["payload"]) if isinstance(task["payload"], str) else task["payload"]
    target_task_id = payload.get("target_task_id", "")

    if target_task_id:
        results = store.get_results(target_task_id, limit=50)
        if not results:
            return "📋 Нет данных для сводки"
        lines = [f"📋 Сводка по задаче {target_task_id} ({len(results)} записей):"]
        for r in results[:10]:
            lines.append(f"  • [{r['executed_at']}] {r['result'][:200]}")
        if len(results) > 10:
            lines.append(f"  ... и ещё {len(results) - 10} записей")
        return "\n".join(lines)
    else:
        agg = store.get_aggregated_summary()
        lines = [
            "📋 Общая сводка планировщика:",
            f"  Всего задач: {agg['total_tasks']}",
            f"  Активных: {agg['active']} | На паузе: {agg['paused']} | Завершено: {agg['completed']}",
        ]
        if agg["recent_results"]:
            lines.append("  Последние результаты:")
            for r in agg["recent_results"][:5]:
                lines.append(f"    • [{r['task_name']}] {r['result'][:150]}")
        return "\n".join(lines)


# ── Parallel tick ────────────────────────────────────────

async def _run_single_task(
    task: dict,
    now: datetime,
    now_iso: str,
    db_path: str,
    client,
    manager,
    semaphore: asyncio.Semaphore,
) -> None:
    """Execute one due task under the concurrency semaphore, then persist result + timing."""
    task_id = task["id"]
    task_type = task["type"]

    async with semaphore:
        logger.info("Executing task %s (%s): %s", task_id, task_type, task["name"])
        try:
            if task_type == "periodic_collect":
                result = await _execute_periodic_collect(task, client=client, manager=manager)
            elif task_type == "reminder":
                result = await _execute_reminder(task)
            elif task_type == "periodic_summary":
                result = await _execute_periodic_summary(task)
            else:
                logger.warning("No executor for task type '%s' (task %s)", task_type, task_id)
                return
        except Exception as e:
            result = f"❌ Ошибка выполнения: {e}"
            logger.error("Task %s execution failed: %s", task_id, e)

    store.add_result(task_id, result, db_path=db_path)

    schedule = task.get("schedule", "once")
    if schedule == "once":
        store.update_task(task_id, db_path=db_path, status="completed", last_run_at=now_iso)
        logger.info("One-time task %s completed.", task_id)
    else:
        next_run_new = compute_next_run(schedule, from_time=now)
        store.update_task(task_id, db_path=db_path, last_run_at=now_iso, next_run_at=next_run_new)
        logger.info("Periodic task %s next run: %s", task_id, next_run_new)


async def _tick(
    db_path: str,
    client,
    manager,
    semaphore: asyncio.Semaphore,
) -> None:
    """Single scheduler tick: collect all due tasks and execute them in parallel."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    tasks = store.get_tasks(status="active", db_path=db_path)
    due = [t for t in tasks if t.get("next_run_at") and t["next_run_at"] <= now_iso]

    if not due:
        return

    logger.info("Tick: %d task(s) due.", len(due))
    await asyncio.gather(*(
        _run_single_task(task, now, now_iso, db_path, client, manager, semaphore)
        for task in due
    ))


# ── Main runner loop ─────────────────────────────────────

async def run_scheduler_loop(
    db_path: str = store.DB_PATH,
    client=None,
    manager=None,
) -> None:
    """
    Main scheduler loop.

    client / manager — pre-built pair supplied by the web app lifespan.
    When omitted (standalone mode), builds its own stack.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info("Scheduler runner started (interval=%ds, concurrency=%d)", CHECK_INTERVAL_SECONDS, _AI_CONCURRENCY)

    store.init_db(db_path)
    semaphore = asyncio.Semaphore(_AI_CONCURRENCY)

    _owns_manager = manager is None
    if _owns_manager:
        from deepseek_chat.core.agent_factory import build_client, build_manager
        client = build_client()
        manager = build_manager()
        logger.info("Starting MCP servers for standalone runner...")
        await manager.start_all()
        logger.info("MCP servers ready.")

    try:
        while True:
            try:
                await _tick(db_path=db_path, client=client, manager=manager, semaphore=semaphore)
            except Exception as e:
                logger.error("Scheduler tick error: %s", e, exc_info=True)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    finally:
        if _owns_manager:
            logger.info("Shutting down MCP servers...")
            await manager.stop_all()


# ── Standalone entrypoint ────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(run_scheduler_loop())
    except KeyboardInterrupt:
        logger.info("Scheduler runner stopped.")
