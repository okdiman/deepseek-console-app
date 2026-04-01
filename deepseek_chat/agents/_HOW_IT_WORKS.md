# Agents — How It Works

This document describes the agent pipeline: how a user message travels from input to streamed LLM output, how hooks intercept and enrich every request, and what each concrete agent and hook does.

---

## Overview

Every agent is a `BaseAgent` subclass. Its only public method is `stream_reply(user_input)`, which orchestrates the full request lifecycle:

```
user_input
    │
    ▼
[ChatSession] ← add user message
    │
    ▼
[UnifiedStrategy] ← sliding window + optional compression
    │
    ▼
[before_stream hooks] ← modify system prompt (in order)
    │
    ▼
[intercept_stream hooks] ← short-circuit LLM? (first wins)
    │
    ├── yes → yield intercept response, skip LLM
    │
    └── no  → stream LLM
                │
                ├── text chunk → yield to caller
                └── tool_call  → execute via MCPManager → re-enter LLM loop
    │
    ▼
[after_stream hooks] ← background work (logging, auto-title, marker parsing)
```

---

## Package Structure

```
deepseek_chat/agents/
├── base_agent.py          — BaseAgent: pipeline orchestration
├── strategies.py          — UnifiedStrategy: context window management
├── general_agent.py       — GeneralAgent (default for web UI)
├── python_agent.py        — PythonAgent (Python/code-focused)
├── dev_help_agent.py      — DevHelpAgent (project documentation assistant)
├── support_agent.py       — SupportAgent (customer support with RAG + CRM)
├── code_review_agent.py   — CodeReviewAgent (automated PR review; used by scripts/review_pr.py)
├── background_agent.py    — BackgroundAgent (scheduler tasks, no hooks)
└── hooks/
    ├── base.py             — AgentHook ABC
    ├── __init__.py         — exports all hooks
    ├── memory_injection.py — MemoryInjectionHook
    ├── invariant_guard.py  — InvariantGuardHook
    ├── user_profile.py     — UserProfileHook
    ├── task_state.py       — TaskStateHook (FSM integration)
    ├── dialogue_task_hook.py — DialogueTaskHook (conversation goal tracking)
    ├── rag_hook.py         — RagHook (retrieval-augmented generation)
    └── auto_title.py       — AutoTitleHook
```

---

## BaseAgent

`base_agent.py` — the core pipeline. Subclasses only need to set `SYSTEM_PROMPT`.

### stream_reply lifecycle

**1. Session update**

`session.add_user(user_input)` — appends the user message to history before any hooks run.

**2. Context strategy**

`UnifiedStrategy.process_context()` — checks if compression is needed and runs it if so. Then `build_history_messages()` builds the final `[system, ...history]` list that will be sent to the LLM.

**3. before_stream hooks**

Each hook's `before_stream(agent, user_input, system_prompt, history)` is called in order. A hook returns a (possibly modified) `system_prompt` string. The final system prompt replaces `history[0]` before the LLM call. Hooks may also mutate `history` in-place (inserting late system messages).

**4. intercept_stream hooks**

Each hook's `intercept_stream(agent, user_input, history)` is called. If any hook returns a non-`None` string, that string is yielded directly to the caller and the LLM is **not called**. Only the first non-`None` intercept wins.

**5. LLM stream loop**

`client.stream_message(history)` streams text chunks. Two special JSON payloads are handled inline:
- `{"__type__": "tool_call_start"}` — yields a UI indicator
- `{"__type__": "tool_calls"}` — executes all tool calls via `MCPManager` (each call wrapped with a **30-second `asyncio.wait_for` timeout**), saves tool results to session, re-builds history, and re-enters the stream loop

All other chunks are yielded to the caller and collected in `response_parts`.

**6. after_stream hooks**

After the stream completes (in a `finally` block), each hook's `after_stream(agent, full_response)` is called. Used for background work that should not block the response stream.

### ask()

Non-streaming helper that collects all chunks from `stream_reply` and returns an `AgentResult(content, metrics)`.

---

## Context Strategy — UnifiedStrategy

`strategies.py` manages the conversation history sent to the LLM.

### Sliding window

`build_history_messages()` always includes the last `DEEPSEEK_CONTEXT_MAX_MESSAGES` messages intact. Older messages are either dropped or replaced by a compressed summary.

### Compression

Triggered when `DEEPSEEK_COMPRESSION_ENABLED=true` and `user_msg_count > DEEPSEEK_COMPRESSION_THRESHOLD`.

A single LLM call asks for a JSON response:
```json
{"summary": "...", "facts": ["fact1", "fact2"]}
```

- `summary` replaces the old messages in session; prepended to future history as a system message
- `facts` are added to **Working Memory** automatically (`MemoryStore.add_working_memory`)

After compression, `get_system_message_for_response()` yields a visible `[System: Контекст сжат...]` notice to the user before the LLM answers.

---

## Hook Interface — AgentHook

`hooks/base.py` defines the ABC with three async methods:

| Method | Returns | Purpose |
|--------|---------|---------|
| `before_stream(agent, user_input, system_prompt, history)` | `str` (modified system prompt) | Enrich system prompt or mutate history |
| `intercept_stream(agent, user_input, history)` | `str \| None` | Short-circuit LLM (return response directly) |
| `after_stream(agent, full_response)` | `None` | Background work after response |

Default implementations: `intercept_stream` returns `None`; `before_stream` returns `system_prompt` unchanged; `after_stream` is a no-op.

**`suppress_tools: bool`** — class-level attribute (default `False`). A hook can set this to `True` during `before_stream` to signal that it has found sufficient local context. `BaseAgent` checks this flag after all hooks run and omits MCP tools from the LLM call if any hook raised it. Must be reset to `False` at the start of each `before_stream` call.

---

## Hooks Reference

Seven concrete hooks are available. Each inherits `AgentHook` from `hooks/base.py` and implements `before_stream` and/or `after_stream`. See `hooks/_HOW_IT_WORKS.md` for full internals of each hook.

### MemoryInjectionHook

**Purpose:** Injects the Explicit Memory Store (working + long-term memory) into the conversation history.

**How:** Loads `MemoryStore` on every call (from disk), formats a memory block, and inserts it as a `system` message right before the last user message. Late placement ensures the LLM treats memory as the most recent context update rather than anchoring on stale history.

**Phase:** `before_stream` only.

---

### InvariantGuardHook

**Purpose:** Injects hard constraints (invariants) that the LLM must always respect.

**How:** Same insertion strategy as `MemoryInjectionHook` — loads `InvariantStore`, inserts a system message right before the last user message. Invariants are reloaded from disk on every request so real-time edits take effect immediately.

**Phase:** `before_stream` only.

---

### UserProfileHook

**Purpose:** Personalizes agent responses with name, role, style preferences, formatting rules, and strict constraints.

**How:** Loads `UserProfile` from disk. If non-empty, appends a `[USER PROFILE PARAMETERS]` block at the end of the system prompt (high priority position). If the profile is empty, returns the system prompt unchanged.

**Phase:** `before_stream` only.

---

### DialogueTaskHook

**Purpose:** Tracks structured conversation state across turns: goal, clarifications, constraints, explored topics, and unresolved questions.

**How:**
- `before_stream` — loads `DialogueTask` from disk and appends its `get_injection()` block (task state + strict marker rules) to the system prompt
- `after_stream` — parses markers embedded by the LLM in its response using regex `[TYPE: value]`, calls `apply_marker()` for each, saves if any markers were found

**Markers the agent embeds:**

| Marker | Trigger |
|--------|---------|
| `[GOAL: text]` | First response, based on what user asks (not what can be answered) |
| `[CLARIFIED: text]` | User states a preference or background detail |
| `[CONSTRAINT: text]` | User restricts approach, language, or tools |
| `[TOPIC: text]` | Substantive answer given; also auto-clears matching `[UNRESOLVED:]` |
| `[UNRESOLVED: text]` | Question could not be answered (IDK) |

**Phase:** `before_stream` + `after_stream`.

See `deepseek_chat/core/dialogue_task.py` for the `DialogueTask` data model.

---

### RagHook

**Purpose:** Retrieval-Augmented Generation — retrieves relevant document chunks from the local index and injects them (with citation instructions) into the system prompt before each LLM call. RAG has priority over MCP tools: when the local index returns confident results, MCP tools are not offered to the LLM at all.

**How:** Runs a 6-step pipeline in `before_stream`:
1. Enrich short queries (≤12 words) with the current DialogueTask goal
2. Optionally rewrite query via LLM (`RAG_QUERY_REWRITE_ENABLED`)
3. Embed query → Ollama (`nomic-embed-text`)
4. Fetch `RAG_PRE_RERANK_TOP_K` candidates from SQLite index
5. Rerank/filter to `RAG_TOP_K` chunks
6. Format citation block with confidence-level instructions; set `suppress_tools=True` if confidence is `CONFIDENT`

**Tool suppression:** After `before_stream` hooks run, `BaseAgent` checks whether any hook has `suppress_tools=True`. If so, MCP tools are not passed to the LLM for this request — the model is forced to answer from the injected context. This ensures the local index is always consulted first; external tools are only available when RAG found nothing useful.

| RAG confidence | MCP tools offered to LLM |
|----------------|--------------------------|
| `CONFIDENT` | No — suppress_tools=True |
| `UNCERTAIN` | Yes — context is partial, tools may help |
| `WEAK` | Yes — context too weak to rely on |
| `EMPTY` | Yes — nothing found locally |

Degrades gracefully: if Ollama is unreachable or the index is empty, `suppress_tools` stays `False` and tools are offered normally.

Exposes `self.last_chunks` for CLI display of retrieved sources.

**Phase:** `before_stream` only.

See `deepseek_chat/core/rag/HOW_IT_WORKS.md` for the full RAG pipeline documentation.

---

### TaskStateHook

**Purpose:** Integrates the `TaskStateMachine` (FSM) into the agent pipeline for structured task execution.

**How:**
- `before_stream` — injects current FSM state + phase into the system prompt; in `PLANNING` phase inserts a SYSTEM GATE message that prohibits execution until the plan is approved
- `after_stream` — parses transition markers from the LLM response and applies FSM transitions in text order

**Markers:**

| Marker | FSM effect |
|--------|-----------|
| `[PLAN_READY]` | planning → ready for approval |
| `[STEP_DONE]` | advance current step counter |
| `[READY_FOR_VALIDATION]` | execution → validation |
| `[REVERT_TO_STEP: N]` | revert to step N |
| `[RESUME_TASK]` | paused → execution |

If `agent._skip_after_stream_markers` is set (by `web/streaming.py` which processes markers live during SSE), the hook skips double-processing.

**Phase:** `before_stream` + `after_stream`.

---

### AutoTitleHook

**Purpose:** Auto-generates a short session title after the first 1–2 user turns.

**How:** In `after_stream`, checks if the session already has a summary (title). If not, and if the user turn count is 1 or 2 (and the message count is even), fires a short LLM call asking for a 3–5 word title. Sets `session.summary` to the result — this becomes the chat title in the web UI.

**Phase:** `after_stream` only.

---

## Concrete Agents

| Agent | Hooks | Use case |
|-------|-------|---------|
| `GeneralAgent` | MemoryInjection, InvariantGuard, UserProfile, TaskState, AutoTitle | Default web UI agent |
| `PythonAgent` | Rag, MemoryInjection, DialogueTask, UserProfile, InvariantGuard, AutoTitle | Python / code-focused conversations with RAG |
| `DevHelpAgent` | Rag, AutoTitle | Project documentation assistant; `/help <question>` in console and web |
| `SupportAgent` | Rag, AutoTitle | Customer support assistant; uses RAG (FAQ) + CRM MCP tools (tickets, users) |
| `CodeReviewAgent` | Rag | Automated PR code review; invoked by `scripts/review_pr.py` and GitHub Actions |
| `BackgroundAgent` | *(none)* | Scheduler tasks; minimal, no UI hooks |
| `RagChatAgent` (demo) | Rag, MemoryInjection, DialogueTask, UserProfile, InvariantGuard | RAG mini-chat experiment |

### SupportAgent

`support_agent.py` — customer support assistant that answers product questions using the RAG knowledge base and fetches per-user / per-ticket context from the CRM MCP server.

**Hook stack:** `[RagHook(allow_tools=True), AutoTitleHook]` — identical structure to `DevHelpAgent`.

**Capabilities:**
- Answers FAQ and product questions via RAG (`docs/corpus/support_faq.md`)
- Fetches ticket details via `crm__get_ticket(ticket_id)` MCP tool
- Fetches user profile/plan via `crm__get_user(user_id)` MCP tool
- Searches related tickets via `crm__search_tickets(query)`
- Updates ticket status via `crm__update_ticket_status(ticket_id, status)`

**System prompt priorities (enforced):**
1. CRM tools first when ticket ID or user is mentioned
2. RAG context for FAQ/product questions
3. Escalation instruction when issue cannot be resolved locally

**Data sources:**
- RAG: `docs/corpus/support_faq.md` (FAQs indexed into `data/rag_index.db`)
- CRM: `data/crm_data.json` (users + tickets, editable JSON)

**Invocation:** Select `support` from the agent dropdown in the web UI.

---

### CodeReviewAgent

`code_review_agent.py` — stateless agent for automated PR code review.

**Hook stack:** `[RagHook]` — injects project conventions from the local RAG index; degrades gracefully when Ollama is unavailable (e.g. in CI).

**Input:** a git diff (passed as the user message), optionally with a list of changed files.

**Output:** structured markdown review with four mandatory sections:
- `## 🐛 Potential Bugs` — concrete bugs, edge cases
- `## 🏗️ Architectural Issues` — design-level problems
- `## 💡 Recommendations` — improvements (naming, tests, performance)
- `## ✅ Summary` — risk level (Low / Medium / High) + verdict (Approve / Request Changes / Needs Discussion)

**No MCP tools** — all context comes from the diff itself plus RAG injection. One-shot `agent.ask()` call; no conversation history needed.

**Invocation:** `python scripts/review_pr.py --diff diff.patch`; called automatically by `.github/workflows/pr_review.yml` on every PR open/sync event.

---

### DevHelpAgent

`dev_help_agent.py` — developer assistant that can both answer questions about the project and make changes to it.

**Hook stack:** `[RagHook, AutoTitleHook]` — RAG context retrieval and auto title generation; no memory/profile/task-state hooks (keeps answers doc-focused).

**Capabilities:**
- Answers questions using RAG (project docs + source files)
- Reads git state (branch, commits, diffs) via `git_project` MCP tools
- Reads project files via `filesystem` MCP tools (`read_file`, `list_directory`, `search_in_files`)
- Proposes and applies code changes via the two-phase filesystem protocol

**Two-phase write protocol (enforced by system prompt):**
1. `read_file` before any edit
2. `propose_edit` / `propose_write` → shows diff, returns `proposal_id`
3. Wait for user confirmation ("yes", "apply", "go ahead")
4. `apply_change(proposal_id)` → writes to disk
5. `run_tests` → verify nothing broke

**Invocation:**
- Console: `/help <question>` — ephemeral session, does not pollute main chat history
- Web: select `dev_help` from the agent dropdown

---

## Hook Execution Order

Order matters — hooks run sequentially. Within `before_stream`, each hook receives the system prompt already modified by the previous hook.

Typical order for `PythonAgent`:
```
1. RagHook            ← retrieves context, appends citation block to system prompt
2. MemoryInjectionHook ← inserts memory as late system message in history
3. DialogueTaskHook   ← appends task memory block to system prompt
4. UserProfileHook    ← appends user profile block to system prompt
5. InvariantGuardHook ← inserts invariants as late system message in history
```

For `after_stream`, hooks run in the same order. `DialogueTaskHook.after_stream` parses markers; `AutoTitleHook.after_stream` generates title.

---

## Adding a New Hook

1. Create `hooks/my_hook.py` inheriting from `AgentHook`
2. Implement `before_stream` and/or `after_stream`
3. Export from `hooks/__init__.py`
4. Add to the hooks list in the relevant agent's constructor or `web/state.py → get_agent()`
