"""
DialogueTaskHook — injects structured task memory into the system prompt
and updates it from markers the agent embeds in each response.

Markers parsed from agent response:
  [GOAL: ...]        — sets / updates the conversation goal
  [CLARIFIED: ...]   — records a user clarification
  [CONSTRAINT: ...]  — records a user-imposed rule or restriction
  [TOPIC: ...]       — marks a topic as substantively answered
  [UNRESOLVED: ...]  — records a question that couldn't be answered (IDK)
"""
from __future__ import annotations

import re
from typing import Dict, List, TYPE_CHECKING

from .base import AgentHook

if TYPE_CHECKING:
    from ..base_agent import BaseAgent


_MARKER_RE = re.compile(
    r"\[(GOAL|CLARIFIED|CONSTRAINT|TOPIC|UNRESOLVED):\s*([^\]]+)\]",
    re.IGNORECASE,
)


class DialogueTaskHook(AgentHook):
    """
    before_stream: loads DialogueTask from disk, appends formatted block
                   to the system prompt.
    after_stream:  scans agent response for markers, applies them, saves.
    """

    async def before_stream(
        self,
        agent: "BaseAgent",
        user_input: str,
        system_prompt: str,
        history: List[Dict[str, str]],
    ) -> str:
        from ...core.dialogue_task import DialogueTask

        task = DialogueTask.load()
        return system_prompt + "\n\n" + task.get_injection()

    async def after_stream(self, agent: "BaseAgent", full_response: str) -> None:
        from ...core.dialogue_task import DialogueTask

        matches = _MARKER_RE.findall(full_response)
        if not matches:
            return

        task = DialogueTask.load()
        for marker_type, value in matches:
            task.apply_marker(marker_type, value)
        task.save()
