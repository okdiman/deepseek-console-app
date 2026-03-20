# MCP Servers — How It Works

This directory contains external MCP (Model Context Protocol) server processes. Each server runs as a standalone subprocess and exposes a set of tools the agent can call during a conversation.

---

## What is an MCP server?

An MCP server is a process that communicates with the application via stdin/stdout using the Model Context Protocol. The application launches it as a subprocess (`MCPManager.start_all()`), performs an `initialize` handshake, then calls `tools/list` to discover available tools. From that point on, when the LLM emits a tool call, the request is routed to the correct server process and the result is returned to the LLM.

Tools from all servers are namespaced: a tool `create_reminder` from server `scheduler` becomes `scheduler__create_reminder` in the LLM's tool list.

---

## Servers

| File | Server name | Purpose |
|------|-------------|---------|
| `scheduler/` | Scheduler Server | Create and manage scheduled / periodic tasks |
| `demo_server.py` | Hacker News Server | Fetch top stories and comments from Hacker News |
| `pipeline_server.py` | — | Experimental pipeline server |

---

## demo_server.py — Hacker News Server

A simple read-only MCP server that wraps the public Hacker News Firebase API.

**Tools:**

| Tool | Description |
|------|-------------|
| `get_top_stories(limit)` | Returns top N stories (title, score, author, link, ID) |
| `get_story_comments(story_id, limit)` | Returns top N comments for a given story ID |

Used by the agent in conversations about current tech news or when the user asks "what's trending on HN?".

**Run standalone:**
```bash
python3 mcp_servers/demo_server.py
```

---

## Registering a server

Servers are registered via the web UI (Settings → MCP Servers) or programmatically:

```python
from deepseek_chat.core.mcp import MCPRegistry, MCPServerConfig

registry = MCPRegistry.load()
registry.add_server(MCPServerConfig(
    server_id="my_server",
    command="python3",
    args=["mcp_servers/my_server.py"],
))
registry.save()
```

Config is persisted to `~/.deepseek_chat/mcp_servers.json` and loaded on next app start.

---

## Writing a new MCP server

Use `FastMCP` from the `mcp` package:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My Server")

@mcp.tool()
def my_tool(param: str) -> str:
    """Tool description shown to the LLM."""
    return f"result: {param}"

if __name__ == "__main__":
    mcp.run()
```

The server must be runnable as a standalone script. It communicates via stdio — do not write to stdout for any other purpose.

See `deepseek_chat/core/mcp/_HOW_IT_WORKS.md` for how `MCPManager` manages server lifecycles.
