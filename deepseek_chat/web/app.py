#!/usr/bin/env python3
from __future__ import annotations

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

import asyncio
import logging

from .routes import router
from .state import get_client, get_mcp_manager

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start all enabled MCP servers on startup
    manager = get_mcp_manager()
    await manager.start_all()

    # Check Ollama availability for RagHook
    from deepseek_chat.core.rag.config import load_rag_config
    from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
    from deepseek_chat.core.rag.store import get_stats
    _rag_config = load_rag_config()
    if OllamaEmbeddingClient(_rag_config).health_check():
        stats = get_stats(_rag_config.db_path)
        if stats["total"] > 0:
            logger.info("RAG: Ollama reachable, index has %d chunks — RagHook active", stats["total"])
        else:
            logger.warning("RAG: Ollama reachable but index is empty — run: python3 experiments/rag_compare/cli.py index")
    else:
        logger.warning("RAG: Ollama not reachable — RagHook disabled (start with: ollama serve)")

    # Start the scheduler runner as a background asyncio task.
    # Pass the web app's client + manager directly — no duplicate MCP subprocesses.
    from mcp_servers.scheduler.scheduler_runner import run_scheduler_loop
    scheduler_task = asyncio.create_task(
        run_scheduler_loop(client=get_client(), manager=manager)
    )
    logger.info("Scheduler runner started as background task (shared MCP manager).")

    yield

    # Cancel scheduler gracefully, then clean up MCP subprocesses
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await manager.stop_all()

app = FastAPI(title="DeepSeek Web Chat", lifespan=lifespan)

BASE_DIR = Path(__file__).parent.resolve()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(
        "deepseek_chat.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
