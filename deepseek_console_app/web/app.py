#!/usr/bin/env python3
from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from .routes import router

app = FastAPI(title="DeepSeek Web App")
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(
        "deepseek_console_app.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
