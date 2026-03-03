from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from .state import (
    create_branch,
    delete_session,
    get_all_sessions,
    get_config,
    get_default_agent_id,
    get_session,
    reset_session_cost_usd,
)
from ..core.profile import UserProfile
from .streaming import sse_response, stream_events
from .views import render_index

router = APIRouter()

class MemoryContent(BaseModel):
    content: str


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
    request: Request,
    message: str = Query(..., min_length=1),
    agent: str = Query(get_default_agent_id(), min_length=1),
    strategy: str = Query("default"),
    session_id: str = Query("default"),
    temperature: Optional[float] = Query(default=None),
    top_p: Optional[float] = Query(default=None),
) -> StreamingResponse:
    return sse_response(stream_events(
        request=request, message=message, agent_id=agent, strategy=strategy, session_id=session_id,
        temperature=temperature, top_p=top_p
    ))

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

@router.get("/memory")
async def get_memory(session_id: str = Query("default")) -> JSONResponse:
    session = get_session(session_id)
    return JSONResponse(session.memory.to_dict())

@router.post("/memory/{layer}")
async def add_memory(layer: str, payload: MemoryContent, session_id: str = Query("default")) -> JSONResponse:
    session = get_session(session_id)
    if layer == "working":
        session.memory.add_working_memory(payload.content)
    elif layer == "long_term":
        session.memory.add_long_term_memory(payload.content)
    else:
        return JSONResponse({"ok": False, "error": "Invalid memory layer"}, status_code=400)
        
    config = get_config()
    if config.persist_context:
        session.save(config.context_path, config.provider, config.model)
    return JSONResponse({"ok": True})

@router.delete("/memory/{layer}/{index}")
async def remove_memory(layer: str, index: int, session_id: str = Query("default")) -> JSONResponse:
    session = get_session(session_id)
    if layer == "working":
        session.memory.remove_working_memory(index)
    elif layer == "long_term":
        session.memory.remove_long_term_memory(index)
    else:
        return JSONResponse({"ok": False, "error": "Invalid memory layer"}, status_code=400)
        
    config = get_config()
    if config.persist_context:
        session.save(config.context_path, config.provider, config.model)
    return JSONResponse({"ok": True})


@router.get("/profile")
async def get_profile() -> JSONResponse:
    profile = UserProfile.load()
    return JSONResponse(profile.model_dump())

@router.post("/profile")
async def update_profile(profile_data: dict) -> JSONResponse:
    profile = UserProfile(**profile_data)
    profile.save()
    return JSONResponse({"ok": True})

