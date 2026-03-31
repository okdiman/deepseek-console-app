# Memory — How It Works

This package contains all persistent context stores: data that is saved to disk between sessions and injected into every LLM request by the corresponding hook.

---

## Package Structure

```
deepseek_chat/core/memory/
├── store.py      — MemoryStore: working + long-term memory facts
├── profile.py    — UserProfile: name, role, style, formatting rules
├── invariants.py — InvariantStore: hard constraints the LLM must always follow
├── dialogue.py   — DialogueTask: conversation goal, clarifications, topics tracking
└── __init__.py   — re-exports all four classes
```

All four modules follow the same pattern:
- **Dataclass** holding the state
- **`save()` / `load()`** — JSON persistence to `~/.deepseek_chat/`
- **`get_*_injection()`** — formatted block appended to the system prompt by a hook

---

## MemoryStore (`store.py`)

Two-tier memory:

| Tier | Purpose | Cleared on `/clear`? |
|------|---------|----------------------|
| `working_memory` | Short-term facts extracted during context compression | Yes |
| `long_term_memory` | Permanent facts added by the user | No |

**Persistence:** `~/.deepseek_chat/memory.json`

**Injection:** Both lists are formatted into a system prompt block and injected by `MemoryInjectionHook` as a late system message, right before the user's latest message. This placement ensures the LLM treats memory as the most recent context update.

**Auto-population:** `UnifiedStrategy` extracts facts from compressed conversation history and adds them to `working_memory` automatically.

---

## UserProfile (`profile.py`)

Stores personal context about the user:

| Field | Example |
|-------|---------|
| `name` | "Dmitriy" |
| `role` | "Senior Android Developer" |
| `style_preferences` | "Concise answers, no filler words" |
| `formatting_rules` | "Use code blocks for all code snippets" |
| `constraints` | "Only Kotlin, no Java" |

**Persistence:** `~/.deepseek_chat/profile.json`

**Injection:** `UserProfileHook` appends a `[USER PROFILE PARAMETERS]` block to the end of the system prompt. Appended last = highest LLM priority. If the profile is empty, the hook is a no-op.

**Not cleared on `/clear`** — profile is permanent user configuration.

---

## InvariantStore (`invariants.py`)

Hard constraints the LLM must always respect regardless of what the user asks:

```
"Only Kotlin, no Java"
"Always use Clean Architecture"
"Never suggest deprecated APIs"
```

**Persistence:** `~/.deepseek_chat/invariants.json`

**Injection:** `InvariantGuardHook` inserts a system message right before the user's latest message in history. Late placement (after conversation history) gives invariants the highest effective priority.

**Not cleared on `/clear`** — invariants are permanent guardrails.

---

## DialogueTask (`dialogue.py`)

Tracks structured conversation state within a single session:

| Field | Type | Purpose |
|-------|------|---------|
| `goal` | `str` | What the user is trying to achieve |
| `clarifications` | `List[str]` | User-stated preferences and background |
| `constraints` | `List[str]` | User-imposed rules on the response |
| `explored_topics` | `List[str]` | Questions substantively answered |
| `unresolved_questions` | `List[str]` | Questions the agent couldn't answer (IDK) |

**Persistence:** `~/.deepseek_chat/dialogue_task.json` (or `DIALOGUE_TASK_PATH` env var)

**Update mechanism:** The LLM embeds special markers in its responses:

| Marker | When |
|--------|------|
| `[GOAL: text]` | First response — always, based on what user asks |
| `[CLARIFIED: text]` | User states a preference or background detail |
| `[CONSTRAINT: text]` | User restricts approach, language, or tools |
| `[TOPIC: text]` | Substantive answer given; also auto-clears matching `[UNRESOLVED:]` |
| `[UNRESOLVED: text]` | Question couldn't be answered (IDK) |

`DialogueTaskHook.after_stream` parses these markers and calls `apply_marker()` after each response.

**List cap:** Each list (`clarifications`, `constraints`, `explored_topics`, `unresolved_questions`) is capped at `_MAX_LIST_SIZE = 50` items. When a list exceeds the cap, the oldest entry is dropped (`list.pop(0)`). This prevents unbounded growth across very long sessions.

**Cleared on `/clear`** — dialogue state is session-scoped.

---

## Shared patterns

### Storage paths

All stores use `~/.deepseek_chat/` by default, defined in `deepseek_chat/core/paths.py`.
Paths can be overridden via env vars for testing:

```python
DIALOGUE_TASK_PATH=/tmp/test_task.json pytest tests/test_dialogue_task.py
```

### Reload on every request

All stores are loaded from disk on **every request** (not cached in memory). This means edits to JSON files take effect immediately without restarting the app.

### Import

All four classes are available from the package root:

```python
from deepseek_chat.core.memory import MemoryStore, UserProfile, InvariantStore, DialogueTask
```
