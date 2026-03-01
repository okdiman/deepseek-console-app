from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional

from ..core.client import DeepSeekClient, StreamMetrics
from ..core.session import ChatSession
from ..core.token_counter import TokenCount, count_messages_tokens, count_text_tokens
from .strategies import get_strategy


@dataclass(frozen=True)
class TokenStats:
    request: TokenCount
    history: TokenCount
    response: TokenCount


@dataclass(frozen=True)
class AgentResult:
    content: str
    metrics: Optional[StreamMetrics]
    token_stats: Optional[TokenStats]


SYSTEM_PROMPT = (
    "You are a helpful, knowledgeable AI assistant. "
    "Provide clear, conversational, and accurate answers to user questions. "
    "You are not restricted to any specific topic, but you should always strive "
    "to be concise and precise in your assistance."
)


class GeneralAgent:
    """
    Encapsulates LLM request/response flow with a general-purpose system prompt.
    """

    def __init__(self, client: DeepSeekClient, session: ChatSession) -> None:
        self._client = client
        self._session = session
        self._last_token_stats: Optional[TokenStats] = None

    def last_token_stats(self) -> Optional[TokenStats]:
        return self._last_token_stats

    async def stream_reply(
        self, user_input: str, temperature: Optional[float] = None, top_p: Optional[float] = None, strategy: str = "default"
    ) -> AsyncGenerator[str, None]:
        """
        Stream the assistant reply while maintaining session state.
        Supports multiple context strategies via ContextStrategy classes.
        """
        self._session.add_user(user_input)

        context_strategy = get_strategy(strategy, self._client, self._session)
        await context_strategy.process_context(SYSTEM_PROMPT, user_input)

        system_msg = context_strategy.get_system_message_for_response()
        if system_msg:
            yield system_msg

        model = self._client._config.model
            
        request_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ]
        
        history_messages = context_strategy.build_history_messages(SYSTEM_PROMPT)

        request_count = count_messages_tokens(request_messages, model=model)
        history_count = count_messages_tokens(history_messages, model=model)

        response_parts: List[str] = []
        try:
            async for chunk in self._client.stream_message(
                history_messages, temperature=temperature, top_p=top_p
            ):
                response_parts.append(chunk)
                yield chunk
        finally:
            response = "".join(response_parts).strip()
            response_count = count_text_tokens(response, model=model)

            self._last_token_stats = TokenStats(
                request=request_count,
                history=history_count,
                response=response_count,
            )

            if response:
                self._session.add_assistant(response)
            
        # Background task: Auto-titling the session summary based on the first few messages
        # We only generate a title if it's currently empty, or if we want to "refresh" it.
        # Let's say we refresh it after 2 messages to get more context, and then keep it.
        total_msgs = len(self._session.messages())
        if total_msgs in (2, 4) and not self._session.summary:
            await self._generate_session_title()

    async def _generate_session_title(self) -> None:
        """Generates a short 3-5 word title for the session based on context."""
        messages = self._session.messages()
        if not messages:
            return
            
        title_prompt = (
            "Напиши ОЧЕНЬ КРАТКИЙ заголовок (3-5 слов, без кавычек и точек в конце) "
            "для этого диалога, отражающий его основную суть."
        )
        
        request = [
            {"role": "system", "content": "You are a helpful assistant that generates extremely concise titles."},
        ]
        # Include up to the first 4 messages for context
        request.extend(messages[:4])
        request.append({"role": "user", "content": title_prompt})
        
        response_parts = []
        try:
            async for chunk in self._client.stream_message(request, temperature=0.3):
                response_parts.append(chunk)
                
            new_title = "".join(response_parts).strip().strip('"').strip("'")
            print(f"[DEBUG] Generated new session title: '{new_title}'")
            if new_title:
                self._session.summary = new_title
        except Exception as e:
            print(f"[DEBUG] Error generating session title: {e}")

    async def ask(
        self, user_input: str, temperature: Optional[float] = None, top_p: Optional[float] = None
    ) -> AgentResult:
        """
        Non-streaming helper that collects the full response.

        Returns:
            AgentResult with full content and last metrics.
        """
        response_parts: List[str] = []
        async for chunk in self.stream_reply(user_input, temperature=temperature, top_p=top_p):
            response_parts.append(chunk)

        content = "".join(response_parts).strip()
        metrics = self._client.last_metrics()
        return AgentResult(
            content=content,
            metrics=metrics,
            token_stats=self._last_token_stats,
        )
