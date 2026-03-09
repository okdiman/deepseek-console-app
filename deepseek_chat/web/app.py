#!/usr/bin/env python3
from __future__ import annotations

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .routes import router
from .state import get_mcp_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start all enabled MCP servers on startup
    manager = get_mcp_manager()
    await manager.start_all()
    
    yield
    
    # Clean up subprocesses on shutdown
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
