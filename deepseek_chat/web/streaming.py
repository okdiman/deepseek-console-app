from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict

from fastapi import Request
from fastapi.responses import StreamingResponse

from .state import (
    add_session_cost_usd,
    get_agent,
    get_client,
    get_config,
    get_session,
    get_session_cost_usd,
)

SSE_HEADERS: Dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_event(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def sse_response(event_generator: AsyncGenerator[str, None]) -> StreamingResponse:
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def stream_events(
    request: Request,
    message: str, agent_id: str, strategy: str = "default", session_id: str = "default",
    temperature: Optional[float] = None, top_p: Optional[float] = None
) -> AsyncGenerator[str, None]:
    config = get_config()
    session = get_session(session_id)
    client = get_client()
    selected_agent = get_agent(agent_id, session_id=session_id)

    try:
        if agent_id == "general":
            async for chunk in selected_agent.stream_reply(message, strategy=strategy, temperature=temperature, top_p=top_p):
                if await request.is_disconnected():
                    break
                yield sse_event({"delta": chunk})
        else:
            async for chunk in selected_agent.stream_reply(message, temperature=temperature, top_p=top_p):
                if await request.is_disconnected():
                    break
                yield sse_event({"delta": chunk})

        stats: Dict[str, Any] = {}
        token_stats = selected_agent.last_token_stats()
        if token_stats:
            stats["tokens_local"] = {
                "request": token_stats.request.tokens,
                "request_method": token_stats.request.method,
                "history": token_stats.history.tokens,
                "history_method": token_stats.history.method,
                "response": token_stats.response.tokens,
                "response_method": token_stats.response.method,
            }

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

        yield sse_event({"done": True})
    except Exception as exc:
        yield sse_event({"error": str(exc)})
    finally:
        if config.persist_context:
            session.save(config.context_path, config.provider, config.model)
