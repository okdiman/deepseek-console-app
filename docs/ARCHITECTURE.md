# Architecture Guidelines — DeepSeek Console App

## Goals
- Keep the app **simple, readable, and reliable**.
- Favor **small, explicit modules** over frameworks.
- Minimize implicit magic; prefer straightforward control flow.

## Architectural Style
- **Layered architecture** with clear boundaries:
  - **Interface layer**: console I/O, UX, commands (`console_app.py`, `stream_printer.py`)
  - **Domain/session layer**: chat history and message management (`session.py`)
  - **Client/integration layer**: HTTP API calls & streaming parsing (`client.py`)
  - **Configuration layer**: runtime configuration (`config.py`)
- **Single responsibility per module**.
- **Dependency direction**: higher-level layers depend on lower-level layers, never the reverse.

## Core Patterns
- **Composition over inheritance**:
  - `ConsoleApp` composes `DeepSeekClient` and `ChatSession`.
- **Explicit configuration**:
  - Optional request parameters are defined **only in code** (`OptionalRequestParams`).
- **Pure data structures**:
  - Messages are plain dicts with `role` and `content`.

## Error Handling
- Fail fast on missing required config (`DEEPSEEK_API_KEY`).
- Surface network or API errors clearly and without retries unless explicitly added.
- Keep error messages user-readable in the console loop.

## Streaming
- Streaming is the default behavior.
- Parse only lines starting with `data:`.
- Ignore malformed JSON chunks safely (skip and continue).

## Configuration Rules
- Environment variables are used **only** for core config:
  - API key, timeouts, max tokens, model, URL.
- Optional model parameters (`temperature`, `frequency_penalty`, etc.) are **code-only**.

## Code Organization Rules
- **No logic in `main.py` (root)** beyond bootstrapping.
- `deepseek_console_app/main.py` orchestrates assembly.
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
- Place UI/CLI behavior in `console_app.py`.
- Place API changes in `client.py`.
- Place stateful conversation behavior in `session.py`.
- Keep configuration changes in `config.py`.
- Keep new utilities small and scoped to one responsibility.

## Non-Goals
- No heavy frameworks.
- No complex dependency injection.
- No background services or daemons.
