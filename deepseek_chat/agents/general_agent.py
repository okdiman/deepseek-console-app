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

    async def _extract_facts(self) -> None:
        """Extracts facts from the last user message and updates session.facts."""
        messages = self._session.messages()
        if not messages or messages[-1].get("role") != "user":
            return
            
        last_user_msg = messages[-1]["content"]
        facts_prompt = (
            "Извлеки новые важные факты, требования, ограничения или договоренности из следующего "
            f"сообщения пользователя: '{last_user_msg}'. "
            "Если ничего критичного нет, верни пустую строку. Если есть, верни краткий список."
        )
        
        request = [
            {"role": "system", "content": "You are a specialized AI that extracts key facts for context memory."},
        ]
        if self._session.facts:
            request.append({"role": "system", "content": f"Текущие факты:\n{self._session.facts}"})
            facts_prompt += "\nДополни текущие факты новыми, без повторений. Верни обновленный полный список факты."
            
        request.append({"role": "user", "content": facts_prompt})
        
        response_parts = []
        async for chunk in self._client.stream_message(request, temperature=0.1):
            response_parts.append(chunk)
            
        new_facts = "".join(response_parts).strip()
        if new_facts:
            self._session.facts = new_facts

    async def stream_reply(
        self, user_input: str, temperature: Optional[float] = None, strategy: str = "default"
    ) -> AsyncGenerator[str, None]:
        """
        Stream the assistant reply while maintaining session state.
        Supports multiple context strategies: default, window, facts, branching.
        """
        self._session.add_user(user_input)

        config = self._client._config
        
        user_msg_count = sum(1 for m in self._session.messages() if m.get("role") == "user")
        
        # Branching strategy uses default compression under the hood
        is_default_or_branching = strategy in ("default", "branching")
        
        if is_default_or_branching and config.compression_enabled and user_msg_count > config.compression_threshold:
            yield "\n*[System: Сжимаю старый контекст для экономии токенов...]*\n\n"
            await self._compress_history()
            
        if strategy == "facts":
            yield "\n*[System: Извлекаю и обновляю факты...]*\n\n"
            await self._extract_facts()

        model = self._client._config.model
        sys_prompt = SYSTEM_PROMPT
        if strategy == "facts" and self._session.facts:
            sys_prompt += f"\n\nIMPORTANT FACTS TO REMEMBER:\n{self._session.facts}"
            
        request_messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_input},
        ]
        history_messages = [{"role": "system", "content": sys_prompt}]
        
        if is_default_or_branching and self._session.summary:
            history_messages.append({
                "role": "system",
                "content": f"Previous conversation summary: {self._session.summary}"
            })
            
        # For sliding window and facts strategies, we take the last 10 messages max
        messages_to_include = self._session.messages()
        if strategy in ("window", "facts"):
            window_size = 10
            messages_to_include = messages_to_include[-window_size:]
            
        history_messages.extend(messages_to_include)

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
