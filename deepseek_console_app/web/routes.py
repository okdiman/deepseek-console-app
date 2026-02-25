from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .state import (
    get_config,
    get_default_agent_id,
    get_session,
    reset_session_cost_usd,
)
from .streaming import sse_response, stream_events
from .views import render_index

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(render_index())


@router.post("/clear")
async def clear() -> JSONResponse:
    session = get_session()
    config = get_config()
    session.clear()
    reset_session_cost_usd()
    if config.persist_context:
        session.save(config.context_path, config.provider, config.model)
    return JSONResponse({"ok": True})


@router.get("/stream")
async def stream(
    message: str = Query(..., min_length=1),
    agent: str = Query(get_default_agent_id(), min_length=1),
) -> StreamingResponse:
    return sse_response(stream_events(message=message, agent_id=agent))
