from __future__ import annotations

from .base_agent import BaseAgent
from .hooks import MemoryInjectionHook, UserProfileHook, TaskStateHook, AutoTitleHook, InvariantGuardHook

SYSTEM_PROMPT = (
    "You are a senior Android developer with 10 years of professional experience. "
    "Provide concise, production-ready guidance focused on modern Android development "
    "(Kotlin, Jetpack, Compose, Coroutines, Architecture Components, testing, and "
    "performance). Ask clarifying questions when requirements are ambiguous and "
    "prefer best practices, clean architecture, and maintainable solutions."
)

class AndroidAgent(BaseAgent):
    """
    Encapsulates LLM request/response flow with Android-focused system prompt.
    """
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, client, session, task_machine=None, mcp_manager=None):
        hooks = [
            MemoryInjectionHook(),
            UserProfileHook(),
            InvariantGuardHook(),
            TaskStateHook(),
            AutoTitleHook(),
        ]
        super().__init__(client, session, hooks=hooks, mcp_manager=mcp_manager)
        self._task_machine = task_machine
