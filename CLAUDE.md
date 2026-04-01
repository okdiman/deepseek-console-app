# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation update — MANDATORY after every change

**This is not optional.** After implementing any feature or fix, you MUST update docs before finishing. Do it in this order:

1. **`_HOW_IT_WORKS.md` for every touched package** — if you changed a file inside a package that has a `_HOW_IT_WORKS.md`, update that file. Check the table below to find the right one. Concretely: changed a default value → update the config table; changed a function's behavior → update the description; added a new concept → add a section.

2. **`README.md`** — update if: new features added, commands changed, new agents/tools introduced, architecture diagram affected, new env vars relevant to users.

3. **`CLAUDE.md`** — update if: new env vars were added, architecture changed, new patterns introduced, commands changed, new files added to the persistent state table.

**How to know which `_HOW_IT_WORKS.md` to update:** look at every file you edited, find its package in the table below, update that package's doc. If you edited files in 3 packages, update 3 docs.

**Common mistakes to avoid:**
- Changing a default value in code but leaving the old value in the docs
- Adding a new function/hook/endpoint but not describing it anywhere
- Finishing the task and only then remembering about docs — update them as the last step, not as an afterthought

## Package documentation (_HOW_IT_WORKS.md)

Each major package has a `_HOW_IT_WORKS.md` that explains its internals in detail. These are the authoritative source for understanding how a subsystem works — read them before making changes to the relevant package, and update them when the behavior, structure, or interfaces change.

| File | Covers |
|------|--------|
| `deepseek_chat/agents/_HOW_IT_WORKS.md` | Agent pipeline, BaseAgent lifecycle, all hooks, concrete agents, hook execution order |
| `deepseek_chat/agents/hooks/_HOW_IT_WORKS.md` | AgentHook interface, all concrete hooks internals, suppress_tools, execution order |
| `deepseek_chat/core/_HOW_IT_WORKS.md` | Config, DeepSeekClient, ChatSession, TaskStateMachine, agent_factory, paths, stream_printer |
| `deepseek_chat/core/memory/_HOW_IT_WORKS.md` | MemoryStore, UserProfile, InvariantStore, DialogueTask — persistence and prompt injection patterns |
| `deepseek_chat/core/mcp/_HOW_IT_WORKS.md` | MCPManager subprocess lifecycle, MCPRegistry, tool routing, tool call flow |
| `deepseek_chat/core/rag/_HOW_IT_WORKS.md` | Full RAG pipeline: chunking, embedding, retrieval, reranking, citations, anti-hallucination |
| `mcp_servers/_HOW_IT_WORKS.md` | MCP server protocol, server list, how to write and register a new server |
| `mcp_servers/scheduler/_HOW_IT_WORKS.md` | Scheduler architecture: store schema, schedule formats, MCP tools, runner tick logic, task executors |

## Testing rules

**Never skip failing tests.** If a test fails after a change, fix the root cause — do not `--ignore` the file, skip the test, or comment it out. Failing tests reveal real bugs (example: `auto_title.py` fired on odd message counts because the even-check was missing). Always run the full suite and fix every failure before finishing.

## Commands

```bash
# Run web UI (http://127.0.0.1:8000)
python3 -m deepseek_chat.web.app

# Run console/CLI app
python3 -m deepseek_chat.console.main

# Clean run (removes __pycache__ first)
./scripts/run_clean.sh

# Run all tests
python3 -m pytest tests/

# Run a single test file
python3 -m pytest tests/test_session.py -v

# Run a specific test
python3 -m pytest tests/test_task_state.py::TestTaskStateMachine::test_transition -v

# Multi-model comparison utility
python3 -m deepseek_chat.core.comparing.model_compare --prompt "..."

# Day 32 — Automated PR code review
python scripts/review_pr.py --diff diff.patch [--changed-files file1.py file2.py]
git diff origin/main...HEAD | python scripts/review_pr.py
# GitHub Action: .github/workflows/pr_review.yml (triggers automatically on PR)

# RAG — download corpus documents (run once)
python3 scripts/download_corpus.py

# RAG — index + search + compare (requires Ollama running)
python3 experiments/rag_compare/cli.py index
python3 experiments/rag_compare/cli.py search --query "how does attention work?"
python3 experiments/rag_compare/cli.py compare
python3 experiments/rag_compare/cli.py stats
python3 experiments/rag_compare/cli.py citations            # citation & IDK check (Day 24)
python3 experiments/rag_compare/cli.py citations --save     # save to data/citation_check_report.json

# RAG mini-chat with dialogue task memory (Day 25)
python3 experiments/rag_compare/rag_chat.py

# Day 28 — Local LLM vs Cloud LLM RAG comparison
python3 experiments/rag_compare/cli.py local-vs-cloud --save

# Day 30 — Run as private network service (bind to 0.0.0.0)
SERVICE_HOST=0.0.0.0 SERVICE_PORT=8000 python3 -m deepseek_chat.web.app
# With auth + rate limit:
SERVICE_API_KEY=secret RATE_LIMIT_PER_MINUTE=30 python3 -m deepseek_chat.web.app
# Health check (no auth required):
curl http://127.0.0.1:8000/health
# Stability test (requires service running):
python3 experiments/stability_test.py --concurrency 3 --requests 9

# Day 29 — Local LLM optimization (parameter + prompt profiling)
python3 experiments/rag_compare/cli.py optimize
python3 experiments/rag_compare/cli.py optimize --save
python3 experiments/rag_compare/cli.py optimize --profiles baseline,quality --save
```

## Architecture

The app is a streaming AI chat system with DeepSeek/Groq API support. It has two frontends (web UI and console CLI) sharing the same agent/core layer.

### Strict Dependency Rule

```
Interface (web/console) → Agent → Domain (core) → Data (session/memory) → Client → Config
```

**Agents never import from the web layer.** The `core/agent_factory.py` exists specifically to build agents for the background scheduler without touching web imports.

Additional constraints:
- `web/state.py → get_agent()` always passes `mcp_manager=_mcp_manager` explicitly
- Config overrides use `dataclasses.replace(_config, ...)` — never manually reconstruct `ClientConfig`
- All imports at module top level — no inline imports inside functions or loops
- `BaseAgent._skip_after_stream_markers` is a declared class attribute, not duck-injected
- `core/paths.py` exports `PROJECT_ROOT` (absolute, anchored to the source file) and `DATA_DIR`; use these — never hardcode paths or use `os.getcwd()`

### Agent Pipeline

`BaseAgent` (`agents/base_agent.py`) orchestrates each reply:
1. **before_stream hooks** — modify the system prompt (memory injection, profile, invariants, task state)
2. **intercept_stream hooks** — optionally short-circuit LLM entirely
3. **Stream LLM response** — handles tool calls inline; if tools are called, re-enters the stream loop
4. **after_stream hooks** — background work (auto-title generation, etc.)

Concrete agents differ only in their system prompts and hook stacks:

| Agent | Hook stack | Entry points |
|-------|-----------|--------------|
| `GeneralAgent` | Memory, Profile, Invariants, TaskState, AutoTitle | Web UI default |
| `PythonAgent` | Rag, Memory, DialogueTask, Profile, Invariants, AutoTitle | Web UI "Python" option |
| `DevHelpAgent` | Rag, AutoTitle | `/help <question>` (console + web) |
| `SupportAgent` | Rag, AutoTitle | Web UI "Support" option; FAQ + CRM tools |
| `CodeReviewAgent` | Rag | `scripts/review_pr.py` + GitHub Actions |
| `BackgroundAgent` | *(none)* | Scheduler background tasks |

### Hook System

All hooks inherit `AgentHook` (`agents/hooks/base.py`) with three async methods:
- `before_stream` → returns modified system prompt string
- `intercept_stream` → returns string to skip LLM, or `None` to proceed
- `after_stream` → returns nothing, runs post-response logic

Active hooks are assembled by `web/state.py → get_agent()` and injected via the constructor.

`PythonAgent` hook stack (in order): `RagHook → MemoryInjectionHook → DialogueTaskHook → UserProfileHook → InvariantGuardHook → AutoTitleHook`

`DevHelpAgent` hook stack: `RagHook → AutoTitleHook` (no memory/profile hooks to keep answers doc-focused)

`SupportAgent` hook stack: `RagHook → AutoTitleHook` (same structure as DevHelpAgent; uses CRM MCP tools for ticket/user context)

### Dialogue Task Memory (Day 25)

`DialogueTask` (`core/dialogue_task.py`) — lightweight structured tracker for the current conversation:
- `goal` — what the user wants to achieve in this dialogue
- `clarifications` — facts the user has clarified
- `constraints` — rules / terms fixed by the user
- `explored_topics` — topics already covered in depth

Updated via markers the agent embeds in responses:
```
[GOAL: ...]  [CLARIFIED: ...]  [CONSTRAINT: ...]  [TOPIC: ...]
```

`DialogueTaskHook` (`agents/hooks/dialogue_task_hook.py`) — injects task memory into system prompt (`before_stream`) and parses markers from agent response (`after_stream`). Persists to `DIALOGUE_TASK_PATH` (default: `<DATA_DIR>/dialogue_task.json`). Cleared on `/clear` in `rag_chat.py`.

`RagHook.last_chunks` — after each `before_stream` call the list of retrieved chunks is stored on the hook instance so the demo CLI can display them separately.

### Context Strategy

`UnifiedStrategy` (`agents/strategies.py`) processes conversation history before each LLM call:
- **Sliding window**: keeps last N messages intact
- **Compression**: summarizes older messages in a single LLM call
- **Auto-facts extraction**: populates Working Memory from compressed content

### Task State Machine (FSM)

`TaskStateMachine` (`core/task_state.py`) enforces phase transitions:
```
idle → planning → execution → validation → done
              ↓_________paused__________↑
```
The agent embeds special markers in its output (`[STEP_DONE]`, `[READY_FOR_VALIDATION]`, etc.), parsed by `web/streaming.py` during SSE streaming to trigger FSM transitions. State is per-session. A declarative `ALLOWED_TRANSITIONS` map enforces valid changes; invalid attempts raise `InvalidTransitionError`.

### MCP (Model Context Protocol) Tool Management

- `MCPManager` (`core/mcp/manager.py`) — manages stdio subprocess lifecycle for external tool servers; merges server `env` on top of `os.environ` at startup; auto-restarts on crash (up to 5 times); prefix-routes tools as `server_id__tool_name`
- `MCPRegistry` (`core/mcp/registry.py`) — persists server configs to `~/.deepseek_chat/mcp_servers.json`; syncs `command`, `args`, and `env` of builtin servers on every load (ensures PYTHONPATH and interpreter path stay correct after venv changes)
- Tool execution is integrated directly into the `BaseAgent` stream loop with a **30-second `asyncio.wait_for` timeout** per tool call

### Global Persistent State

All state lives in `~/.deepseek_chat/`:
| File | Purpose | Cleared on `/clear`? |
|------|---------|----------------------|
| `context.json` | Chat history + summary | Yes |
| `memory.json` | Working + long-term memory | Working only |
| `profile.json` | User profile & preferences | No |
| `invariants.json` | Hard constraints | No |
| `mcp_servers.json` | MCP server configs | No |
| `scheduler.db` | SQLite: scheduled tasks + history | No |
| `dialogue_task.json` | Dialogue task memory (goal, clarifications, constraints, topics) | Yes (in `rag_chat.py`) |
| `pending_changes.json` | Filesystem proposal blobs (shared between MCP subprocess and app) | No |
| `crm_data.json` | CRM users and tickets (read/write by `crm_server.py`) | No |

RAG index lives alongside other app state in `data/` (or `DEEPSEEK_DATA_DIR`):
| File | Purpose |
|------|---------|
| `rag_index.db` | SQLite: chunk text + embeddings (both strategies) |

Experiment artifacts live in `experiments/rag_compare/data/`:
| File | Purpose |
|------|---------|
| `comparison_report.json` | Strategy comparison results |
| `local_vs_cloud_report.json` | Day 28: local Ollama vs cloud LLM RAG comparison (raw data) |
| `day28_local_vs_cloud_report.md` | Day 28: human-readable analysis report |
| `day29_optimization_report.json` | Day 29: parameter+prompt optimization results (raw data) |
| `day29_optimization_report.md` | Day 29: human-readable optimization report |
| `day30_stability_report.md` | Day 30: stability test results and analysis (3 concurrency series, 100% success) |

Memory/profile/invariants are **reloaded from disk on every request** to pick up real-time edits.

Persistence file formats:

```json
// context.json
{"format_version": 1, "provider": "deepseek", "model": "deepseek-chat",
 "updated_at": "...", "summary": "...", "messages": [{"role": "user", "content": "..."}]}

// memory.json
{"working_memory": ["..."], "long_term_memory": ["..."]}

// invariants.json
{"invariants": ["Only Kotlin, no Java", "Clean Architecture + MVVM"]}
```

### Web Layer (`web/`)

- `app.py` — FastAPI app; lifespan starts MCP servers and scheduler runner; rate limiter (`slowapi`) + `APIKeyMiddleware` applied at startup; CORS middleware (localhost by default, `SERVICE_CORS_ORIGINS` env override); `/health` endpoint (no auth, returns `mcp_servers_active` + `data_dir_writable`); warns if `WEB_CONCURRENCY > 1`; checks `is_index_stale()` at startup; binds to `SERVICE_HOST`/`SERVICE_PORT`
- `middleware.py` — `APIKeyMiddleware`: checks `X-API-Key` header when `SERVICE_API_KEY` is set; exempts `/`, `/static/*`, `/health`; logs `401` rejections at `WARNING` level
- `routes.py` — all HTTP/SSE endpoints; includes `GET /config/provider` and `POST /config/provider` for runtime switching; `/stream` enforces `MAX_INPUT_CHARS` limit
- `streaming.py` — SSE generator with task marker parsing; `_collect_task_markers` and `_apply_task_markers` are pure functions (testable without HTTP context)
- `state.py` — singletons for config, client, sessions, task machines, MCP; `get_agent()` factory; `set_provider(provider)` for runtime provider switching; `get_session_async()` / `get_task_machine_async()` use `asyncio.Lock` + double-checked locking to prevent duplicate session creation under concurrent requests
- `cost_tracker.py` — per-session cost accumulator (`defaultdict(float)` keyed by `session_id`); no global state, no cross-session bleed
- Frontend: vanilla JS (`static/app.js`, ~48KB) + CSS; no build step needed

### Provider Switching (Day 26–27)

`PROVIDER=ollama` in `.env` starts the app **fully locally** — no cloud API key required. All three frontends (web, console, rag_chat) work without modification.

`set_provider(provider)` in `web/state.py` also switches the active LLM at runtime without restart:
- `"ollama"` — routes to local Ollama (`http://localhost:11434/v1/chat/completions`, model `qwen2.5:7b`, no API key, price=0)
- `"deepseek"` or `"groq"` — restores the startup config (read from env at boot)

UI toggle in the chat input bar (DeepSeek ↔ Ollama buttons) calls `POST /config/provider`. The toolbar badge and textarea placeholder update to reflect the active provider.

`client.py` skips `response_format` for Ollama (not universally supported). DeepSeek-specific fields (`frequency_penalty`, `presence_penalty`, `thinking`) are already omitted for non-deepseek providers.

### RAG — Document Indexing (`core/rag/`)

`deepseek_chat/core/rag/` is a self-contained domain package (no web/agent imports):
- `config.py` — `RagConfig` dataclass + `load_rag_config()` (env: `RAG_*`)
- `corpus.py` — `CORPUS_FILES` list (17 files: 6 external articles + 2 project md + 9 py)
- `chunkers.py` — `FixedSizeChunker` (tiktoken sliding window) + `StructureChunker` (markdown `##` / Python AST)
- `embedder.py` — `OllamaEmbeddingClient` calling `POST /api/embed` on local Ollama
- `store.py` — SQLite store with cosine similarity search
- `pipeline.py` — `run_pipeline(strategy)` orchestrator

Experiment code (can be deleted): `experiments/rag_compare/` — `compare.py` + `cli.py`.
Corpus documents: `docs/corpus/` (6 markdown files, ~150 pages, downloaded via `scripts/download_corpus.py`).
`RagHook` (`agents/hooks/rag_hook.py`) — `before_stream` hook, автоматически инжектирует релевантные чанки в system prompt перед каждым LLM-запросом. Контролируется через `RAG_ENABLED`, `RAG_TOP_K`, `RAG_SEARCH_STRATEGY`. Graceful degradation: если Ollama недоступна или индекс пустой — hook молча пропускается.

Pipeline внутри хука (Day 23–24):
1. (опционально) `QueryRewriter.rewrite()` — LLM-переформулировка запроса (`RAG_QUERY_REWRITE_ENABLED`)
2. Embed query → Ollama
3. Fetch `RAG_PRE_RERANK_TOP_K` кандидатов (pre-rerank pool)
4. `rerank_and_filter()` — порог отсечения + опциональный heuristic boost (`RAG_RERANKER_TYPE`, `RAG_RERANKER_THRESHOLD`)
5. `format_citation_block()` — нумерованные цитаты + инструкция по уровню уверенности (`RAG_CITATIONS_ENABLED`)
   - **confident** (max_score ≥ `RAG_WEAK_CONTEXT_THRESHOLD`): полные цитаты, обязательный список источников
   - **uncertain** (max_score ≥ `RAG_IDK_THRESHOLD`): цитаты + предупреждение об умеренной уверенности
   - **weak** (max_score < `RAG_IDK_THRESHOLD`): инструкция "не знаю", запрос уточнения
   - **empty** (нет чанков): инструкция "не знаю", запрет отвечать из общих знаний

Новые модули RAG:
- `core/rag/reranker.py` — `ThresholdFilter`, `HeuristicReranker`, `rerank_and_filter()`
- `core/rag/query_rewriter.py` — `QueryRewriter` (LLM rewrite + heuristic clean)

### Scheduler

`mcp_servers/scheduler/` implements autonomous background tasks:
- `scheduler_store.py` — SQLite persistence
- `scheduler_runner.py` — 30-second tick loop, runs from `app.py` lifespan
- `scheduler_server.py` — MCP tool provider (create/list/pause/resume/delete tasks)
- Tasks are executed by `BackgroundAgent` built via `core/agent_factory.py`
- Schedule formats: `once`, `every_Nm`, `every_Nh`, `daily_HH:MM`

## Configuration

Copy `.env.example` to `.env`.

**DeepSeek:**
```dotenv
PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_API_MODEL=deepseek-chat          # default
DEEPSEEK_API_MAX_TOKENS=4000              # default
DEEPSEEK_API_TIMEOUT_SECONDS=60          # default
DEEPSEEK_API_URL=https://api.deepseek.com/v1/chat/completions
DEEPSEEK_MODELS_URL=...                   # optional, enables /models endpoint
```

**Ollama (local, no API key):**
```dotenv
PROVIDER=ollama
OLLAMA_URL=http://localhost:11434   # default
OLLAMA_MODEL=qwen2.5:7b            # default; any model pulled via `ollama pull`
OLLAMA_MAX_TOKENS=4000             # default
OLLAMA_TIMEOUT_SECONDS=120         # default (local inference is slower)
OLLAMA_NUM_CTX=4096                # optional; sets context window via options.num_ctx
```

**Groq:**
```dotenv
PROVIDER=groq
GROQ_API_KEY=...
GROQ_API_MODEL=moonshotai/kimi-k2-instruct  # default
GROQ_API_MAX_TOKENS=4000                    # default
GROQ_API_TIMEOUT_SECONDS=60                # default
GROQ_API_URL=https://api.groq.com/openai/v1/chat/completions
GROQ_MODELS_URL=https://api.groq.com/openai/v1/models
GROQ_LLAMA3_1_8B_MODEL=llama-3.1-8b-instant      # for model_compare.py
GROQ_LLAMA3_1_70B_MODEL=llama-3.1-70b-versatile  # for model_compare.py
```

**Context persistence:**
```dotenv
DEEPSEEK_PERSIST_CONTEXT=true        # default
DEEPSEEK_CONTEXT_PATH=~/.deepseek_chat/context.json
DEEPSEEK_WEB_CONTEXT_PATH=...        # override context file path for web
DEEPSEEK_CONTEXT_MAX_MESSAGES=40     # sliding window size
```

**Day 30 — Private service:**
```dotenv
SERVICE_HOST=0.0.0.0       # bind address (default: 127.0.0.1)
SERVICE_PORT=8000           # bind port (default: 8000)
SERVICE_API_KEY=            # if set, X-API-Key header required on all non-exempt endpoints
RATE_LIMIT_PER_MINUTE=60   # max requests per IP per minute (default: 60)
MAX_INPUT_CHARS=0           # max /stream message length in chars (0 = unlimited)
```

**Context compression:**
```dotenv
DEEPSEEK_COMPRESSION_ENABLED=false  # default
DEEPSEEK_COMPRESSION_THRESHOLD=10   # messages before compression triggers
DEEPSEEK_COMPRESSION_KEEP=4         # messages to keep uncompressed
```

**RAG reranking / query rewrite (Day 23):**
```dotenv
RAG_PRE_RERANK_TOP_K=10          # candidates fetched before filtering (>= RAG_TOP_K)
RAG_RERANKER_TYPE=threshold      # "none" | "threshold" | "heuristic"
RAG_RERANKER_THRESHOLD=0.30      # min cosine similarity to keep a chunk
RAG_QUERY_REWRITE_ENABLED=false  # rewrite query via LLM before embedding
# Citations & anti-hallucination (Day 24)
RAG_CITATIONS_ENABLED=true       # inject numbered citation format + instructions
RAG_IDK_THRESHOLD=0.45           # max_score below this → "I don't know" response
RAG_WEAK_CONTEXT_THRESHOLD=0.55  # max_score below this → uncertain response with caveat
```

Optional LLM params (set in code via `OptionalRequestParams` in `core/config.py`, not env): `temperature`, `frequency_penalty`, `presence_penalty`, `response_format`, `stop`, `thinking`.

## Testing

Tests use `pytest` with no mocking of databases (scheduler uses real SQLite temp files). Web-layer tests require `DEEPSEEK_API_KEY` in environment. Pure domain tests (config, session, task_state, memory, profile) have no external dependencies.

| Test file | Covers |
|-----------|--------|
| `test_config.py` | env parsing, provider selection |
| `test_session.py` | history, trim, clone, persistence |
| `test_memory.py` | working/long-term memory, persistence |
| `test_profile.py` | fields, persistence |
| `test_invariants.py` | add/remove, prompt injection |
| `test_task_state.py` | FSM transitions, serialization |
| `test_cost_tracker.py` | `web/cost_tracker.py` |
| `test_hooks.py` | TaskState, Memory, Profile, Invariant hooks |
| `test_auto_title_hook.py` | trigger logic, LLM errors |
| `test_strategies.py` | history building, compression flags |
| `test_streaming_markers.py` | `_collect_task_markers`, `_apply_task_markers` |
| `test_mcp_registry.py` | CRUD, persistence |
| `test_scheduler_store.py` | SQLite scheduler store |
| `test_scheduler_utils.py` | `compute_next_run()` |
| `test_rag_reranker.py` | `ThresholdFilter`, `HeuristicReranker`, `rerank_and_filter` |
| `test_rag_query_rewriter.py` | `QueryRewriter.clean()`, `QueryRewriter.rewrite()` |
| `test_rag_citations.py` | `assess_confidence`, `format_citation_block`, config defaults |
| `test_dialogue_task.py` | `DialogueTask`: apply_marker, get_injection, persistence |
| `test_dialogue_task_hook.py` | `DialogueTaskHook`: before_stream injection, after_stream marker parsing |
| `test_git_server.py` | git MCP tools: branch, commits, changed files, diff, project tree |
| `test_dev_help_agent.py` | `DevHelpAgent`: hook composition, system prompt |
| `test_filesystem_server.py` | two-phase filesystem tools: read, propose, apply, discard |
| `test_code_review_agent.py` | `CodeReviewAgent`: hook composition, system prompt, prompt builder |
| `test_crm_server.py` | CRM MCP tools: get_ticket, get_user, list_open_tickets, search_tickets, update_ticket_status |
| `test_support_agent.py` | `SupportAgent`: hook composition, system prompt |
