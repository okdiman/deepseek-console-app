# DeepSeek Chat

Streaming chat application with DeepSeek / Groq / Ollama support. Includes a Web UI and console interface with multiple agents, MCP tool support, RAG, background task scheduler, and autonomous Agent mode.

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
    python_agent.py       # Python/RAG-focused agent
    dev_help_agent.py         # Developer assistant (RAG + filesystem + git tools)
    support_agent.py          # Customer support assistant (RAG + CRM tools)
    code_assistant_agent.py   # Goal-driven code assistant (search, edit, generate, audit)
    background_agent.py       # Minimal agent for scheduled background tasks
    strategies.py         # UnifiedStrategy: sliding window + compression + facts
    hooks/
      base.py             # AgentHook ABC
      memory_injection.py
      user_profile.py
      invariant_guard.py
      task_state.py       # Task FSM integration
      dialogue_task_hook.py
      rag_hook.py
      auto_title.py
  core/
    config.py             # ClientConfig dataclass + env loading
    client.py             # Streaming HTTP client
    session.py            # Chat history, branching, compression
    task_state.py         # Task State Machine (FSM)
    change_store.py       # Shared store for filesystem change proposals
    agent_factory.py      # Build agents without web imports
    paths.py              # PROJECT_ROOT, DATA_DIR
    stream_printer.py
    mcp/
      manager.py          # MCP server subprocess lifecycle
      registry.py         # MCP server config persistence
    memory/
      store.py            # Working + long-term memory
      profile.py          # User profile
      invariants.py       # Hard constraints
      dialogue.py         # Dialogue task tracker
    rag/                  # RAG pipeline (chunking, embedding, retrieval, reranking)
    comparing/            # Multi-model comparison utilities
  web/
    app.py                # FastAPI bootstrap
    routes.py             # All HTTP endpoints
    streaming.py          # SSE streaming + task marker parsing
    state.py              # Web-layer singletons
    cost_tracker.py
    static/               # CSS, JS
    templates/            # index.html
  console/
    main.py
    app.py
mcp_servers/
  demo_server.py          # Hacker News API MCP server
  filesystem_server.py    # Two-phase read/write + run_tests
  git_server.py           # Git info tools (branch, commits, diff, tree)
  crm_server.py           # CRM: users + tickets (for SupportAgent)
  pipeline_server.py      # Search → summarize → save pipeline
  scheduler/
    scheduler_server.py   # Scheduler MCP tool provider
    scheduler_runner.py   # Standalone background runner
    scheduler_store.py    # SQLite persistence
    scheduler_utils.py    # compute_next_run() — shared utility
tests/                    # 546 unit tests
```

## Web UI Features

- **Streaming** via SSE at `/stream` with live Markdown rendering and code highlighting
- **Stop button** — cancels mid-stream generation
- **Agents** — General, Python, Dev Help, Support, and Code Assistant agent selectable per session
- **Branches (sidebar)** — autonomous chat sessions with auto-generated titles; switch and delete
- **Memory (🧠)** — Working memory (clears on `/clear`) and long-term memory across all sessions
- **Profile (👤)** — Global user profile injected into every agent response
- **Invariants (🛡️)** — Hard constraints the assistant must never violate
- **MCP Servers (🔌)** — Dynamically connect external tool servers (toggle on/off, auto-restart)
- **Scheduler (📅)** — Background task scheduler: reminders, periodic data collection, daily summaries. Supports `once`, `every_Nm`, `every_Nh`, `daily_HH:MM` formats
- **Agent / Task mode** — Autonomous task execution via FSM (`idle → planning → execution → validation → done`) with plan approval, pause/resume, step tracking
- **Provider toggle** — Switch between DeepSeek, Groq, and Ollama at runtime without restart
- **Stats panel** — Token usage, API cost, session cost

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PROVIDER` | `deepseek` | `deepseek`, `groq`, or `ollama` |
| `DEEPSEEK_API_KEY` | — | Required for DeepSeek |
| `GROQ_API_KEY` | — | Required for Groq |
| `DEEPSEEK_API_MODEL` | `deepseek-chat` | Model name |
| `GROQ_API_MODEL` | `moonshotai/kimi-k2-instruct` | Model name |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Model name for Ollama |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `DEEPSEEK_PERSIST_CONTEXT` | `true` | Persist chat context between restarts |
| `DEEPSEEK_CONTEXT_PATH` | `~/.deepseek_chat/context.json` | Context file path |
| `DEEPSEEK_WEB_CONTEXT_PATH` | — | Override context path for Web UI |
| `DEEPSEEK_CONTEXT_MAX_MESSAGES` | `40` | Sliding window size |
| `DEEPSEEK_COMPRESSION_ENABLED` | `false` | Enable context compression |
| `DEEPSEEK_COMPRESSION_THRESHOLD` | `10` | User messages before compressing |
| `DEEPSEEK_COMPRESSION_KEEP` | `4` | Recent messages kept raw after compression |
| `SERVICE_HOST` | `127.0.0.1` | Bind address (use `0.0.0.0` for network access) |
| `SERVICE_PORT` | `8000` | Bind port |
| `SERVICE_API_KEY` | — | If set, `X-API-Key` header required on all requests |
| `RATE_LIMIT_PER_MINUTE` | `60` | Max requests per IP per minute |

Optional request parameters (`temperature`, `frequency_penalty`, `presence_penalty`, `response_format`, `stop`, `thinking`) are set in code via `OptionalRequestParams` in `core/config.py`.

## Console Commands

- `/help` — show help
- `/help <question>` — ask Dev Help agent about the project
- `/provider` — show current provider and model
- `/models` — list available models
- `/clear` — clear chat context
- `/context` — show history size
- `/apply <id>` — apply a pending filesystem change proposal
- `/discard <id>` — discard a pending filesystem change proposal
- `/quit` or `/exit` — exit

## Model Comparison

```shell
python3 -m deepseek_chat.core.comparing.model_compare --prompt "..."
```

## Tests

```shell
python3 -m pytest tests/        # 546 tests
python3 -m pytest tests/ -v     # verbose
```

## Common Issues

- **`DEEPSEEK_API_KEY not found`** — check `.env` and the key name
- **Network errors** — check your internet connection and key validity
- **Stale behavior** — run `./scripts/run_clean.sh` to clear `__pycache__`

---
MIT License
