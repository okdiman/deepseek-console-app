# MCP — How It Works

This package manages MCP (Model Context Protocol) tool servers: external processes that expose tools the agent can call during a conversation.

---

## Package Structure

```
deepseek_chat/core/mcp/
├── manager.py  — MCPManager: subprocess lifecycle + tool routing + execution
├── registry.py — MCPRegistry: persistent server configuration
└── __init__.py — re-exports MCPManager, MCPRegistry, MCPServerConfig
```

---

## Overview

MCP servers are external processes (e.g. Node.js, Python scripts) that communicate via stdio using the Model Context Protocol. Each server exposes a set of tools. The agent can call these tools mid-stream, receive results, and continue generating.

```
Agent (stream_reply)
    │ detects tool_call chunk from LLM
    ▼
MCPManager.execute_tool("server_id__tool_name", args)
    │
    ├── routes to correct MCPServerProcess by prefix
    ▼
MCPServerProcess (stdio subprocess)
    │ sends MCP request, waits for response
    ▼
tool result → added to session history → LLM continues
```

---

## MCPRegistry (`registry.py`)

Stores server configurations. Each entry is an `MCPServerConfig`:

| Field | Description |
|-------|-------------|
| `server_id` | Unique identifier, e.g. `"scheduler"` |
| `command` | Executable, e.g. `"python3"` |
| `args` | Arguments list, e.g. `["mcp_servers/scheduler/scheduler_server.py"]` |
| `env` | Optional extra environment variables |

**Persistence:** `~/.deepseek_chat/mcp_servers.json`

**Not cleared on `/clear`** — server configs are permanent.

CRUD operations: `add_server()`, `remove_server()`, `get_server()`, `list_servers()`.

---

## MCPManager (`manager.py`)

Manages the lifecycle of all registered MCP server subprocesses.

### Startup

`MCPManager.start_all()` is called from `web/app.py` lifespan. For each registered server:
1. Spawns the subprocess (stdin/stdout pipe)
2. Sends MCP `initialize` handshake
3. Calls `tools/list` to discover available tools
4. Registers tools with a `server_id__tool_name` prefix

### Tool routing

All tools from all servers are aggregated into a flat list via `get_aggregated_tools()`. Tools are namespaced: a tool `create_task` from server `scheduler` becomes `scheduler__create_task`.

When the LLM emits a tool call, `execute_tool(fn_name, args)` strips the prefix, routes to the correct server process, and returns the result.

### Auto-restart

If a server process crashes, `MCPManager` automatically restarts it (up to 5 times). After 5 failures the server is marked as permanently failed and its tools are removed from the aggregated list.

### Graceful shutdown

`MCPManager.stop_all()` is called from `web/app.py` lifespan teardown. Sends SIGTERM to all subprocesses.

---

## Tool call flow inside BaseAgent

The agent's `stream_reply` loop handles two special JSON payloads from the client:

```python
# 1. Tool call starting (UI feedback)
{"__type__": "tool_call_start", "name": "scheduler__create_task"}

# 2. All tool calls for this turn
{"__type__": "tool_calls", "calls": [...]}
```

On receiving `tool_calls`:
1. Save preceding text to session
2. Append assistant message with `tool_calls` payload
3. For each call: `MCPManager.execute_tool(fn_name, args)`
4. Append `tool` result message to session
5. Re-build history and re-enter the LLM stream loop

The LLM sees tool results in history and continues generating its final response.

---

## Adding a new MCP server

```bash
# Via web UI: Settings → MCP Servers → Add

# Or programmatically:
from deepseek_chat.core.mcp import MCPRegistry, MCPServerConfig
registry = MCPRegistry.load()
registry.add_server(MCPServerConfig(
    server_id="my_server",
    command="python3",
    args=["mcp_servers/my_server/server.py"],
))
registry.save()
```

The server will be started on next app restart (or immediately if `MCPManager.start_server()` is called).

---

## Import

```python
from deepseek_chat.core.mcp import MCPManager, MCPRegistry, MCPServerConfig
```
