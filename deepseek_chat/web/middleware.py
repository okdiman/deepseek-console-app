"""
Service middleware for Day 30 — local LLM as a private service.

API key authentication:
  - Enabled when SERVICE_API_KEY is set in env (non-empty).
  - Clients pass the key via header: X-API-Key: <key>
  - Exempt paths: /health, /static/* (HTML UI served without auth —
    intended for same-network / VPN access; programmatic API requires key).
"""
from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


_EXEMPT_PREFIXES = ("/health", "/static/", "/")  # '/' exact match handled below


def _is_exempt(path: str) -> bool:
    """Return True for paths that don't require API key auth."""
    if path == "/" or path == "":
        return True
    if path.startswith("/static/"):
        return True
    if path == "/health":
        return True
    return False


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Rejects requests missing a valid X-API-Key header when SERVICE_API_KEY is set."""

    async def dispatch(self, request: Request, call_next):
        api_key = os.getenv("SERVICE_API_KEY", "").strip()
        if not api_key:
            # Auth disabled — pass through
            return await call_next(request)

        if _is_exempt(request.url.path):
            return await call_next(request)

        provided = request.headers.get("X-API-Key", "")
        if provided != api_key:
            return JSONResponse(
                {"detail": "Invalid or missing API key. Pass X-API-Key header."},
                status_code=401,
            )

        return await call_next(request)
