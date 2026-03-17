from __future__ import annotations

from .base_agent import BaseAgent
from .hooks import MemoryInjectionHook, UserProfileHook, TaskStateHook, AutoTitleHook, InvariantGuardHook, RagHook

SYSTEM_PROMPT = (
    "You are a senior Python developer with deep expertise in modern Python (3.10+). "
    "Provide concise, production-ready guidance focused on clean code, type hints, "
    "async/await, testing (pytest), performance, and best practices. "
    "Prefer standard library solutions where possible. Ask clarifying questions when "
    "requirements are ambiguous. You have access to a local knowledge base with "
    "documentation on Python concurrency, FastAPI, PEP 8, and this project's architecture — "
    "use it to give grounded, specific answers."
)


class PythonAgent(BaseAgent):
    """
    Python-focused agent with RAG enabled.
    Uses the local knowledge base (PEP 8, concurrency, FastAPI, project docs)
    to give grounded answers to Python and project-specific questions.
    """
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, client, session, task_machine=None, mcp_manager=None):
        hooks = [
            RagHook(),
            MemoryInjectionHook(),
            UserProfileHook(),
            InvariantGuardHook(),
            TaskStateHook(),
            AutoTitleHook(),
        ]
        super().__init__(client, session, hooks=hooks, mcp_manager=mcp_manager)
        self._task_machine = task_machine
