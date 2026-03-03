from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional

from ..core.client import DeepSeekClient, StreamMetrics
from ..core.session import ChatSession
from .strategies import get_strategy
from .hooks import AgentHook


@dataclass(frozen=True)
class AgentResult:
    content: str
    metrics: Optional[StreamMetrics]


class BaseAgent:
    """
    Pipeline-based abstract base class for AI agents.
    Executes the LLM request/response stream while delegating side-effects 
    (memory, tokens, auto-titles) to injected `AgentHook` instances.
    """
    
    SYSTEM_PROMPT = ""  # Must be overridden by subclasses

    def __init__(self, client: DeepSeekClient, session: ChatSession, hooks: Optional[List[AgentHook]] = None) -> None:
        self._client = client
        self._session = session
        self._hooks = hooks or []

    async def stream_reply(
        self, user_input: str, temperature: Optional[float] = None, top_p: Optional[float] = None, strategy: str = "default"
    ) -> AsyncGenerator[str, None]:
        """
        Stream the assistant reply. Executes pre-stream and post-stream hooks to manage side-effects.
        """
        self._session.add_user(user_input)

        context_strategy = get_strategy(strategy, self._client, self._session)
        await context_strategy.process_context(self.SYSTEM_PROMPT, user_input)

        system_msg = context_strategy.get_system_message_for_response()
        if system_msg:
            yield system_msg

        # 1. Apply pre-stream hooks to modify system prompt
        system_prompt = self.SYSTEM_PROMPT
        history_messages = context_strategy.build_history_messages(self.SYSTEM_PROMPT)

        for hook in self._hooks:
            system_prompt = await hook.before_stream(self, user_input, system_prompt, history_messages)
            
        # Re-build final request combining hooked prompt and user input
        history_messages[0] = {"role": "system", "content": system_prompt}

        response_parts: List[str] = []
        try:
            # 2. Execute LLM stream
            async for chunk in self._client.stream_message(
                history_messages, temperature=temperature, top_p=top_p
            ):
                response_parts.append(chunk)
                yield chunk
        finally:
            response = "".join(response_parts).strip()
            if response:
                self._session.add_assistant(response)
                
            # 3. Execute post-stream hooks for background tasks/logging
            for hook in self._hooks:
                await hook.after_stream(self, response)

    async def ask(
        self, user_input: str, temperature: Optional[float] = None, top_p: Optional[float] = None, strategy: str = "default"
    ) -> AgentResult:
        """
        Non-streaming helper that collects the full response using the Hook pipeline.
        """
        response_parts: List[str] = []
        async for chunk in self.stream_reply(user_input, temperature=temperature, top_p=top_p, strategy=strategy):
            response_parts.append(chunk)

        content = "".join(response_parts).strip()
        metrics = self._client.last_metrics()
        return AgentResult(
            content=content,
            metrics=metrics,
        )
