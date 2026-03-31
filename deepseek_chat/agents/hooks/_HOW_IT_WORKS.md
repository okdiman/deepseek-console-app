# Hooks — How It Works

This document describes the hook system in detail: the `AgentHook` interface, all concrete hooks, their lifecycle, and how they interact with `BaseAgent`.

---

## Overview

Hooks are middleware injected into the `BaseAgent` pipeline. Each hook can observe and modify the request at three points: before the LLM call, as an interceptor that can skip the LLM entirely, and after the response is complete.

```
user_input
    │
    ▼
[before_stream hooks]   ← modify system prompt or inject history messages (in order)
    │
    ▼
[intercept_stream hooks] ← first non-None return skips LLM entirely
    │
    ├── intercepted → yield string directly, done
    │
    └── not intercepted → stream LLM
                              │
                              ▼
                    [after_stream hooks]  ← background work (in order)
```

Hooks are injected at construction time via `BaseAgent.__init__(hooks=[...])`. The order of the list determines execution order — hooks run sequentially, each `before_stream` receives the system prompt already modified by the previous hook.

---

## Package Structure

```
deepseek_chat/agents/hooks/
├── base.py               — AgentHook ABC
├── __init__.py           — exports all hooks
├── memory_injection.py   — MemoryInjectionHook
├── invariant_guard.py    — InvariantGuardHook
├── user_profile.py       — UserProfileHook
├── task_state.py         — TaskStateHook
├── dialogue_task_hook.py — DialogueTaskHook
├── rag_hook.py           — RagHook
└── auto_title.py         — AutoTitleHook
```

---

## AgentHook — Base Interface

`base.py` defines the ABC all hooks must inherit from.

### Methods

```python
async def before_stream(agent, user_input, system_prompt, history) -> str
```
Called before the LLM stream. Receives the current `system_prompt` string (already modified by preceding hooks) and the full `history` list. Returns the (possibly modified) system prompt. May also mutate `history` in-place to inject late system messages.

```python
async def intercept_stream(agent, user_input, history) -> Optional[str]
```
Called after all `before_stream` hooks. If returns a non-`None` string, that string is yielded directly to the caller and the LLM is **not called**. Only the first hook to return a non-`None` value wins. Default implementation returns `None`.

```python
async def after_stream(agent, full_response) -> None
```
Called in a `finally` block after the full response has been streamed and saved to the session. Used for background tasks that must not block the response stream.

### suppress_tools

```python
suppress_tools: bool = False
```

Class-level flag. If a hook sets `self.suppress_tools = True` during `before_stream`, `BaseAgent` will not pass MCP tools to the LLM for that request. The flag must be reset to `False` at the start of each `before_stream` call (so each request is evaluated independently). `RagHook` uses this to give the local index priority over external tools when retrieval confidence is high.

---

## Hooks Reference

The application ships seven concrete hooks. Each inherits `AgentHook` and is registered in the agent's hook list at construction time. The hooks and their primary phases:

| Hook | before_stream | intercept_stream | after_stream |
|------|:---:|:---:|:---:|
| `MemoryInjectionHook` | ✓ | — | — |
| `InvariantGuardHook` | ✓ | — | — |
| `UserProfileHook` | ✓ | — | — |
| `DialogueTaskHook` | ✓ | — | ✓ |
| `TaskStateHook` | ✓ | — | ✓ |
| `RagHook` | ✓ | — | — |
| `AutoTitleHook` | — | — | ✓ |

### MemoryInjectionHook

**File:** `memory_injection.py`

**Purpose:** Injects working and long-term memory facts into the conversation so the LLM has access to persistent user context.

**How:** Loads `MemoryStore` from disk on every call, calls `get_system_prompt_injection()` to format a memory block, and inserts it as a `{"role": "system"}` message right before the last user message in `history`. Late placement (just before the user message) ensures the LLM treats memory as fresh context rather than anchoring on stale history.

**Phases:** `before_stream` only. `after_stream` is a no-op.

**Side effects:** None — memory is read-only here. Writing to memory happens via separate commands, not this hook.

---

### InvariantGuardHook

**File:** `invariant_guard.py`

**Purpose:** Injects hard constraints (invariants) the LLM must always respect — e.g. "Only Kotlin, no Java", "Clean Architecture + MVVM".

**How:** Same pattern as `MemoryInjectionHook` — loads `InvariantStore`, inserts a system message right before the last user message. Invariants are reloaded from disk on every request so real-time edits take effect immediately without restarting the server.

**Phases:** `before_stream` only. `after_stream` is a no-op.

---

### UserProfileHook

**File:** `user_profile.py`

**Purpose:** Personalizes agent responses with the user's name, role, style preferences, formatting rules, and strict constraints.

**How:** Loads `UserProfile` from disk. If the profile is non-empty, appends a `[USER PROFILE PARAMETERS]` block at the **end** of the system prompt. End-placement means it's a high-priority override — the LLM sees it last and weights it most. Returns the system prompt unchanged if the profile is empty.

**Profile fields:** `name`, `role`, `style_preferences`, `formatting_rules`, `constraints`.

**Phases:** `before_stream` only. `after_stream` is a no-op.

---

### DialogueTaskHook

**File:** `dialogue_task_hook.py`

**Purpose:** Tracks structured conversation state across turns so the agent can maintain coherent multi-turn dialogues: current goal, clarifications, constraints, explored topics, and unresolved questions.

**How:**

- `before_stream` — loads `DialogueTask` from disk, appends its `get_injection()` block to the system prompt. This block tells the LLM the current conversation goal and rules for embedding markers in its response.
- `after_stream` — scans the full response for markers using regex, calls `apply_marker()` for each match, saves to disk if any were found.

**Markers parsed from agent response:**

| Marker | Effect |
|--------|--------|
| `[GOAL: text]` | Sets / updates the conversation goal |
| `[CLARIFIED: text]` | Records a user clarification |
| `[CONSTRAINT: text]` | Records a user-imposed rule or restriction |
| `[TOPIC: text]` | Marks a topic as substantively answered; also auto-clears matching `[UNRESOLVED:]` |
| `[UNRESOLVED: text]` | Records a question that couldn't be answered |

**Phases:** `before_stream` + `after_stream`.

---

### TaskStateHook

**File:** `task_state.py`

**Purpose:** Integrates the `TaskStateMachine` FSM into the agent pipeline for structured multi-step task execution (plan → execute → validate).

**How:**

- `before_stream` — reads current FSM state via `task_machine.get_prompt_injection()` and appends it to the system prompt. If the phase is `PLANNING` and a plan exists, inserts a SYSTEM GATE message into `history` right before the last user message, prohibiting the LLM from executing any steps until the plan is approved.
- `after_stream` — scans the response for FSM transition markers using regex and applies them in text order. If `agent._skip_after_stream_markers` is set (meaning `web/streaming.py` already processed them live during SSE), skips double-processing.

**Markers parsed from agent response:**

| Marker | FSM transition |
|--------|----------------|
| `[PLAN_READY]` | planning → ready for approval |
| `[STEP_DONE]` | advance current step counter |
| `[READY_FOR_VALIDATION]` | execution → validation |
| `[REVERT_TO_STEP: N]` | revert to step N |
| `[RESUME_TASK]` | paused → execution |

**Phases:** `before_stream` + `after_stream`. `intercept_stream` always returns `None`.

---

### RagHook

**File:** `rag_hook.py`

**Purpose:** Retrieval-Augmented Generation — searches the local document index and injects relevant chunks into the system prompt before each LLM call. Gives RAG priority over MCP tools when retrieval confidence is high.

**How (before_stream pipeline):**

1. Reset `self.suppress_tools = False`
2. Check readiness via `await _check_ready()` (Ollama reachable + index non-empty); skip silently if not ready. Blocking calls (`health_check()`, `embed()`) run in a thread pool via `run_in_executor` to avoid blocking the event loop.
3. Enrich short queries (≤12 words) with the current `DialogueTask` goal
4. Optionally rewrite query via LLM (`RAG_QUERY_REWRITE_ENABLED`)
5. Embed query via Ollama (`await loop.run_in_executor(None, embedder.embed, [query])`)
6. Fetch `RAG_PRE_RERANK_TOP_K` candidates from SQLite index
7. Rerank/filter to `RAG_TOP_K` chunks
8. Assess confidence (`empty` / `weak` / `uncertain` / `confident`)
9. Format citation block and append to system prompt
10. If confidence is `CONFIDENT` → set `self.suppress_tools = True`

**Tool suppression:**

| Confidence | MCP tools offered to LLM |
|------------|--------------------------|
| `CONFIDENT` (score ≥ 0.55) | No — local context is sufficient |
| `UNCERTAIN` (score ≥ 0.45) | Yes — partial context, tools may help |
| `WEAK` / `EMPTY` | Yes — nothing reliable found locally |

**Exposes:** `self.last_chunks` — list of retrieved chunks, readable by CLI for display.

**Graceful degradation:** If Ollama is down or the index is empty, returns system prompt unchanged and `suppress_tools` stays `False`.

**Phases:** `before_stream` only. `after_stream` is a no-op.

See `deepseek_chat/core/rag/_HOW_IT_WORKS.md` for the full RAG pipeline internals.

---

### AutoTitleHook

**File:** `auto_title.py`

**Purpose:** Auto-generates a short session title (3–5 words) after the first 1–2 user turns so the web UI can display a meaningful conversation name.

**How (`after_stream`):**

1. If `session.summary` is already set, do nothing.
2. Count user turns in session history (ignoring tool call messages).
3. If `len(messages) % 2 == 0` and `user_turns in (1, 2)`, fire a short LLM call with up to 4 plain text messages and a title-generation prompt.
4. Strip quotes and punctuation from the result, set `session.summary`.

The even-message-count guard prevents the hook from firing on incomplete exchanges.

**Error handling:** LLM errors during title generation are logged at `WARNING` level via `logger.warning(...)` and do not propagate — a failed title generation is non-fatal.

**Phases:** `after_stream` only. `before_stream` is a no-op.

---

## Hook Execution Order

Hooks run in the order they are passed to `BaseAgent`. Each `before_stream` call receives the system prompt already modified by all preceding hooks.

**GeneralAgent** (web UI default):
```
1. MemoryInjectionHook  ← injects memory as late system message
2. InvariantGuardHook   ← injects invariants as late system message
3. UserProfileHook      ← appends profile block to system prompt
4. TaskStateHook        ← appends FSM state; inserts SYSTEM GATE if planning
5. AutoTitleHook        ← no-op in before_stream; fires title generation after
```

**PythonAgent / RagChatAgent** (RAG-enabled):
```
1. RagHook              ← retrieves context, appends citation block, may suppress tools
2. MemoryInjectionHook  ← injects memory as late system message
3. DialogueTaskHook     ← appends dialogue task block to system prompt
4. UserProfileHook      ← appends profile block to system prompt
5. InvariantGuardHook   ← injects invariants as late system message
6. AutoTitleHook        ← no-op in before_stream; fires title generation after
```

**DevHelpAgent** (documentation assistant):
```
1. RagHook              ← retrieves context, appends citation block, may suppress tools
2. AutoTitleHook        ← no-op in before_stream; fires title generation after
```

`RagHook` runs first so all downstream hooks see the system prompt already enriched with retrieved context.

---

## Adding a New Hook

1. Create `hooks/my_hook.py` inheriting from `AgentHook`
2. Implement at minimum `before_stream` and `after_stream` (both are `@abstractmethod`)
3. If you need to suppress MCP tools conditionally, set `self.suppress_tools = True` in `before_stream` and reset it to `False` at the start of each call
4. Export from `hooks/__init__.py`
5. Add to the hooks list in the agent constructor or in `web/state.py → get_agent()`
