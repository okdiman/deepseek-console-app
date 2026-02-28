from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional

from ..core.client import DeepSeekClient, StreamMetrics
from ..core.session import ChatSession
from ..core.token_counter import TokenCount, count_messages_tokens, count_text_tokens


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

    async def _compress_history(self) -> None:
        """Summarizes old messages and updates the session."""
        config = self._client._config
        messages = self._session.messages()
        keep_count = config.compression_keep
        
        # We need to summarize messages EXCEPT the ones we are keeping.
        if len(messages) <= keep_count:
            return
            
        old_messages = messages[:-keep_count]
        
        # Build prompt for summarization
        summarize_prompt = "Сделай краткое саммари нашего предыдущего диалога. Сохрани ключевые факты и суть обсуждаемой темы."
        if self._session.summary:
            summarize_prompt += f" Вот текущее саммари, дополни его новой информацией:\n{self._session.summary}"
            
        summary_request = [
            {"role": "system", "content": "You are a specialized AI that summarizes context for an AI Assistant without losing crucial details."},
        ]
        summary_request.extend(old_messages)
        summary_request.append({"role": "user", "content": summarize_prompt})
        
        response_parts = []
        async for chunk in self._client.stream_message(summary_request, temperature=0.3):
            response_parts.append(chunk)
            
        new_summary = "".join(response_parts).strip()
        if new_summary:
            self._session.apply_compression(new_summary, keep_count)

    async def stream_reply(
        self, user_input: str, temperature: Optional[float] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream the assistant reply while maintaining session state.

        Yields: chunks of assistant content.
        """
        self._session.add_user(user_input)

        config = self._client._config
        if config.compression_enabled and len(self._session.messages()) > config.compression_threshold:
            yield "\n*[System: Сжимаю старый контекст для экономии токенов...]*\n\n"
            await self._compress_history()

        model = self._client._config.model
        request_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ]
        history_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        if self._session.summary:
            history_messages.append({
                "role": "system",
                "content": f"Previous conversation summary: {self._session.summary}"
            })
            
        history_messages.extend(self._session.messages())

        request_count = count_messages_tokens(request_messages, model=model)
        history_count = count_messages_tokens(history_messages, model=model)

        response_parts: List[str] = []
        async for chunk in self._client.stream_message(
            history_messages, temperature=temperature
        ):
            response_parts.append(chunk)
            yield chunk

        response = "".join(response_parts).strip()
        response_count = count_text_tokens(response, model=model)

        self._last_token_stats = TokenStats(
            request=request_count,
            history=history_count,
            response=response_count,
        )

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
        return AgentResult(
            content=content,
            metrics=metrics,
            token_stats=self._last_token_stats,
        )
