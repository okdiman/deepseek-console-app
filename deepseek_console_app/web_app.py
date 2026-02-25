#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from typing import AsyncGenerator, Dict, List

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .android_agent import AndroidAgent
from .client import DeepSeekClient
from .config import load_config
from .session import ChatSession

app = FastAPI(title="DeepSeek Web App")

_config = load_config()

_web_context_path = os.getenv("DEEPSEEK_WEB_CONTEXT_PATH", "").strip()
if _web_context_path:
    _config = _config.__class__(  # type: ignore[misc]
        provider=_config.provider,
        api_key=_config.api_key,
        api_url=_config.api_url,
        models_url=_config.models_url,
        model=_config.model,
        max_tokens=_config.max_tokens,
        read_timeout_seconds=_config.read_timeout_seconds,
        price_per_1k_prompt_usd=_config.price_per_1k_prompt_usd,
        price_per_1k_completion_usd=_config.price_per_1k_completion_usd,
        persist_context=_config.persist_context,
        context_path=os.path.expanduser(_web_context_path),
        context_max_messages=_config.context_max_messages,
        optional_params=_config.optional_params,
    )

_client = DeepSeekClient(_config)
_session = ChatSession(max_messages=_config.context_max_messages)

_AGENT_REGISTRY = {
    "android": "Android Agent",
}
_agents = {
    "android": AndroidAgent(_client, _session),
}
_DEFAULT_AGENT_ID = "android"
_DEFAULT_AGENT_NAME = _AGENT_REGISTRY[_DEFAULT_AGENT_ID]
_session_cost_usd = 0.0


def _get_agent(agent_id: str) -> AndroidAgent:
    return _agents.get(agent_id, _agents[_DEFAULT_AGENT_ID])


if _config.persist_context:
    _session.load(_config.context_path)


def _render_messages(messages: List[Dict[str, str]]) -> str:
    rows = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        role_label = "You" if role == "user" else _DEFAULT_AGENT_NAME
        rows.append(
            f"""
            <div class="msg {role}">
                <div class="meta">{role_label}</div>
                <div class="content"></div>
                <script>
                  (function() {{
                    const nodes = document.getElementsByClassName("content");
                    const last = nodes[nodes.length - 1];
                    if (last) {{
                      last.textContent = {json.dumps(content)};
                    }}
                  }})();
                </script>
            </div>
            """
        )
    return "\n".join(rows)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>DeepSeek Web Chat</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    html, body {{
      height: 100%;
    }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      margin: 0;
      background: #0f1115;
      color: #e6e6e6;
      overflow: hidden;
    }}
    .container {{
      width: 100%;
      max-width: none;
      margin: 0;
      padding: 0;
      height: 100%;
      display: flex;
      flex-direction: column;
    }}
    h1 {{
      margin: 0 0 16px 0;
      font-size: 20px;
    }}
    #chat {{
      background: #161a22;
      border: 1px solid #2a2f3a;
      border-radius: 12px;
      padding: 16px 24px;
      min-height: 0;
      margin: 16px 24px;
      flex: 1;
      overflow: auto;
    }}
    .msg {{
      padding: 12px;
      border-radius: 10px;
      margin-bottom: 12px;
      background: #1b202b;
    }}
    .msg.user {{
      border-left: 3px solid #6f8cff;
    }}
    .msg.assistant {{
      border-left: 3px solid #64d39b;
    }}
    .meta {{
      font-size: 12px;
      opacity: 0.7;
      margin-bottom: 6px;
    }}
    .content {{
      white-space: pre-wrap;
      line-height: 1.4;
    }}
    form {{
      display: flex;
      gap: 8px;
      align-items: flex-start;
    }}
    textarea {{
      flex: 1;
      min-height: 64px;
      padding: 10px;
      border-radius: 10px;
      border: 1px solid #2a2f3a;
      background: #0f1115;
      color: #e6e6e6;
      resize: vertical;
    }}
    select {{
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid #2a2f3a;
      background: #0f1115;
      color: #e6e6e6;
      appearance: none;
      -webkit-appearance: none;
      -moz-appearance: none;
    }}
    button {{
      padding: 10px 16px;
      border-radius: 10px;
      border: 1px solid #2a2f3a;
      background: #2a313f;
      color: #e6e6e6;
      cursor: pointer;
    }}
    form button {{
      align-self: flex-start;
    }}
    .toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 16px 24px;
      border-bottom: 1px solid #2a2f3a;
      background: #0f1115;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    .footer {{
      padding: 12px 24px 16px 24px;
      border-top: 1px solid #2a2f3a;
      background: #0f1115;
      position: sticky;
      bottom: 0;
      z-index: 1;
    }}
    .stats {{
      padding: 0 24px 8px 24px;
      font-size: 12px;
      opacity: 0.8;
      min-height: 18px;
      display: none;
    }}
    .status {{
      font-size: 12px;
      opacity: 0.7;
      margin-top: 6px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="toolbar">
      <h1>DeepSeek Web Chat (Streaming)</h1>
      <button id="clearBtn" type="button">Clear</button>
    </div>
    <div id="chat">
      {_render_messages(_session.messages())}
    </div>
    <div class="stats" id="stats"></div>
    <div class="footer">
      <form id="chatForm">
        <textarea id="message" placeholder="Напиши сообщение..."></textarea>
        <select id="agentSelect">
          <option value="android" selected>Android Agent</option>
        </select>
        <button type="submit">Send</button>
      </form>
      <div class="status" id="status"></div>
    </div>
  </div>

<script>
  const chat = document.getElementById("chat");
  const form = document.getElementById("chatForm");
  const messageInput = document.getElementById("message");
  const agentSelect = document.getElementById("agentSelect");
  const statusEl = document.getElementById("status");
  const statsEl = document.getElementById("stats");
  const clearBtn = document.getElementById("clearBtn");

  function addMessage(role, text, label) {{
    const msg = document.createElement("div");
    msg.className = "msg " + role;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = label || (role === "user" ? "You" : "Assistant");
    const content = document.createElement("div");
    content.className = "content";
    content.textContent = text || "";
    msg.appendChild(meta);
    msg.appendChild(content);
    chat.appendChild(msg);
    chat.scrollTop = chat.scrollHeight;
    return content;
  }}

  function formatStats(stats) {{
    if (!stats) {{
      return "";
    }}
    const parts = [];
    if (stats.tokens_local) {{
      const t = stats.tokens_local;
      parts.push(
        "Tokens (local): request=" +
          t.request +
          " (" +
          t.request_method +
          "), history=" +
          t.history +
          " (" +
          t.history_method +
          "), response=" +
          t.response +
          " (" +
          t.response_method +
          ")"
      );
    }}
    const usageParts = [];
    if (stats.prompt_tokens != null) usageParts.push("prompt=" + stats.prompt_tokens);
    if (stats.completion_tokens != null)
      usageParts.push("completion=" + stats.completion_tokens);
    if (stats.total_tokens != null) usageParts.push("total=" + stats.total_tokens);
    const duration =
      stats.duration_ms != null ? stats.duration_ms + " ms" : "n/a";
    const usage = usageParts.length ? usageParts.join(", ") : "n/a";
    const cost =
      stats.cost_usd != null ? "$" + stats.cost_usd.toFixed(6) : "n/a";
    const sessionCost =
      stats.session_cost_usd != null ? "$" + stats.session_cost_usd.toFixed(6) : "n/a";
    if (
      stats.duration_ms != null ||
      usageParts.length ||
      stats.cost_usd != null ||
      stats.session_cost_usd != null
    ) {
      parts.push(
        "Time: " +
          duration +
          " | Tokens: " +
          usage +
          " | Cost: " +
          cost +
          " | Session Cost: " +
          sessionCost
      );
    }
    return parts.join(" | ");
  }}

  form.addEventListener("submit", (e) => {{
    e.preventDefault();
    const text = messageInput.value.trim();
    if (!text) return;

    addMessage("user", text, "You");
    const agentLabel =
      agentSelect.options[agentSelect.selectedIndex]?.text || "Assistant";
    const assistantContent = addMessage("assistant", "", agentLabel);
    messageInput.value = "";
    statusEl.textContent = "Streaming...";
    statsEl.textContent = "";
    statsEl.style.display = "none";

    const agentId = agentSelect.value || "android";
    const url =
      "/stream?message=" +
      encodeURIComponent(text) +
      "&agent=" +
      encodeURIComponent(agentId);
    const source = new EventSource(url);

    source.onmessage = (event) => {{
      const payload = JSON.parse(event.data);
      if (payload.delta) {{
        assistantContent.textContent += payload.delta;
        chat.scrollTop = chat.scrollHeight;
      }}
      if (payload.stats) {{
        const statsText = formatStats(payload.stats);
        statsEl.textContent = statsText;
        statsEl.style.display = statsText ? "block" : "none";
      }}
      if (payload.done) {{
        statusEl.textContent = "";
        source.close();
      }}
      if (payload.error) {{
        statusEl.textContent = "Error: " + payload.error;
        source.close();
      }}
    }};

    source.onerror = () => {{
      statusEl.textContent = "Stream connection error.";
      source.close();
    }};
  }});

  clearBtn.addEventListener("click", async () => {{
    const res = await fetch("/clear", {{ method: "POST" }});
    if (res.ok) {{
      chat.innerHTML = "";
      statusEl.textContent = "Context cleared.";
      statsEl.textContent = "";
      statsEl.style.display = "none";
    }}
  }});
</script>
</body>
</html>
"""
    return HTMLResponse(html)


@app.post("/clear")
async def clear() -> JSONResponse:
    global _session_cost_usd
    _session.clear()
    _session_cost_usd = 0.0
    if _config.persist_context:
        _session.save(_config.context_path, _config.provider, _config.model)
    return JSONResponse({"ok": True})


@app.get("/stream")
async def stream(
    message: str = Query(..., min_length=1),
    agent: str = Query(_DEFAULT_AGENT_ID, min_length=1),
) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        global _session_cost_usd
        selected_agent = _get_agent(agent)
        try:
            async for chunk in selected_agent.stream_reply(message):
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
            stats: dict = {}
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
            metrics = _client.last_metrics()
            if metrics:
                stats["duration_ms"] = round(metrics.duration_seconds * 1000.0)
                stats["prompt_tokens"] = metrics.prompt_tokens
                stats["completion_tokens"] = metrics.completion_tokens
                stats["total_tokens"] = metrics.total_tokens
                stats["cost_usd"] = metrics.cost_usd
                if metrics.cost_usd is not None:
                    _session_cost_usd += metrics.cost_usd
                stats["session_cost_usd"] = _session_cost_usd
            if stats:
                yield f"data: {json.dumps({'stats': stats})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            if _config.persist_context:
                _session.save(_config.context_path, _config.provider, _config.model)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )


if __name__ == "__main__":
    uvicorn.run(
        "deepseek_console_app.web_app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
