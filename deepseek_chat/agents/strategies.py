from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from ..core.client import DeepSeekClient
from ..core.session import ChatSession


class ContextStrategy(ABC):
    """
    Base class for context management strategies.
    """

    def __init__(self, client: DeepSeekClient, session: ChatSession) -> None:
        self._client = client
        self._session = session

    @abstractmethod
    async def process_context(self, system_prompt: str, user_input: str) -> None:
        """
        Execute any preprocessing side-effects (e.g., summarizing old history).
        """
        pass

    @abstractmethod
    def build_history_messages(self, system_prompt: str) -> List[Dict[str, str]]:
        """
        Build the messages list to be sent to the LLM.
        """
        pass

    def get_system_message_for_response(self) -> Optional[str]:
        """
        Optionally return a meta-message to yield back to the user before the LLM streams.
        """
        return None


class UnifiedStrategy(ContextStrategy):
    """
    Automatic context optimization combining:
    1. Sliding window — always keep last N messages intact
    2. Compression — summarize older messages into a running summary
    3. Auto-facts — extract key facts during compression and add to Working Memory
    """

    def __init__(self, client: DeepSeekClient, session: ChatSession) -> None:
        super().__init__(client, session)
        self._compressed = False
        self._last_extracted_facts: List[str] = []

    async def process_context(self, system_prompt: str, user_input: str) -> None:
        config = self._client.config
        user_msg_count = sum(1 for m in self._session.messages() if m.get("role") == "user")

        if config.compression_enabled and user_msg_count > config.compression_threshold:
            await self._compress_and_extract()

    async def _compress_and_extract(self) -> None:
        """Summarizes old messages and extracts key facts in a single LLM call."""
        config = self._client.config
        messages = self._session.messages()
        keep_count = config.compression_keep

        if len(messages) <= keep_count:
            return

        old_messages = messages[:-keep_count]

        # Build prompt for combined summarization + fact extraction
        prompt = (
            "Проанализируй следующий диалог и верни ТОЛЬКО валидный JSON (без markdown-разметки) в формате:\n"
            '{"summary": "краткое саммари диалога", "facts": ["факт 1", "факт 2"]}\n\n'
            "В summary — сохрани суть и ключевые темы обсуждения.\n"
            "В facts — извлеки конкретные требования, ограничения, предпочтения и договорённости пользователя. "
            "Если фактов нет, верни пустой массив."
        )

        if self._session.summary:
            prompt += f"\n\nТекущее саммари (дополни его):\n{self._session.summary}"

        request = [
            {"role": "system", "content": "You are a specialized AI that summarizes conversations and extracts key facts. Always respond with valid JSON only."},
        ]
        request.extend(old_messages)
        request.append({"role": "user", "content": prompt})

        response_parts = []
        async for chunk in self._client.stream_message(request, temperature=0.1):
            response_parts.append(chunk)

        raw_response = "".join(response_parts).strip()
        
        # Parse JSON response
        new_summary = ""
        extracted_facts: List[str] = []
        
        try:
            # Strip markdown code fences if present
            if raw_response.startswith("```"):
                raw_response = raw_response.strip("`").removeprefix("json").strip()
            
            parsed = json.loads(raw_response)
            new_summary = parsed.get("summary", "")
            extracted_facts = parsed.get("facts", [])
        except (json.JSONDecodeError, AttributeError):
            # Fallback: treat entire response as summary
            new_summary = raw_response

        if new_summary:
            self._session.apply_compression(new_summary, keep_count)

        # Auto-populate Working Memory with extracted facts
        clean_facts = [f.strip() for f in extracted_facts if isinstance(f, str) and f.strip()]
        if clean_facts:
            from ..core.memory import MemoryStore
            memory = MemoryStore.load()
            for fact in clean_facts:
                memory.add_working_memory(fact)
            memory.save()

        self._compressed = True
        self._last_extracted_facts = clean_facts

    def build_history_messages(self, system_prompt: str) -> List[Dict[str, str]]:
        history_messages = [{"role": "system", "content": system_prompt}]

        if self._session.summary:
            history_messages.append({
                "role": "system",
                "content": f"Previous conversation summary: {self._session.summary}"
            })

        history_messages.extend(self._session.messages())
        return history_messages

    def get_system_message_for_response(self) -> Optional[str]:
        if not self._compressed:
            return None

        if self._last_extracted_facts:
            facts_list = ", ".join(f'"{f}"' for f in self._last_extracted_facts)
            return f"\n*[System: Контекст сжат. Извлечённые факты → Working Memory: {facts_list}]*\n\n"
        else:
            return "\n*[System: Контекст сжат. Новых фактов не обнаружено.]*\n\n"


def get_strategy(client: DeepSeekClient, session: ChatSession) -> ContextStrategy:
    """Returns the unified context strategy."""
    return UnifiedStrategy(client, session)
