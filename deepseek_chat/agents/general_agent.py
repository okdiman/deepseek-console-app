from __future__ import annotations

from .base_agent import BaseAgent
from .hooks import MemoryInjectionHook, UserProfileHook, TaskStateHook, AutoTitleHook, InvariantGuardHook

SYSTEM_PROMPT = (
    "You are a helpful, knowledgeable AI assistant. "
    "Provide clear, conversational, and accurate answers to user questions. "
    "You are not restricted to any specific topic, but you should always strive "
    "to be concise and precise in your assistance."
)

class GeneralAgent(BaseAgent):
    """
    Encapsulates LLM request/response flow with a general-purpose system prompt.
    """
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, client, session, task_machine=None):
        hooks = [
            MemoryInjectionHook(),
            UserProfileHook(),
            InvariantGuardHook(),
            TaskStateHook(),
            AutoTitleHook(),
        ]
        super().__init__(client, session, hooks=hooks)
        self._task_machine = task_machine
