# Project Context — DeepSeek Console App (Quick Reference)

Architecture guidelines: `docs/ARCHITECTURE.md`

## What it is
Streaming chat application with DeepSeek/Groq API, featuring a Web UI and console interface with multiple agents (General, Android).

## Web UI Structure (after refactor)
- `deepseek_chat/web/app.py` — FastAPI app, wires router
- `deepseek_chat/web/routes.py` — HTTP routes (`/`, `/clear`, `/stream`)
- `deepseek_chat/web/views.py` — HTML rendering (now minimal, uses templates)
- `deepseek_chat/web/state.py` — shared state/config/session/agent
- `deepseek_chat/web/streaming.py` — SSE streaming helpers
- `deepseek_chat/web/static/` — static files (JS, CSS)
- `deepseek_chat/web/templates/` — HTML templates (index.html)

## How static/templates are used
- CSS and JS are now in `web/static/` (e.g. `style.css`, `app.js`)
- HTML is rendered from `web/templates/index.html` via FastAPI/Jinja2
- `views.py` loads template and injects messages/agent name


## Run
- `python3 -m deepseek_chat.console.main`  
- Web UI: `python3 -m deepseek_chat.web.app` (opens http://127.0.0.1:8000)
- Clean run: `chmod +x scripts/run_clean.sh && ./scripts/run_clean.sh`

## Key Files
- `deepseek_chat/console/main.py` — console app bootstrap
- `deepseek_chat/console/app.py` — CLI loop
- `deepseek_chat/web/app.py` — FastAPI app
- `deepseek_chat/web/routes.py` — web routes
- `deepseek_chat/web/views.py` — HTML rendering
- `deepseek_chat/web/state.py` — web state/config/session/agent
- `deepseek_chat/web/streaming.py` — SSE streaming
- `deepseek_chat/web/static/` — static files (JS, CSS)
- `deepseek_chat/web/templates/` — HTML templates
- `deepseek_chat/core/config.py` — config + optional params (code-only)
- `deepseek_chat/core/client.py` — streaming HTTP client
- `deepseek_chat/agents/base_agent.py` — Base agent orchestrator running Hook pipelines
- `deepseek_chat/agents/hooks/` — AgentHooks package (base, MemoryInjection, UserProfile, AutoTitle, TaskState, InvariantGuard)
- `deepseek_chat/agents/android_agent.py` — Android-focused agent + system prompt
- `deepseek_chat/agents/general_agent.py` — General-purpose agent
- `deepseek_chat/core/session.py` — message history, branching, context compression
- `deepseek_chat/core/task_state.py` — Task State Machine (finite automaton: idle→planning→execution→validation→done)
- `deepseek_chat/core/mcp_manager.py` — Manages dynamic MCP processes and their tools
- `deepseek_chat/core/mcp_registry.py` — Persists MCP server configs (`~/.deepseek_chat/mcp_servers.json`)
- `mcp_servers/scheduler/scheduler_server.py` — Scheduler MCP server (pure tool provider: create/list/pause/resume/delete tasks)
- `mcp_servers/scheduler/scheduler_store.py` — SQLite persistence for scheduler (`~/.deepseek_chat/scheduler.db`)
- `mcp_servers/scheduler/scheduler_runner.py` — Standalone background runner (`python scheduler_runner.py`); own agent stack, no HTTP dependency
- `mcp_servers/scheduler/scheduler_utils.py` — Shared `compute_next_run()` utility
- `mcp_servers/pipeline_server.py` — Pipeline MCP server (Day 19): `search` → `summarize` → `save_to_file` + composite `run_pipeline`
- `deepseek_chat/core/agent_factory.py` — `build_background_agent()`: builds agent+MCPManager without web imports
- `deepseek_chat/agents/background_agent.py` — Minimal agent for background tasks (no stateful hooks)
- `deepseek_chat/core/memory.py` — global explicit memory layers (working, long_term), persisted to `~/.deepseek_chat/memory.json`
- `deepseek_chat/core/profile.py` — global UserProfile model (`~/.deepseek_chat/profile.json`)
- `deepseek_chat/core/invariants.py` — global InvariantStore model (`~/.deepseek_chat/invariants.json`)
- `deepseek_chat/core/stream_printer.py` — stall indicator
- `deepseek_chat/core/comparing/model_compare.py` — сравнение ответов разных моделей

## Config (env)
Provider selection:
- `PROVIDER` (`deepseek` or `groq`, default `deepseek`)

DeepSeek:
- `DEEPSEEK_API_KEY` (required when provider is `deepseek`)
- `DEEPSEEK_API_TIMEOUT_SECONDS` (default 60)
- `DEEPSEEK_API_MAX_TOKENS` (default 4000)
- `DEEPSEEK_API_MODEL` (default `deepseek-chat`)
- `DEEPSEEK_API_URL` (default `https://api.deepseek.com/v1/chat/completions`)
- `DEEPSEEK_MODELS_URL` (optional; if set, used by `/models`)

Groq:
- `GROQ_API_KEY` (required when provider is `groq`)
- `GROQ_API_TIMEOUT_SECONDS` (default 60)
- `GROQ_API_MAX_TOKENS` (default 4000)
- `GROQ_API_MODEL` (default `moonshotai/kimi-k2-instruct`)
- `GROQ_API_URL` (default `https://api.groq.com/openai/v1/chat/completions`)
- `GROQ_MODELS_URL` (default `https://api.groq.com/openai/v1/models`)
- `GROQ_LLAMA3_1_8B_MODEL` (optional for `model_compare.py`, default `llama-3.1-8b-instant`)
- `GROQ_LLAMA3_1_70B_MODEL` (optional for `model_compare.py`, default `llama-3.1-70b-versatile`)
- `DEEPSEEK_CHAT_MODEL` (optional for `model_compare.py`, default `deepseek-chat`)

Context persistence:
- `DEEPSEEK_PERSIST_CONTEXT` (default `true`)
- `DEEPSEEK_CONTEXT_PATH` (default `~/.deepseek_chat/context.json`)
- `DEEPSEEK_WEB_CONTEXT_PATH` (optional override for web UI)
- `DEEPSEEK_CONTEXT_MAX_MESSAGES` (default 40)

Context compression:
- `DEEPSEEK_COMPRESSION_ENABLED` (default `false`)
- `DEEPSEEK_COMPRESSION_THRESHOLD` (default 10)
- `DEEPSEEK_COMPRESSION_KEEP` (default 4)

## OptionalRequestParams (code-only)
Edit defaults in `deepseek_chat/core/config.py`:
`temperature`, `frequency_penalty`, `presence_penalty`, `response_format`, `stop`, `thinking`

## Notes
- Streaming parses `data:` chunks.
- Web UI Streams via SSE at `/stream`.
- Web UI has an agent selector and a Settings Modal ⚙️ (Temperature, Top P).
- **Web UI Features**:
  - Full Markdown parsing with syntax highlighting and ``Copy`` buttons for code blocks.
  - Generates answers dynamically, can be cancelled mid-stream using the **Stop 🛑** button.
  - Sidebar: Displays autonomous chat sessions (branches) with auto-generated titles. Users can switch between them and delete them.
  - **Memory/Brain (🧠)**: Global Explicit Memory. Users can save working and long-term memory constraints shared across all sessions. Working memory auto-clears on `/clear`, long-term persists forever.
  - **Profile (👤)**: Global User Profile. Modifies agent responses with strict styling, formatting, and constraints across all sessions.
  - **Invariants (🛡️)**: Global hard constraints (architecture, stack, business rules) that the assistant must never violate. When a request conflicts with an invariant, the assistant refuses and explains which invariant would be broken.
  - **MCP Servers (🔌)**: Dynamically connect to Model Context Protocol servers to give the agent new tools (e.g. Hacker News API, Postgres, Local scripts). Managed by `MCPManager` and persisted by `MCPRegistry`. Tools are automatically prefix-routed to prevent namespace collisions. Default servers: `demo_server.py` (Hacker News API), `scheduler_server.py` (background task scheduler), `pipeline_server.py` (Day 19: search→summarize→save_to_file pipeline).
  - **Scheduler (📅)**: Background task scheduler MCP server. Supports reminders, periodic data collection, and automated summaries. Tasks stored in SQLite (`~/.deepseek_chat/scheduler.db`), executed by a background runner (30s tick interval). Schedule formats: `once`, `every_Nm`, `every_Nh`, `daily_HH:MM`. UI panel shows task stats, list, and recent results with auto-refresh.
  - **Chat / Agent Modes**: A unified input field allows tossing between standard `Chat` mode and autonomous `Agent` mode where tasks are managed via a state machine.
- **Automatic Context Optimization**: Combines sliding window (last N messages intact) + compression (summarize older messages) + auto-facts extraction (key facts auto-populate Working Memory during compression). No user configuration needed.
- **Task State Machine (Agent Mode)**: Structured task execution as FSM (`idle→planning→execution→validation→done`). Supports pause/resume on any phase. User approves plan and final completion; agent auto-advances execution steps. Per-session state is persisted. A collapsible UI panel shows progress, steps, transition history, and action buttons. The API handles state transitions (`POST /task/approve|pause|resume|complete`), and clients fetch the latest state seamlessly without refresh (`GET /task`). **Controlled transitions**: a declarative `ALLOWED_TRANSITIONS` map enforces valid phase changes; invalid attempts raise `InvalidTransitionError`. The system prompt injects allowed transitions and a strict no-skip rule. API responses include `allowed_transitions` so the frontend renders buttons dynamically. A `transition_log` records every phase change with timestamps.
- Web UI shows a stats panel with API usage, cost, and session cost (auto-hides when empty).
- `AndroidAgent` injects an Android-focused `system` prompt, `GeneralAgent` is for general conversation.
- API usage tokens (prompt/completion/total) are shown when provided by the provider.
- If context length is exceeded, the client raises a clear `Context length exceeded` error.
- `/provider` prints current provider and model.
- `/models` lists available models for the current provider (if models endpoint is configured).
- `/clear` clears chat context (and overwrites persisted context if enabled).
- `/context` shows chat history size.
- Persisted context loads on startup when `DEEPSEEK_PERSIST_CONTEXT=true`.
- `python3 -m deepseek_chat.core.comparing.model_compare --prompt "..."` — сравнивает Llama-3.1-8B (weak), Llama-3.1-70B (medium) и DeepSeek (API).
- If behavior seems stale, run clean script (removes `__pycache__`).

## Web UI Static/Templates Example

- CSS: `deepseek_chat/web/static/style.css`
- JS: `deepseek_chat/web/static/app.js`
- HTML: `deepseek_chat/web/templates/index.html`
- FastAPI serves static files and renders template via Jinja2



## Architecture Rules (enforced)
- `agents/` must never import from `web/`. `BaseAgent` receives `mcp_manager` only via constructor.
- `web/state.py:get_agent()` always passes `mcp_manager=_mcp_manager` explicitly.
- Config overrides use `dataclasses.replace(_config, ...)` — never manually reconstruct `ClientConfig`.
- All imports at module top level — no inline imports inside functions or loops.
- `BaseAgent._skip_after_stream_markers` is a declared class attribute (not duck-injected).

## Tests
Run: `python3 -m pytest tests/`

| File | Covers |
|---|---|
| `test_config.py` | `core/config.py` — env parsing, providers |
| `test_session.py` | `core/session.py` — history, trim, clone, persistence |
| `test_memory.py` | `core/memory.py` — working/long-term, persistence |
| `test_profile.py` | `core/profile.py` — fields, persistence |
| `test_invariants.py` | `core/invariants.py` — add/remove, prompt injection |
| `test_task_state.py` | `core/task_state.py` — FSM transitions, serialization |
| `test_cost_tracker.py` | `web/cost_tracker.py` |
| `test_hooks.py` | `agents/hooks/` — TaskState, Memory, Profile, Invariant |
| `test_auto_title_hook.py` | `agents/hooks/auto_title.py` — trigger logic, LLM errors |
| `test_strategies.py` | `agents/strategies.py` — history building, compression flags |
| `test_streaming_markers.py` | `web/streaming.py` — `_collect_task_markers`, `_apply_task_markers` |
| `test_mcp_registry.py` | `core/mcp_registry.py` — CRUD, persistence |
| `test_scheduler_store.py` | `mcp_servers/scheduler/scheduler_store.py` |
| `test_scheduler_utils.py` | `mcp_servers/scheduler/scheduler_utils.py` — `compute_next_run()` |

## Maintenance Rule
After any code changes, verify `PROJECT_CONTEXT.md` and update it if needed.

## Persisted Context File (format)
Default path: `~/.deepseek_chat/context.json`
Structure:
{
  "format_version": 1,
  "provider": "deepseek",
  "model": "deepseek-chat",
  "updated_at": "2025-01-01T12:00:00Z",
  "summary": "This is a summary of older compressed messages.",
  "messages": [
    {"role": "user", "content": "Привет"},
    {"role": "assistant", "content": "Привет! Чем помочь?"}
  ]
}

## Global Memory File
Default path: `~/.deepseek_chat/memory.json`
Structure:
{
  "working_memory": ["Need to optimize DB queries"],
  "long_term_memory": ["Project uses Python 3.10+"]
}

## Global Profile File
Default path: `~/.deepseek_chat/profile.json`
Structure corresponds to `UserProfile` parameters like `name`, `role`, `style_preferences`, `formatting_rules`, and `constraints`.

## Global Invariants File
Default path: `~/.deepseek_chat/invariants.json`
Structure:
{
  "invariants": ["Only Kotlin, no Java", "Clean Architecture + MVVM"]
}

## Quick Verification
1. Run the app, send a couple of messages.
2. Exit and restart the app — context should be restored.
3. Run `/clear` and restart — context should be empty.
4. Add memory facts in one session — they should appear in all sessions.
