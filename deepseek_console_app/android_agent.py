from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional

from .client import DeepSeekClient, StreamMetrics
from .session import ChatSession


@dataclass(frozen=True)
class AgentResult:
    content: str
    metrics: Optional[StreamMetrics]


SYSTEM_PROMPT = (
    "You are a senior Android developer with 10 years of professional experience. "
    "Provide concise, production-ready guidance focused on modern Android development "
    "(Kotlin, Jetpack, Compose, Coroutines, Architecture Components, testing, and "
    "performance). Ask clarifying questions when requirements are ambiguous and "
    "prefer best practices, clean architecture, and maintainable solutions."
)


class AndroidAgent:
    """
    Encapsulates LLM request/response flow with Android-focused system prompt.

    Responsibilities:
    - Accept user input.
    - Update conversation history.
    - Call LLM via DeepSeekClient.
    - Aggregate streamed response.
    - Persist assistant response in session.
    """

    def __init__(self, client: DeepSeekClient, session: ChatSession) -> None:
        self._client = client
        self._session = session

    async def stream_reply(
        self, user_input: str, temperature: Optional[float] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream the assistant reply while maintaining session state.

        Yields: chunks of assistant content.
        """
        self._session.add_user(user_input)

        response_parts: List[str] = []
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ] + self._session.messages()
        async for chunk in self._client.stream_message(
            messages, temperature=temperature
        ):
            response_parts.append(chunk)
            yield chunk

        response = "".join(response_parts).strip()
        if response:
            self._session.add_assistant(response)

    async def ask(
        self, user_input: str, temperature: Optional[float] = None
    ) -> AgentResult:
        """
        Non-streaming helper that collects the full response.

        Returns:
            AgentResult with full content and last metrics.
        """
        response_parts: List[str] = []
        async for chunk in self.stream_reply(user_input, temperature=temperature):
            response_parts.append(chunk)

        content = "".join(response_parts).strip()
        metrics = self._client.last_metrics()
        return AgentResult(content=content, metrics=metrics)
