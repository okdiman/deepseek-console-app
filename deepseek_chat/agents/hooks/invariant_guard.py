"""
InvariantGuardHook — injects global invariants into the conversation history
as a late system message, ensuring the LLM always respects hard constraints.
"""
from __future__ import annotations

from typing import Dict, List, TYPE_CHECKING

from .base import AgentHook

if TYPE_CHECKING:
    from ..base_agent import BaseAgent


class InvariantGuardHook(AgentHook):
    """
    Injects the InvariantStore constraints into the conversation history
    as a system message placed right before the user's latest message.
    This ensures the LLM treats invariants as the highest-priority context.
    """
    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        from ...core.invariants import InvariantStore
        store = InvariantStore.load()
        injection = store.get_system_prompt_injection()
        if injection:
            invariant_msg = {"role": "system", "content": injection}
            # Insert right before the last message (user's latest input)
            if len(history) >= 2:
                history.insert(-1, invariant_msg)
            else:
                history.insert(0, invariant_msg)
        return system_prompt

    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        pass
