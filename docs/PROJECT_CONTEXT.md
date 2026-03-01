# Project Context — DeepSeek Console App (Quick Reference)

Architecture guidelines: `docs/ARCHITECTURE.md`

## What it is
Console app for streaming chat with DeepSeek Chat Completions API, using an Android-focused agent.

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
- `deepseek_chat/agents/android_agent.py` — Android-focused agent + system prompt
- `deepseek_chat/agents/general_agent.py` — General-purpose agent
- `deepseek_chat/core/session.py` — message history (with compression support)
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
- `DEEPSEEK_COMPRESSION_ENABLED` (default `true`)
- `DEEPSEEK_COMPRESSION_THRESHOLD` (default 10)
- `DEEPSEEK_COMPRESSION_KEEP` (default 4)

## OptionalRequestParams (code-only)
Edit defaults in `deepseek_chat/core/config.py`:
`temperature`, `frequency_penalty`, `presence_penalty`, `response_format`, `stop`, `thinking`

## Notes
- Streaming parses `data:` chunks.
- Web UI Streams via SSE at `/stream`.
- Web UI has an agent selector and a Strategy selector (for General Agent).
- **Web UI Sidebar**: Displays autonomous chat sessions (branches) with auto-generated titles. Users can switch between them and delete them.
- **Context Strategies (GeneralAgent)**:
  - `default`: Folds old context into a running summary to save tokens.
  - `window`: Strict N-message sliding window. Forgets older text entirely.
  - `facts`: Extracts and strictly persists key user requirements in a background process.
  - `branching`: Isolates conversation timelines. Users can branch off old messages into new parallel sessions.
- Web UI shows a stats panel with local tokens, API usage, cost, and session cost (auto-hides when empty).
- `AndroidAgent` injects an Android-focused `system` prompt, `GeneralAgent` is for general conversation and supports the distinct Context Strategies.
- Local token counting is shown in the CLI: request, full history, and response (uses `tiktoken` if available, otherwise a heuristic).
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

## Quick Verification
1. Run the app, send a couple of messages.
2. Exit and restart the app — context should be restored.
3. Run `/clear` and restart — context should be empty.
