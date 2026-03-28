#!/usr/bin/env python3
from __future__ import annotations

import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

import asyncio
import logging
import shutil
import subprocess

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv

from .middleware import APIKeyMiddleware
from .routes import router
from .state import get_client, get_mcp_manager

load_dotenv()

logger = logging.getLogger(__name__)

_ollama_proc: subprocess.Popen | None = None


async def _ensure_ollama_running(embedder_cls, config) -> bool:
    """Return True if Ollama is reachable; try to start it if not."""
    if embedder_cls(config).health_check():
        return True

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        logger.warning("RAG: Ollama not found in PATH — RagHook disabled")
        return False

    global _ollama_proc
    logger.info("RAG: Ollama not running — starting '%s serve' ...", ollama_bin)
    _ollama_proc = subprocess.Popen(
        [ollama_bin, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait up to 10 s for Ollama to become reachable
    for i in range(10):
        await asyncio.sleep(1)
        if embedder_cls(config).health_check():
            logger.info("RAG: Ollama started (pid=%d, waited %ds)", _ollama_proc.pid, i + 1)
            return True

    logger.warning("RAG: Ollama did not start in time — RagHook disabled")
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start all enabled MCP servers on startup
    manager = get_mcp_manager()
    await manager.start_all()

    # Ensure Ollama is running, auto-starting it if needed
    from deepseek_chat.core.rag.config import load_rag_config
    from deepseek_chat.core.rag.embedder import OllamaEmbeddingClient
    from deepseek_chat.core.rag.store import get_stats
    _rag_config = load_rag_config()
    if await _ensure_ollama_running(OllamaEmbeddingClient, _rag_config):
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

    if _ollama_proc is not None:
        logger.info("RAG: stopping Ollama (pid=%d)", _ollama_proc.pid)
        _ollama_proc.terminate()
        try:
            _ollama_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ollama_proc.kill()

_rate_limit = os.getenv("RATE_LIMIT_PER_MINUTE", "60")
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{_rate_limit}/minute"])

app = FastAPI(title="DeepSeek Web Chat", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(APIKeyMiddleware)

BASE_DIR = Path(__file__).parent.resolve()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(router)


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe — returns service info without auth."""
    return JSONResponse({
        "status": "ok",
        "service": "deepseek-chat",
        "auth_enabled": bool(os.getenv("SERVICE_API_KEY", "").strip()),
        "rate_limit_per_minute": int(_rate_limit),
    })


if __name__ == "__main__":
    host = os.getenv("SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("SERVICE_PORT", "8000"))
    uvicorn.run(
        "deepseek_chat.web.app:app",
        host=host,
        port=port,
        reload=False,
    )
