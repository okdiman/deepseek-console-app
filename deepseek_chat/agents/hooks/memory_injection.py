"""
MemoryInjectionHook — injects Explicit Memory Store into conversation history.
"""
from __future__ import annotations

from typing import Dict, List, TYPE_CHECKING

from .base import AgentHook

if TYPE_CHECKING:
    from ..base_agent import BaseAgent


class MemoryInjectionHook(AgentHook):
    """
    Injects the Explicit Memory Store into the conversation history as a late
    system message, placed right before the user's latest message.
    This structural placement ensures the LLM treats memory facts as a recent
    context update, preventing it from anchoring on stale conversation history.
    """
    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        from ...core.memory import MemoryStore
        memory = MemoryStore.load()
        memory_injection = memory.get_system_prompt_injection()
        if memory_injection:
            memory_msg = {"role": "system", "content": memory_injection}
            # Insert right before the last message (user's latest input)
            if len(history) >= 2:
                history.insert(-1, memory_msg)
            else:
                history.insert(0, memory_msg)
        return system_prompt

    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        pass
