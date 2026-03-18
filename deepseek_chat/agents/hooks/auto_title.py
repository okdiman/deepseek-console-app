"""
AutoTitleHook — auto-generates a short session title after initial messages.
"""
from __future__ import annotations

from typing import Dict, List, TYPE_CHECKING

from .base import AgentHook

if TYPE_CHECKING:
    from ..base_agent import BaseAgent


class AutoTitleHook(AgentHook):
    """
    Monitors session length and fires a background job to summarize the 
    conversation into a short title string if the session lacks one.
    """
    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        return system_prompt

    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        if agent._session.summary:
            return
        messages = agent._session.messages()
        # Count only user turns to avoid being thrown off by tool_calls/tool messages
        user_turns = sum(1 for m in messages if m.get("role") == "user")
        if len(messages) % 2 == 0 and user_turns in (1, 2):
            await self._generate_title(agent, messages)

    async def _generate_title(self, agent: BaseAgent, messages: List[Dict[str, str]]) -> None:
        if not messages:
            return

        # Only pass plain user/assistant text messages to avoid tool_calls payload
        plain = [
            m for m in messages
            if m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            and m["content"].strip()
        ]

        title_prompt = (
            "Напиши ОЧЕНЬ КРАТКИЙ заголовок (3-5 слов, без кавычек и точек в конце) "
            "для этого диалога, отражающий его основную суть."
        )

        request = [
            {"role": "system", "content": "You are a helpful assistant that generates extremely concise titles."},
        ]
        request.extend(plain[:4])
        request.append({"role": "user", "content": title_prompt})

        response_parts = []
        try:
            async for chunk in agent._client.stream_message(request, temperature=0.3):
                response_parts.append(chunk)

            new_title = "".join(response_parts).strip().strip('"').strip("'")
            if new_title:
                agent._session.summary = new_title
        except Exception:
            pass
