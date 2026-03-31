# DeepSeek Chat

Streaming chat application with DeepSeek/Groq API. Includes a Web UI and console interface with multiple agents, MCP tool support, background task scheduler, and autonomous Agent mode.

## Quick Start

```shell
git clone https://github.com/okdiman/deepseek-chat.git
cd deepseek-chat
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and add your key(s):

```dotenv
PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

Run:

```shell
# Console
python3 -m deepseek_chat.console.main
# Web UI
python3 -m deepseek_chat.web.app
```

Clean run (removes `__pycache__`):

```shell
chmod +x scripts/run_clean.sh && ./scripts/run_clean.sh
```

## Project Structure

```
deepseek_chat/
  agents/
    base_agent.py         # Pipeline orchestrator — hook lifecycle
    general_agent.py      # General-purpose agent
background_agent.py   # Minimal agent for scheduled background tasks
    strategies.py         # UnifiedStrategy: sliding window + compression + facts
    hooks/
      base.py             # AgentHook ABC
      memory_injection.py
      user_profile.py
      invariant_guard.py
      task_state.py       # Task FSM integration
      auto_title.py
  core/
    config.py             # ClientConfig dataclass + env loading
    client.py             # Streaming HTTP client
    session.py            # Chat history, branching, compression
    task_state.py         # Task State Machine (FSM)
    memory.py             # Working + long-term memory
    profile.py            # User profile
    invariants.py         # Hard constraints
    mcp_manager.py        # MCP server lifecycle manager
    mcp_registry.py       # MCP server config persistence
    agent_factory.py      # Build agents without web imports
    stream_printer.py
    comparing/            # Multi-model comparison utilities
  web/
    app.py                # FastAPI bootstrap
    routes.py             # All HTTP endpoints
    streaming.py          # SSE streaming + task marker parsing
    state.py              # Web-layer singletons
    views.py              # Jinja2 template rendering
    cost_tracker.py
    static/               # CSS, JS
    templates/            # index.html
  console/
    main.py
    app.py
mcp_servers/
  demo_server.py          # Hacker News API MCP server
  pipeline_server.py      # Search → summarize → save pipeline
  scheduler/
    scheduler_server.py   # Scheduler MCP tool provider
    scheduler_runner.py   # Standalone background runner
    scheduler_store.py    # SQLite persistence
    scheduler_utils.py    # compute_next_run() — shared utility
tests/                    # 323 unit tests
docs/
  ARCHITECTURE.md
  PROJECT_CONTEXT.md
```

## Web UI Features

- **Streaming** via SSE at `/stream` with live Markdown rendering and code highlighting
- **Stop button** — cancels mid-stream generation
- **Agents** — General and Android agent selectable per session
- **Branches (sidebar)** — autonomous chat sessions with auto-generated titles; switch and delete
- **Memory (🧠)** — Working memory (clears on `/clear`) and long-term memory across all sessions
- **Profile (👤)** — Global user profile injected into every agent response
- **Invariants (🛡️)** — Hard constraints the assistant must never violate
- **MCP Servers (🔌)** — Dynamically connect external tool servers (toggle on/off, auto-restart)
- **Scheduler (📅)** — Background task scheduler: reminders, periodic data collection, daily summaries. Supports `once`, `every_Nm`, `every_Nh`, `daily_HH:MM` formats
- **Agent / Task mode** — Autonomous task execution via FSM (`idle → planning → execution → validation → done`) with plan approval, pause/resume, step tracking
- **Stats panel** — Token usage, API cost, session cost

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PROVIDER` | `deepseek` | `deepseek` or `groq` |
| `DEEPSEEK_API_KEY` | — | Required for DeepSeek |
| `GROQ_API_KEY` | — | Required for Groq |
| `DEEPSEEK_API_MODEL` | `deepseek-chat` | Model name |
| `GROQ_API_MODEL` | `moonshotai/kimi-k2-instruct` | Model name |
| `DEEPSEEK_PERSIST_CONTEXT` | `true` | Persist chat context between restarts |
| `DEEPSEEK_CONTEXT_PATH` | `~/.deepseek_chat/context.json` | Context file path |
| `DEEPSEEK_WEB_CONTEXT_PATH` | — | Override context path for Web UI |
| `DEEPSEEK_CONTEXT_MAX_MESSAGES` | `40` | Sliding window size |
| `DEEPSEEK_COMPRESSION_ENABLED` | `false` | Enable context compression |
| `DEEPSEEK_COMPRESSION_THRESHOLD` | `10` | User messages before compressing |
| `DEEPSEEK_COMPRESSION_KEEP` | `4` | Recent messages kept raw after compression |

Optional request parameters (`temperature`, `frequency_penalty`, `presence_penalty`, `response_format`, `stop`, `thinking`) are set in code via `OptionalRequestParams` in `core/config.py`.

## Console Commands

- `/help` — show help
- `/provider` — show current provider and model
- `/models` — list available models
- `/clear` — clear chat context
- `/context` — show history size
- `/quit` or `/exit` — exit

## Model Comparison

```shell
python3 -m deepseek_chat.core.comparing.model_compare --prompt "..."
```

## Tests

```shell
python3 -m pytest tests/        # 323 tests
python3 -m pytest tests/ -v     # verbose
```

## Common Issues

- **`DEEPSEEK_API_KEY not found`** — check `.env` and the key name
- **Network errors** — check your internet connection and key validity
- **Stale behavior** — run `./scripts/run_clean.sh` to clear `__pycache__`

---
MIT License
