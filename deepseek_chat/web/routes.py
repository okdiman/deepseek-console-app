from __future__ import annotations

import os
from typing import Optional

import aiohttp
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from .state import (
    create_branch,
    delete_session,
    get_all_sessions,
    get_config,
    get_default_agent_id,
    get_mcp_manager,
    get_mcp_registry,
    get_session,
    get_task_machine,
    set_provider,
)
from .cost_tracker import reset_session_cost_usd
from ..core.memory import DialogueTask, InvariantStore, MemoryStore, UserProfile
from ..core.mcp import MCPServerConfig
from ..core import change_store
from .streaming import sse_response, stream_events
from .views import render_index
from mcp_servers.scheduler import scheduler_store as _sched_store
from mcp_servers.filesystem_server import apply_change as _fs_apply, discard_change as _fs_discard

router = APIRouter()

class MemoryContent(BaseModel):
    content: str

class TaskGoal(BaseModel):
    goal: str


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(render_index(request))


# ── Provider switching ────────────────────────────────────

class ProviderRequest(BaseModel):
    provider: str


@router.get("/config/provider")
async def get_provider(session_id: str = Query("default")) -> JSONResponse:
    config = get_config(session_id)
    return JSONResponse({"provider": config.provider, "model": config.model})


async def _check_ollama_reachable() -> bool:
    try:
        timeout = aiohttp.ClientTimeout(total=2)
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:11434/api/tags", timeout=timeout) as resp:
                return resp.status == 200
    except Exception:
        return False


@router.post("/config/provider")
async def switch_provider(
    payload: ProviderRequest, session_id: str = Query("default")
) -> JSONResponse:
    if payload.provider == "ollama" and not await _check_ollama_reachable():
        return JSONResponse(
            {"ok": False, "error": "Ollama недоступна. Запустите: ollama serve"},
            status_code=503,
        )
    try:
        set_provider(payload.provider, session_id)
        reset_session_cost_usd(session_id)
        config = get_config(session_id)
        return JSONResponse({"ok": True, "provider": config.provider, "model": config.model})
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/clear")
async def clear(session_id: str = Query("default")) -> JSONResponse:
    session = get_session(session_id)
    config = get_config(session_id)
    session.clear()
    reset_session_cost_usd(session_id)
    # Clear working memory (session-scoped), keep long-term memory
    memory = MemoryStore.load()
    memory.clear_working_memory()
    memory.save()
    if config.persist_context:
        session.save(config.context_path, config.provider, config.model)
    get_task_machine(session_id).reset()
    DialogueTask().save()
    change_store.clear()
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
    max_chars = int(os.getenv("MAX_INPUT_CHARS", "0"))
    if max_chars > 0 and len(message) > max_chars:
        return JSONResponse(
            {"detail": f"Message too long: {len(message)} chars (max {max_chars})."},
            status_code=400,
        )
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


def _task_transition(tm, action) -> JSONResponse:
    """Execute a task state transition and return a unified response."""
    try:
        action()
        return JSONResponse({"ok": True, "state": _task_response(tm)})
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": str(exc), "allowed_transitions": tm.get_allowed_transitions()},
            status_code=400,
        )


@router.get("/task")
async def get_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    return JSONResponse(_task_response(tm))

@router.post("/task/start")
async def start_task(payload: TaskGoal, session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    return _task_transition(tm, lambda: tm.start_task(payload.goal))

@router.post("/task/approve")
async def approve_task_plan(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    return _task_transition(tm, tm.approve_plan)

@router.post("/task/pause")
async def pause_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    return _task_transition(tm, tm.pause)

@router.post("/task/resume")
async def resume_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    return _task_transition(tm, tm.resume)

@router.post("/task/complete")
async def complete_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    return _task_transition(tm, tm.complete)

@router.post("/task/reset")
async def reset_task(session_id: str = Query("default")) -> JSONResponse:
    tm = get_task_machine(session_id)
    tm.reset()
    return JSONResponse({"ok": True, "state": _task_response(tm)})

# ── MCP Server endpoints ─────────────────────────────────

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


# ── Scheduler endpoints ──────────────────────────────────

@router.get("/scheduler/status")
async def scheduler_status() -> JSONResponse:
    """Scheduler dashboard data — reads SQLite directly."""
    try:
        _sched_store.init_db()
        tasks = _sched_store.get_tasks()
        summary = _sched_store.get_aggregated_summary()
        return JSONResponse({"tasks": tasks, "summary": summary})
    except Exception as e:
        return JSONResponse({"tasks": [], "summary": {}, "error": str(e)})

@router.post("/scheduler/task/{task_id}/pause")
async def scheduler_pause_task(task_id: str) -> JSONResponse:
    try:
        _sched_store.update_task(task_id, status="paused")
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.post("/scheduler/task/{task_id}/resume")
async def scheduler_resume_task(task_id: str) -> JSONResponse:
    try:
        _sched_store.update_task(task_id, status="active")
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.delete("/scheduler/task/{task_id}")
async def scheduler_delete_task(task_id: str) -> JSONResponse:
    try:
        _sched_store.delete_task(task_id)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.get("/scheduler/notifications")
async def scheduler_notifications(since: str = Query("")) -> JSONResponse:
    """Return new scheduler results since the given ISO timestamp."""
    try:
        _sched_store.init_db()
        if not since:
            return JSONResponse({"results": []})
        results = _sched_store.get_results_since(since)
        return JSONResponse({"results": results})
    except Exception as e:
        return JSONResponse({"results": [], "error": str(e)})


class AgentTaskRequest(BaseModel):
    prompt: str
    max_length: int = 4000


@router.post("/scheduler/execute_agent")
async def execute_agent_task(payload: AgentTaskRequest) -> JSONResponse:
    """Execute an autonomous agent task and return the text result."""
    try:
        import datetime
        from .state import delete_session, get_agent

        temp_session_id = f"bg_task_{datetime.datetime.now().timestamp()}"
        agent = get_agent("general", session_id=temp_session_id)

        autonomous_prompt = (
            "You are running as an autonomous background task. "
            "Fully complete the user's request without asking for permission. "
            "If a tool returns IDs or partial data, immediately use follow-up tools "
            "to produce a complete, human-readable response.\n\n"
            f"User Request: {payload.prompt}"
        )

        response_chunks = []
        async for chunk in agent.stream_reply(autonomous_prompt, temperature=0.3):
            response_chunks.append(chunk)

        delete_session(temp_session_id)

        result_text = "".join(response_chunks)
        if len(result_text) > payload.max_length:
            result_text = result_text[:payload.max_length] + f"\n... (обрезано, всего {len(result_text)} символов)"

        return JSONResponse({"ok": True, "text": result_text})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── Filesystem change proposals ──────────────────────────────────────────────

@router.get("/pending-changes")
async def get_pending_changes() -> JSONResponse:
    """Return all proposals waiting for user approval."""
    proposals = change_store.list_all()
    return JSONResponse({
        "proposals": [
            {"id": p.id, "kind": p.kind, "path": p.path, "preview": p.preview}
            for p in proposals
        ]
    })


@router.post("/apply-change")
async def apply_change_route(proposal_id: str = Query(...)) -> JSONResponse:
    """Apply a pending proposal (user-triggered, not LLM-triggered)."""
    result = _fs_apply(proposal_id)
    ok = result.startswith("✅")
    remaining = len(change_store.list_all())
    return JSONResponse({"ok": ok, "message": result, "remaining": remaining})


@router.post("/discard-change")
async def discard_change_route(proposal_id: str = Query(...)) -> JSONResponse:
    """Discard a pending proposal."""
    result = _fs_discard(proposal_id)
    ok = "not found" not in result.lower()
    remaining = len(change_store.list_all())
    return JSONResponse({"ok": ok, "message": result, "remaining": remaining})
