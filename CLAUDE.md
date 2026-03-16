# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Before pushing

After implementing any feature or fix, check whether `CLAUDE.md` needs to be updated (new env vars, architectural changes, new patterns, changed commands). Update it before pushing.

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

# RAG — download corpus documents (run once)
python3 scripts/download_corpus.py

# RAG — index + search + compare (requires Ollama running)
python3 experiments/rag_compare/cli.py index
python3 experiments/rag_compare/cli.py search --query "how does attention work?"
python3 experiments/rag_compare/cli.py compare
python3 experiments/rag_compare/cli.py stats
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

### Agent Pipeline

`BaseAgent` (`agents/base_agent.py`) orchestrates each reply:
1. **before_stream hooks** — modify the system prompt (memory injection, profile, invariants, task state)
2. **intercept_stream hooks** — optionally short-circuit LLM entirely
3. **Stream LLM response** — handles tool calls inline; if tools are called, re-enters the stream loop
4. **after_stream hooks** — background work (auto-title generation, etc.)

Concrete agents (`GeneralAgent`, `AndroidAgent`, `BackgroundAgent`) differ only in their system prompts.

### Hook System

All hooks inherit `AgentHook` (`agents/hooks/base.py`) with three async methods:
- `before_stream` → returns modified system prompt string
- `intercept_stream` → returns string to skip LLM, or `None` to proceed
- `after_stream` → returns nothing, runs post-response logic

Active hooks are assembled by `web/state.py → get_agent()` and injected via the constructor.

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

- `MCPManager` (`core/mcp_manager.py`) — manages stdio subprocess lifecycle for external tool servers, auto-restarts on crash (up to 5 times), prefix-routes tools as `server_id__tool_name`
- `MCPRegistry` (`core/mcp_registry.py`) — persists server configs to `~/.deepseek_chat/mcp_servers.json`
- Tool execution is integrated directly into the `BaseAgent` stream loop

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

All RAG experiment state lives in `experiments/rag_compare/data/`:
| File | Purpose |
|------|---------|
| `doc_index.db` | SQLite: chunk text + embeddings (both strategies) |
| `comparison_report.json` | Strategy comparison results |

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

- `app.py` — FastAPI app; lifespan starts MCP servers and scheduler runner
- `routes.py` — all HTTP/SSE endpoints
- `streaming.py` — SSE generator with task marker parsing; `_collect_task_markers` and `_apply_task_markers` are pure functions (testable without HTTP context)
- `state.py` — singletons for config, client, sessions, task machines, MCP; `get_agent()` factory
- Frontend: vanilla JS (`static/app.js`, ~48KB) + CSS; no build step needed

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

**Context compression:**
```dotenv
DEEPSEEK_COMPRESSION_ENABLED=false  # default
DEEPSEEK_COMPRESSION_THRESHOLD=10   # messages before compression triggers
DEEPSEEK_COMPRESSION_KEEP=4         # messages to keep uncompressed
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
