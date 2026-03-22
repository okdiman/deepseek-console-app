"""
AgentHook — abstract base class for the agent hook (middleware) interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..base_agent import BaseAgent


class AgentHook(ABC):
    """
    Interface for an Agent Hook (Middleware) that can intercept and side-effect
    during the LLM response stream lifecycle.

    suppress_tools: if set to True after before_stream, the agent will not pass
    MCP tools to the LLM for this request. Use this when the hook provides
    sufficient local context and external tools should not be offered.
    """

    suppress_tools: bool = False

    async def intercept_stream(
        self, agent: "BaseAgent", user_input: str, history: List[Dict[str, str]]
    ) -> Optional[str]:
        """
        Called before the stream is executed. If this returns a string, the agent will
        yield this string directly and SKIP calling the LLM entirely.
        """
        return None

    @abstractmethod
    async def before_stream(self, agent: "BaseAgent", user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        """
        Called right before the stream is executed. 
        Hooks can return a modified `system_prompt` string here.
        A return value of empty string or the unchanged prompt is perfectly fine.
        """
        return system_prompt

    @abstractmethod
    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        """
        Called immediately after the stream has fully yielded its response.
        Useful for firing background jobs or logging based on the full conversation.
        """
        pass
