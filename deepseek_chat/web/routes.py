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
    get_task_machine,
)
from .cost_tracker import reset_session_cost_usd
from ..core.profile import UserProfile
from ..core.memory import MemoryStore
from ..core.invariants import InvariantStore
from .streaming import sse_response, stream_events
from .views import render_index

router = APIRouter()

class MemoryContent(BaseModel):
    content: str

class TaskGoal(BaseModel):
    goal: str


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(render_index(request))


@router.post("/clear")
async def clear(session_id: str = Query("default")) -> JSONResponse:
    session = get_session(session_id)
    config = get_config()
    session.clear()
    reset_session_cost_usd()
    # Clear working memory (session-scoped), keep long-term memory
    memory = MemoryStore.load()
    memory.clear_working_memory()
    memory.save()
    if config.persist_context:
        session.save(config.context_path, config.provider, config.model)
    get_task_machine(session_id).reset()
    return JSONResponse({"ok": True})


@router.get("/stream")
async def stream(
    request: Request,
    message: str = Query(..., min_length=1),
    agent: str = Query(get_default_agent_id(), min_length=1),
    session_id: str = Query("default"),
    temperature: Optional[float] = Query(default=None),
    top_p: Optional[float] = Query(default=None),
) -> StreamingResponse:
    return sse_response(stream_events(
        request=request, message=message, agent_id=agent, session_id=session_id,
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
async def get_memory() -> JSONResponse:
    memory = MemoryStore.load()
    return JSONResponse(memory.to_dict())

@router.post("/memory/{layer}")
async def add_memory(layer: str, payload: MemoryContent) -> JSONResponse:
    memory = MemoryStore.load()
    if layer == "working":
        memory.add_working_memory(payload.content)
    elif layer == "long_term":
        memory.add_long_term_memory(payload.content)
    else:
        return JSONResponse({"ok": False, "error": "Invalid memory layer"}, status_code=400)
        
    memory.save()
    return JSONResponse({"ok": True})

@router.delete("/memory/{layer}/{index}")
async def remove_memory(layer: str, index: int) -> JSONResponse:
    memory = MemoryStore.load()
    if layer == "working":
        memory.remove_working_memory(index)
    elif layer == "long_term":
        memory.remove_long_term_memory(index)
    else:
        return JSONResponse({"ok": False, "error": "Invalid memory layer"}, status_code=400)
        
    memory.save()
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


# ── Invariants endpoints ─────────────────────────────────

@router.get("/invariants")
async def get_invariants() -> JSONResponse:
    store = InvariantStore.load()
    return JSONResponse(store.to_dict())

@router.post("/invariants")
async def add_invariant(payload: MemoryContent) -> JSONResponse:
    store = InvariantStore.load()
    store.add(payload.content)
    store.save()
    return JSONResponse({"ok": True})

@router.delete("/invariants/{index}")
async def remove_invariant(index: int) -> JSONResponse:
    store = InvariantStore.load()
    store.remove(index)
    store.save()
    return JSONResponse({"ok": True})


# ── Task State Machine endpoints ─────────────────────────────

def _task_response(tm) -> dict:
    """Build a unified task response including allowed transitions."""
    data = tm.state.to_dict()
    data["allowed_transitions"] = tm.get_allowed_transitions()
    return data

@router.get("/task")
async def get_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    return JSONResponse(_task_response(tm))

@router.post("/task/start")
async def start_task(payload: TaskGoal, session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    try:
        tm.start_task(payload.goal)
        return JSONResponse({"ok": True, "state": _task_response(tm)})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc), "allowed_transitions": tm.get_allowed_transitions()}, status_code=400)

@router.post("/task/approve")
async def approve_task_plan(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    try:
        tm.approve_plan()
        return JSONResponse({"ok": True, "state": _task_response(tm)})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc), "allowed_transitions": tm.get_allowed_transitions()}, status_code=400)

@router.post("/task/pause")
async def pause_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    try:
        tm.pause()
        return JSONResponse({"ok": True, "state": _task_response(tm)})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc), "allowed_transitions": tm.get_allowed_transitions()}, status_code=400)

@router.post("/task/resume")
async def resume_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    try:
        tm.resume()
        return JSONResponse({"ok": True, "state": _task_response(tm)})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc), "allowed_transitions": tm.get_allowed_transitions()}, status_code=400)

@router.post("/task/complete")
async def complete_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    try:
        tm.complete()
        return JSONResponse({"ok": True, "state": _task_response(tm)})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc), "allowed_transitions": tm.get_allowed_transitions()}, status_code=400)

@router.post("/task/reset")
async def reset_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    tm.reset()
    return JSONResponse({"ok": True, "state": _task_response(tm)})

# ── MCP Server endpoints ─────────────────────────────────

from ..core.mcp_registry import MCPServerConfig
from .state import get_mcp_registry, get_mcp_manager

@router.get("/mcp")
async def list_mcp_servers() -> JSONResponse:
    registry = get_mcp_registry()
    manager = get_mcp_manager()
    
    servers = [s.model_dump() for s in registry.get_all()]
    
    # Also attach the active tools for enabled servers
    tools = manager.get_aggregated_tools()
    
    return JSONResponse({
        "servers": servers,
        "tools": tools
    })

@router.post("/mcp")
async def save_mcp_server(config: MCPServerConfig) -> JSONResponse:
    registry = get_mcp_registry()
    manager = get_mcp_manager()
    
    registry.add_server(config)
    registry.save()
    
    if config.enabled:
        await manager.reload_server(config.id)
    else:
        await manager.stop_server(config.id)
        
    return JSONResponse({"ok": True})

@router.delete("/mcp/{server_id}")
async def delete_mcp_server(server_id: str) -> JSONResponse:
    registry = get_mcp_registry()
    manager = get_mcp_manager()
    
    await manager.stop_server(server_id)
    registry.remove_server(server_id)
    registry.save()
    
    return JSONResponse({"ok": True})

@router.post("/mcp/{server_id}/toggle")
async def toggle_mcp_server(server_id: str, payload: dict) -> JSONResponse:
    registry = get_mcp_registry()
    manager = get_mcp_manager()
    
    server = registry.get_server(server_id)
    if not server:
        return JSONResponse({"ok": False, "error": "Server not found"}, status_code=404)
        
    enabled = payload.get("enabled", False)
    server.enabled = enabled
    registry.save()
    
    if enabled:
        await manager.reload_server(server_id)
    else:
        await manager.stop_server(server_id)
        
    return JSONResponse({"ok": True, "enabled": enabled})
