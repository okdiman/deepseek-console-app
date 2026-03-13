# Architecture Guidelines — DeepSeek Chat

## Goals
- Keep the app **simple, readable, and reliable**.
- Favor **small, explicit modules** over frameworks.
- Minimize implicit magic; prefer straightforward control flow.

## Architectural Style
- **Layered architecture** with strict dependency direction (higher → lower, never reverse):
  - **Interface layer**: console I/O, Web UI, SSE streaming (`console/app.py`, `web/`)
  - **Agent layer**: LLM orchestration, hook pipelines, context strategies (`agents/`)
  - **Domain layer**: chat history, task state machine (`session.py`, `task_state.py`)
  - **Data layer**: global persistent stores — Memory, Profile, Invariants (`core/`)
  - **Client/integration layer**: HTTP API calls & streaming parsing (`client.py`)
  - **Configuration layer**: runtime configuration (`config.py`)
  - **MCP layer**: external tool servers and their manager (`mcp_manager.py`, `mcp_registry.py`, `mcp_servers/`)
- **Single responsibility per module**.
- **Agents must never import from the web layer.** `BaseAgent` receives `mcp_manager` via constructor. Use `agent_factory.py` to build agents outside web context.

## Core Patterns

### Hook/Middleware pattern
`AgentHook` ABC defines three lifecycle methods:
- `before_stream()` — modify the system prompt before the LLM call
- `intercept_stream()` — optionally short-circuit the LLM call entirely (return a string to skip the LLM)
- `after_stream()` — run background work after the full response

Hooks modify behavior without touching agent internals. Current hooks:
`MemoryInjectionHook`, `UserProfileHook`, `InvariantGuardHook`, `TaskStateHook`, `AutoTitleHook`.

### Unified context strategy
`UnifiedStrategy` combines sliding window + compression + auto-facts extraction.
On compression trigger: single LLM call returns JSON with summary + extracted facts.
Extracted facts auto-populate Working Memory.

### Task State Machine (Agent mode)
`TaskStateMachine` is a FSM: `idle → planning → execution → validation → done`.
Declarative `ALLOWED_TRANSITIONS` map enforces valid phase changes; invalid attempts raise `InvalidTransitionError`.
The agent embeds task state markers (`[STEP_DONE]`, `[READY_FOR_VALIDATION]`, etc.) in its responses.
Live marker parsing in `streaming.py` (`_collect_task_markers`, `_apply_task_markers`) advances the FSM in real time during SSE streaming. `TaskStateHook.after_stream` handles planning-phase extraction and resume logic.

### MCP (Model Context Protocol)
`MCPManager` manages lifecycles of external tool servers (stdio subprocesses) with auto-restart and graceful shutdown.
`MCPRegistry` persists server configs to `~/.deepseek_chat/mcp_servers.json`.
Tools are prefix-routed (`server_id__tool_name`) to avoid namespace collisions.
`MCPManager` is always injected into agents via constructor — no hidden singleton lookups.

### Agent factory
`agent_factory.py` provides `build_background_agent()` — creates agents without importing the web layer.
Use this in `scheduler_runner.py` and any non-web context.

### Explicit configuration
Optional request parameters are defined **only in code** (`OptionalRequestParams`).

### Pure data structures
Messages are plain dicts with `role` and `content`.

## Global Persistent State
Three data stores persist globally across all sessions:
- **Memory** (`~/.deepseek_chat/memory.json`): Working memory (session-scoped, auto-cleared on `/clear`) and long-term memory. Injected via `MemoryInjectionHook`.
- **Profile** (`~/.deepseek_chat/profile.json`): User name, role, style preferences, constraints. Injected via `UserProfileHook`.
- **Invariants** (`~/.deepseek_chat/invariants.json`): Hard constraints the assistant must never violate. Injected via `InvariantGuardHook`.

All three are loaded from disk on every request to reflect real-time edits.

## Error Handling
- Fail fast on missing required config (`API_KEY`).
- Surface network or API errors clearly and without retries unless explicitly added.
- Keep error messages user-readable in the console loop.

## Streaming
- Streaming is the default behavior.
- Parse only lines starting with `data:`.
- Ignore malformed JSON chunks safely (skip and continue).
- SSE marker helpers (`_collect_task_markers`, `_apply_task_markers`) are pure functions — testable without HTTP context.

## Configuration Rules
- Environment variables are used for core config and persistence settings.
- Optional model parameters (`temperature`, `frequency_penalty`, etc.) are **code-only**.
- Override web context path via `DEEPSEEK_WEB_CONTEXT_PATH`; use `dataclasses.replace()` — never manually reconstruct config objects.

## Code Organization Rules
- **No logic in `main.py` (root)** beyond bootstrapping.
- `console/main.py` orchestrates assembly for the CLI.
- `web/app.py` wires FastAPI router and static files for the Web UI.
- Keep cross-module imports **minimal and explicit**.
- Inline imports inside functions are banned — all imports go at the module top level.

## Testing
- Unit tests live in `tests/`. Run with `pytest`.
- Pure functions and data models are tested without mocks (session, task_state, config, etc.).
- Hook tests use `unittest.mock.MagicMock` for agent and LLM client.
- Streaming helper tests (`test_streaming_markers.py`) use real `TaskStateMachine` instances.
- Web-layer imports in tests require `DEEPSEEK_API_KEY` to be set (use `os.environ.setdefault`).
- Do **not** mock the database in scheduler tests — use a real SQLite temp file.

## Naming & Style
- Use clear, descriptive names.
- Prefer type hints for public methods and data structures.
- Keep functions short and focused; avoid multi-purpose functions.

## Extension Guidelines
When adding features:
- Place UI/CLI behavior in `console/app.py` or `web/`.
- Place API changes in `client.py`.
- Place agent orchestration logic in `agents/base_agent.py`.
- Add new agent behaviors as `AgentHook` subclasses in `agents/hooks/`.
- Add new context management approaches as `ContextStrategy` subclasses in `agents/strategies.py`.
- Place stateful conversation behavior in `session.py`.
- Place global persistent data models in `core/`.
- Keep configuration changes in `config.py`.
- After any code changes, verify `PROJECT_CONTEXT.md` and update it if needed.

## Non-Goals
- No heavy frameworks.
- No complex dependency injection.
