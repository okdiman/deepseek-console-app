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
| `git_server.py` | Git Project Server | Exposes git info about the project (branch, commits, diffs, file tree) |
| `filesystem_server.py` | Filesystem Server | Two-phase read/write access to project files (propose → confirm → apply) |
| `pipeline_server.py` | — | Experimental pipeline server |

---

## git_server.py — Git Project Server

A read-only MCP server that exposes git information about the local project to the LLM. Used primarily by `DevHelpAgent` to answer questions about the current state of the codebase.

**Tools:**

| Tool | Description |
|------|-------------|
| `get_current_branch()` | Returns the current git branch name |
| `get_recent_commits(limit)` | Returns last N commits (hash \| author \| date \| message) |
| `list_changed_files()` | Returns git status --short (modified/untracked files) |
| `get_file_diff(file_path)` | Returns git diff HEAD for a specific file |
| `get_project_structure(max_depth)` | Returns a text directory tree (excludes `__pycache__`, `.git`, `.venv`) |

All tools run `git` as a subprocess inside the project root. They return plain text — errors are returned as strings rather than exceptions so the LLM can explain what went wrong.

**Run standalone:**
```bash
python3 mcp_servers/git_server.py
```

**Registration:** Auto-registered as builtin `git_project` server on first app start (or when loading an existing `mcp_servers.json` that does not yet contain it). See `MCPRegistry._BUILTIN_SERVERS`.

---

## filesystem_server.py — Filesystem Server

Two-phase read/write access to the project. All write operations require an explicit confirmation step — the LLM physically cannot modify files without calling `apply_change` after the user approves.

**Read tools (no confirmation needed):**

| Tool | Description |
|------|-------------|
| `read_file(path)` | Read file contents |
| `list_directory(path, pattern)` | List files with glob filter |
| `search_in_files(pattern, glob)` | Regex search across files (up to 50 matches) |

**Two-phase write tools:**

| Tool | Description |
|------|-------------|
| `propose_write(path, content)` | Propose creating/overwriting a file — returns proposal_id + diff |
| `propose_edit(path, old_string, new_string)` | Propose replacing an exact string — returns proposal_id + unified diff |
| `propose_delete(path)` | Propose deleting a file — returns proposal_id |
| `apply_change(proposal_id)` | Apply a pending proposal (the user confirmation step) |
| `discard_change(proposal_id)` | Discard a pending proposal |
| `list_pending_changes()` | Show all not-yet-applied proposals |

**Test runner:**

| Tool | Description |
|------|-------------|
| `run_tests(test_path)` | Run pytest on the project or a specific file/dir |

**Safety guarantees:**
- All paths are validated against `_PROJECT_ROOT` — path traversal attempts are rejected
- Proposals are held in-memory in the MCP subprocess; `apply_change` is the only write gate
- `propose_edit` validates that `old_string` appears **exactly once** before creating a proposal — ambiguous edits are rejected upfront

**Run standalone:**
```bash
python3 mcp_servers/filesystem_server.py
```

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
