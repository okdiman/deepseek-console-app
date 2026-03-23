from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from fastapi import Request
from fastapi.responses import StreamingResponse

from .state import (
    get_agent,
    get_client,
    get_config,
    get_session,
    get_task_machine,
)
from .cost_tracker import add_session_cost_usd, get_session_cost_usd

SSE_HEADERS: Dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# Task state transition markers — compiled once at module level
_STEP_DONE_RE = re.compile(r"\[STEP_DONE\]", re.IGNORECASE)
_VALIDATION_RE = re.compile(r"\[READY_FOR_VALIDATION\]|\[VALIDATION\]", re.IGNORECASE)
_REVERT_RE = re.compile(r"\[REVERT_TO_STEP:\s*(\d+)\]", re.IGNORECASE)
_RESUME_RE = re.compile(r"\[RESUME_TASK\]", re.IGNORECASE)


def sse_event(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def sse_response(event_generator: AsyncGenerator[str, None]) -> StreamingResponse:
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _collect_task_markers(accumulated_text: str, last_idx: int) -> List[Tuple[int, int, str, Any]]:
    """Scan accumulated_text from last_idx onward and return sorted marker tuples."""
    matches = []
    for m in _STEP_DONE_RE.finditer(accumulated_text):
        if m.start() >= last_idx:
            matches.append((m.start(), m.end(), "STEP_DONE", None))
    for m in _VALIDATION_RE.finditer(accumulated_text):
        if m.start() >= last_idx:
            matches.append((m.start(), m.end(), "VALIDATION", None))
    for m in _REVERT_RE.finditer(accumulated_text):
        if m.start() >= last_idx:
            matches.append((m.start(), m.end(), "REVERT", int(m.group(1)) - 1))
    for m in _RESUME_RE.finditer(accumulated_text):
        if m.start() >= last_idx:
            matches.append((m.start(), m.end(), "RESUME", None))
    matches.sort(key=lambda x: x[0])
    return matches


def _apply_task_markers(tm, accumulated_text: str, last_idx: int) -> Tuple[int, List[str]]:
    """
    Apply any new task state markers found past last_idx.
    Returns (new_last_idx, list_of_sse_task_state_events).
    """
    from ..core.task_state import TaskPhase, InvalidTransitionError

    state = tm.state
    if state.phase not in {TaskPhase.EXECUTION, TaskPhase.VALIDATION, TaskPhase.PAUSED}:
        return last_idx, []

    matches = _collect_task_markers(accumulated_text, last_idx)
    if not matches:
        return last_idx, []

    events: List[str] = []
    new_last_idx = last_idx

    for start_idx, end_idx, marker_type, val in matches:
        current_phase = tm.state.phase
        changed = False

        if marker_type == "STEP_DONE" and current_phase == TaskPhase.EXECUTION:
            try:
                tm.step_done()
                changed = True
            except InvalidTransitionError:
                pass

        elif marker_type == "VALIDATION" and current_phase == TaskPhase.EXECUTION:
            if tm.state.current_step < tm.state.total_steps:
                try:
                    tm.step_done()
                except InvalidTransitionError:
                    pass
            try:
                tm.advance_to_validation()
                changed = True
            except InvalidTransitionError:
                pass

        elif marker_type == "REVERT" and current_phase in {TaskPhase.EXECUTION, TaskPhase.VALIDATION}:
            try:
                tm.revert_to_step(val)
                changed = True
            except InvalidTransitionError:
                pass

        elif marker_type == "RESUME" and current_phase == TaskPhase.PAUSED:
            try:
                tm.resume()
                changed = True
            except InvalidTransitionError:
                pass

        if changed:
            task_data = tm.state.to_dict()
            task_data["allowed_transitions"] = tm.get_allowed_transitions()
            events.append(sse_event({"task_state": task_data}))

        new_last_idx = end_idx

    return new_last_idx, events


async def stream_events(
    request: Request,
    message: str, agent_id: str, session_id: str = "default",
    temperature: Optional[float] = None, top_p: Optional[float] = None
) -> AsyncGenerator[str, None]:
    from ..core.task_state import TaskPhase

    config = get_config(session_id)
    session = get_session(session_id)
    client = get_client(session_id)
    selected_agent = get_agent(agent_id, session_id=session_id)
    tm = get_task_machine(session_id)

    try:
        accumulated_text = ""
        last_processed_idx = 0
        stats: Dict[str, Any] = {}

        # Tell the TaskStateHook not to re-process markers that we handle live here
        selected_agent._skip_after_stream_markers = True

        gen = selected_agent.stream_reply(message, temperature=temperature, top_p=top_p)
        try:
            async for chunk in gen:
                if await request.is_disconnected():
                    state = tm.state
                    if getattr(state, "phase", None) in {TaskPhase.EXECUTION, TaskPhase.PLANNING, TaskPhase.VALIDATION}:
                        try:
                            tm.pause()
                        except Exception:
                            pass
                    break

                accumulated_text += chunk

                new_idx, marker_events = _apply_task_markers(tm, accumulated_text, last_processed_idx)
                last_processed_idx = new_idx
                for ev in marker_events:
                    yield ev

                yield sse_event({"delta": chunk})

        except asyncio.CancelledError:
            state = tm.state
            if getattr(state, "phase", None) in {TaskPhase.EXECUTION, TaskPhase.PLANNING, TaskPhase.VALIDATION}:
                try:
                    tm.pause()
                except Exception:
                    pass
            raise
        finally:
            await gen.aclose()

        metrics = client.last_metrics()
        if metrics:
            stats["duration_ms"] = round(metrics.duration_seconds * 1000.0)
            stats["prompt_tokens"] = metrics.prompt_tokens
            stats["completion_tokens"] = metrics.completion_tokens
            stats["total_tokens"] = metrics.total_tokens
            stats["cost_usd"] = metrics.cost_usd
            if metrics.cost_usd is not None:
                add_session_cost_usd(metrics.cost_usd)
            stats["session_cost_usd"] = get_session_cost_usd()

        if stats:
            yield sse_event({"stats": stats})

        tm = get_task_machine(session_id)
        task_data = tm.state.to_dict()
        task_data["allowed_transitions"] = tm.get_allowed_transitions()
        yield sse_event({"task_state": task_data})

        yield sse_event({"done": True})
    except Exception as exc:
        yield sse_event({"error": str(exc)})
    finally:
        if config.persist_context:
            session.save(config.context_path, config.provider, config.model)
