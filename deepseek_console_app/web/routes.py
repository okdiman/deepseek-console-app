from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .state import (
    create_branch,
    delete_session,
    get_all_sessions,
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
async def clear(session_id: str = Query("default")) -> JSONResponse:
    session = get_session(session_id)
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
    strategy: str = Query("default"),
    session_id: str = Query("default"),
) -> StreamingResponse:
    return sse_response(stream_events(message=message, agent_id=agent, strategy=strategy, session_id=session_id))

@router.get("/sessions")
async def list_sessions() -> JSONResponse:
    sessions = get_all_sessions()
    session_list = []
    for s_id, s in sessions.items():
        session_list.append({
            "id": s_id,
            "summary": s.summary,
            "updated_at": getattr(s, 'updated_at', "")
        })
    return JSONResponse({"sessions": session_list})

@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str) -> JSONResponse:
    delete_session(session_id)
    return JSONResponse({"ok": True})

@router.post("/branch")
async def create_new_branch(
    parent_id: str = Query(..., min_length=1),
    message_index: int = Query(...),
    new_branch_id: str = Query(..., min_length=1)
) -> JSONResponse:
    create_branch(parent_id, message_index, new_branch_id)
    return JSONResponse({"ok": True, "branch_id": new_branch_id})

@router.get("/history")
async def get_history(session_id: str = Query("default")) -> JSONResponse:
    session = get_session(session_id)
    return JSONResponse({"messages": session.messages(), "summary": session.summary, "facts": session.facts})
