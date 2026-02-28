#!/usr/bin/env python3
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .routes import router

app = FastAPI(title="DeepSeek Web App")

BASE_DIR = Path(__file__).parent.resolve()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(
        "deepseek_console_app.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
