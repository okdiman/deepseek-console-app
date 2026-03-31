# Core — How It Works

The `core/` package is the foundation of the application. It contains the LLM client, session management, configuration, task FSM, and a set of sub-packages for more complex domains. Nothing in `core/` imports from `agents/` or `web/` — it sits at the bottom of the dependency chain.

---

## Package Structure

```
deepseek_chat/core/
├── config.py        — ClientConfig + load_config()
├── client.py        — DeepSeekClient: streaming HTTP client
├── session.py       — ChatSession: in-memory conversation history
├── task_state.py    — TaskStateMachine: FSM for structured task execution
├── change_store.py  — Shared JSON store for filesystem proposal blobs (file-locked)
├── agent_factory.py — build_background_agent(), build_client(), build_manager()
├── paths.py         — PROJECT_ROOT and DATA_DIR constants
├── stream_printer.py — StreamPrinter: console streaming with stall indicator
│
├── memory/          — MemoryStore, UserProfile, InvariantStore, DialogueTask
├── mcp/             — MCPManager, MCPRegistry, MCPServerConfig
├── rag/             — RAG pipeline (chunking, embedding, retrieval, citations)
└── comparing/       — Multi-model comparison utilities
```

---

## config.py — ClientConfig

`load_config()` reads the `.env` file and returns a frozen `ClientConfig`.

Supports three providers selected via `PROVIDER=deepseek|groq|ollama` at startup:

| Setting | DeepSeek env var | Groq env var | Ollama env var | Default |
|---------|-----------------|--------------|----------------|---------|
| API key | `DEEPSEEK_API_KEY` | `GROQ_API_KEY` | *(none required)* | — |
| Model | `DEEPSEEK_API_MODEL` | `GROQ_API_MODEL` | `OLLAMA_MODEL` | deepseek-chat / kimi-k2 / qwen2.5:7b |
| Max tokens | `DEEPSEEK_API_MAX_TOKENS` | `GROQ_API_MAX_TOKENS` | `OLLAMA_MAX_TOKENS` | 4000 |
| Timeout | `DEEPSEEK_API_TIMEOUT_SECONDS` | `GROQ_API_TIMEOUT_SECONDS` | `OLLAMA_TIMEOUT_SECONDS` | 60s / 60s / 120s |
| URL | `DEEPSEEK_API_URL` | `GROQ_API_URL` | `OLLAMA_URL` | platform URLs / `http://localhost:11434` |

Setting `PROVIDER=ollama` requires **no API key** and routes all LLM calls to a local Ollama instance. This enables running the full application without any cloud services.

**Runtime provider switching:** `web/state.py` exposes `set_provider(provider, session_id)` which switches the LLM provider per session without restart. Supported values: `"ollama"` (routes to local Ollama, no API key) or the startup provider (`"deepseek"` / `"groq"`). Each session has its own `ClientConfig` and `DeepSeekClient` stored in `_session_configs` / `_session_clients` dicts. New sessions inherit the config of the `"default"` session at creation time. The API endpoint is `POST /config/provider?session_id=...`.

Additional settings (provider-agnostic):

| Env var | Default | Purpose |
|---------|---------|---------|
| `OLLAMA_NUM_CTX` | *(unset)* | Ollama context window size (e.g. 4096); passed as `options.num_ctx`; when unset, Ollama uses the model default |
| `DEEPSEEK_PERSIST_CONTEXT` | `true` | Save/load conversation history to disk |
| `DEEPSEEK_CONTEXT_PATH` | `data/context.json` | Path for persisted session |
| `DEEPSEEK_CONTEXT_MAX_MESSAGES` | `40` | Sliding window size |
| `DEEPSEEK_COMPRESSION_ENABLED` | `false` | Enable LLM-based history compression |
| `DEEPSEEK_COMPRESSION_THRESHOLD` | `10` | User turns before compression triggers |
| `DEEPSEEK_COMPRESSION_KEEP` | `4` | Recent messages kept after compression |

`OptionalRequestParams` holds LLM sampling settings (`temperature`, `frequency_penalty`, `presence_penalty`, `response_format`, `stop`, `thinking`) — set in code, not via env vars.

**Rule:** Config overrides always use `dataclasses.replace(_config, ...)`, never manual reconstruction.

---

## client.py — DeepSeekClient

Async HTTP client wrapping the OpenAI-compatible Chat Completions API (SSE streaming).

### stream_message()

Sends a POST request with `"stream": true` and yields response chunks as strings. Two special JSON payloads are yielded instead of text when tool calls are detected:

```python
# Tool call starting (UI feedback, yields immediately when tool name is known)
'{"__type__": "tool_call_start", "name": "scheduler__create_task"}'

# All accumulated tool calls for this turn (yielded after stream closes)
'{"__type__": "tool_calls", "calls": [...]}'
```

Tool call arguments are accumulated across chunks (streamed by the API) before being yielded as a complete payload.

### Provider-specific payload handling

- `deepseek` — adds `frequency_penalty`, `presence_penalty`, `thinking` to the payload
- `ollama` — removes `response_format` (not universally supported across Ollama model versions); if `ClientConfig.ollama_num_ctx` is set, adds `"options": {"num_ctx": N}` to the payload (Ollama-specific context window override)
- `groq` — no extra fields; standard OpenAI-compatible payload

### Error handling

- HTTP non-200 → raises `RuntimeError` with status and body
- Context length exceeded → detected by keywords in the body, raises `RuntimeError` with a descriptive message
- Timeout → controlled by `sock_read` timeout on the aiohttp session

### StreamMetrics

After every call, `last_metrics()` returns a `StreamMetrics` with duration, token counts, and cost in USD. Cost is calculated from `price_per_1k_prompt_usd` and `price_per_1k_completion_usd` in the config.

---

## session.py — ChatSession

In-memory conversation history with persistence.

### Message types stored

| Role | Content | When added |
|------|---------|------------|
| `user` | string | `add_user()` |
| `assistant` | string | `add_assistant()` |
| `assistant` | + `tool_calls` list | `add_tool_calls()` |
| `tool` | result string | `add_tool_result()` |

### Sliding window trim

After every `add_*` call, `_trim()` enforces `max_messages`. If the oldest messages are orphaned tool-related messages (a `tool` or `tool_calls` assistant message without its pair), they are also dropped to keep history structurally valid.

### Persistence format

`save(path, provider, model)` writes atomically (via `.tmp` + `os.replace`):

```json
{
  "format_version": 1,
  "provider": "deepseek",
  "model": "deepseek-chat",
  "updated_at": "2026-03-20T10:00:00+00:00",
  "summary": "...",
  "messages": [{"role": "user", "content": "..."}, ...]
}
```

`load(path)` validates each message on read — malformed entries are silently dropped.

### Compression

`apply_compression(new_summary, keep_count)` replaces the summary string and trims history to the last `keep_count` messages. Called by `UnifiedStrategy` after an LLM summarization call.

---

## task_state.py — TaskStateMachine

Finite state automaton for structured multi-step task execution. State is per-session (not global).

### Phases

```
idle → planning → execution → validation → done
         ↑                                   ↓
         └────────────── reset() ────────────┘
              ↗ pause() ↘  ↗ resume() ↘
           active       paused       active
```

| Phase | Who controls | What happens |
|-------|-------------|--------------|
| `idle` | — | No active task |
| `planning` | Agent proposes steps; user approves | Plan is assembled; execution blocked until approval |
| `execution` | Agent | Steps executed one by one; `[STEP_DONE]` advances counter |
| `validation` | Agent summarizes; user confirms | Final review before marking done |
| `done` | — | Task complete; reset to idle |
| `paused` | User | Suspended; `resume()` restores previous phase |

### Transition enforcement

`ALLOWED_TRANSITIONS` is a declarative map. Any attempt to skip phases raises `InvalidTransitionError`. The hook `TaskStateHook` calls FSM methods based on markers the agent embeds in responses.

### Markers the agent emits

| Marker | FSM effect |
|--------|-----------|
| `[PLAN_READY]` | Signals plan is complete (UI shows Approve button) |
| `[STEP_DONE]` | `step_done()` — advances current step |
| `[READY_FOR_VALIDATION]` | `advance_to_validation()` |
| `[REVERT_TO_STEP: N]` | `revert_to_step(N-1)` |
| `[RESUME_TASK]` | `resume()` from paused |

### Prompt injection

`get_prompt_injection()` returns a `[ACTIVE TASK STATE]` block injected into the system prompt by `TaskStateHook`. Contains phase, plan progress, and strict behavioral rules (e.g. "do NOT start execution while in PLANNING").

### Serialization

`to_dict()` includes `"format_version": 1` alongside phase, step counters, and plan. This version field enables future schema migrations without breaking existing saved states.

### Persistence

`save(path)` / `load(path)` — atomic JSON write. State is stored per-session in the web layer via `web/state.py`.

---

## agent_factory.py

Standalone factory for building agents **without importing the web layer**. Used by the scheduler runner and tests.

| Function | Returns | Purpose |
|----------|---------|---------|
| `build_background_agent()` | `(BackgroundAgent, MCPManager)` | Agent + manager for scheduler tasks |
| `build_client()` | `DeepSeekClient` | Standalone client from current config |
| `build_manager()` | `MCPManager` | Standalone MCP manager |

Callers must call `await manager.start_all()` before using the agent and `await manager.stop_all()` on shutdown.

---

## paths.py

Two public constants:

```python
PROJECT_ROOT = Path(__file__).parent.parent.parent  # absolute path to repo root
DATA_DIR     = Path(os.getenv("DEEPSEEK_DATA_DIR", str(PROJECT_ROOT / "data")))
```

`PROJECT_ROOT` is anchored to the source file location (not `os.getcwd()`), so it remains correct regardless of the working directory — including when imported by MCP subprocesses. All persistence paths in `core/memory/` modules default to `DATA_DIR / "*.json"`. Override `DATA_DIR` via `DEEPSEEK_DATA_DIR` env var for testing.

---

## stream_printer.py — StreamPrinter

Console streaming helper used by the CLI app. Prints chunks to stdout as they arrive, with a stall indicator (`...`) if no tokens come for `stall_seconds` (default 3).

Runs a background `asyncio.Task` that wakes every second and checks if the last token arrived too long ago.

---

## Dependency rule

```
web/ → agents/ → core/ → (nothing above)
```

`core/` never imports from `agents/` or `web/`. `agent_factory.py` exists specifically to bridge core and agents without creating a circular dependency with the web layer.

---

## Sub-packages

| Package | Contents | Docs |
|---------|----------|------|
| `memory/` | MemoryStore, UserProfile, InvariantStore, DialogueTask | `memory/_HOW_IT_WORKS.md` |
| `mcp/` | MCPManager, MCPRegistry, MCPServerConfig | `mcp/_HOW_IT_WORKS.md` |
| `rag/` | Full RAG pipeline | `rag/_HOW_IT_WORKS.md` |
| `comparing/` | Multi-model comparison scripts | — |
