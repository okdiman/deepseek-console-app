from __future__ import annotations

from .base_agent import BaseAgent
from .hooks import MemoryInjectionHook, InvariantGuardHook


class BackgroundAgent(BaseAgent):
    """
    Minimal agent for autonomous background task execution.

    Uses only read-only hooks (Memory + Invariants) — no AutoTitle,
    no TaskState, no UserProfile writes — so background runs don't
    pollute the user-facing session state.
    """

    SYSTEM_PROMPT = (
        "You are running as an autonomous background scheduled task. "
        "You MUST fully complete the user's request without asking for permission "
        "or waiting for follow-ups. "
        "If you use a tool that returns IDs or partial data, you MUST immediately "
        "use follow-up tools to fetch the full details and produce a complete, "
        "human-readable final response. "
        "Be concise but thorough."
    )

    def __init__(self, client, session, mcp_manager=None):
        hooks = [
            MemoryInjectionHook(),
            InvariantGuardHook(),
        ]
        super().__init__(client, session, hooks=hooks, mcp_manager=mcp_manager)
