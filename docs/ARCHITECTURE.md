# Architecture Guidelines — DeepSeek Chat

## Goals
- Keep the app **simple, readable, and reliable**.
- Favor **small, explicit modules** over frameworks.
- Minimize implicit magic; prefer straightforward control flow.

## Architectural Style
- **Layered architecture** with clear boundaries:
  - **Interface layer**: console I/O, Web UI, SSE streaming (`console/app.py`, `web/`)
  - **Agent layer**: LLM orchestration, hook pipelines, context strategies (`agents/`)
  - **Domain/session layer**: chat history, message management, persistence (`session.py`)
  - **Data layer**: global persistent stores — Memory & Profile (`memory.py`, `profile.py`)
  - **Client/integration layer**: HTTP API calls & streaming parsing (`client.py`)
  - **Configuration layer**: runtime configuration (`config.py`)
- **Single responsibility per module**.
- **Dependency direction**: higher-level layers depend on lower-level layers, never the reverse.

## Core Patterns
- **Composition over inheritance**:
  - `BaseAgent` composes `DeepSeekClient`, `ChatSession`, and a list of `AgentHook` instances.
  - `ConsoleApp` composes `DeepSeekClient`, `ChatSession`, and `AndroidAgent`.
- **Hook/Middleware pattern** for agent behavior:
  - `AgentHook` ABC defines `before_stream()` and `after_stream()` lifecycle methods.
  - Hooks modify the system prompt or inject context without touching agent internals.
  - Current hooks: `MemoryInjectionHook`, `UserProfileHook`, `AutoTitleHook`.
- **Strategy pattern** for context management:
  - `ContextStrategy` ABC with `process_context()` and `build_history_messages()`.
  - Strategies: `DefaultStrategy` (compression), `WindowStrategy`, `FactsStrategy`.
- **Explicit configuration**:
  - Optional request parameters are defined **only in code** (`OptionalRequestParams`).
- **Pure data structures**:
  - Messages are plain dicts with `role` and `content`.

## Global Persistent State
Two data stores persist globally across all sessions (similar to app-level settings):
- **Memory** (`~/.deepseek_chat/memory.json`): Working memory and long-term memory facts.
  Injected via `MemoryInjectionHook` as a late system message in the conversation history.
- **Profile** (`~/.deepseek_chat/profile.json`): User name, role, style preferences, constraints.
  Injected via `UserProfileHook` into the system prompt.

Both are loaded from disk on every request to ensure real-time updates.

## Error Handling
- Fail fast on missing required config (`API_KEY`).
- Surface network or API errors clearly and without retries unless explicitly added.
- Keep error messages user-readable in the console loop.

## Streaming
- Streaming is the default behavior.
- Parse only lines starting with `data:`.
- Ignore malformed JSON chunks safely (skip and continue).

## Configuration Rules
- Environment variables are used for core config and persistence settings:
  - API key, timeouts, max tokens, model, URL.
  - Context persistence: enable/disable, storage path, max messages.
- Optional model parameters (`temperature`, `frequency_penalty`, etc.) are **code-only**.

## Code Organization Rules
- **No logic in `main.py` (root)** beyond bootstrapping.
- `console/main.py` orchestrates assembly for the CLI.
- `web/app.py` wires FastAPI router and static files for the Web UI.
- Keep cross-module imports **minimal and explicit**.

## Naming & Style
- Use clear, descriptive names.
- Prefer type hints for public methods and data structures.
- Keep functions short and focused; avoid multi-purpose functions.

## Testing & Debugging
- Use small scripts (e.g., `test_api.py`, `compare_responses.py`) for verification.
- Add debug logging only temporarily and remove when done.
- Avoid changing behavior just to satisfy diagnostics.

## Extension Guidelines
When adding features:
- Place UI/CLI behavior in `console/app.py` or `web/`.
- Place API changes in `client.py`.
- Place agent orchestration logic in `agents/base_agent.py`.
- Add new agent behaviors as `AgentHook` subclasses in `agents/hooks.py`.
- Add new context management approaches as `ContextStrategy` subclasses in `agents/strategies.py`.
- Place stateful conversation behavior in `session.py`.
- Place global persistent data models in `core/` (e.g., `memory.py`, `profile.py`).
- Keep configuration changes in `config.py`.
- Keep new utilities small and scoped to one responsibility.
- After any code changes, verify `PROJECT_CONTEXT.md` and update it if needed.

## Non-Goals
- No heavy frameworks.
- No complex dependency injection.
- No background services or daemons.
