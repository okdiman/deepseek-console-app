from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, List, Optional

from ..core.client import DeepSeekClient
from ..core.session import ChatSession


class ContextStrategy(ABC):
    """
    Base class for context management strategies used by the GeneralAgent.
    """

    def __init__(self, client: DeepSeekClient, session: ChatSession) -> None:
        self._client = client
        self._session = session

    @abstractmethod
    async def process_context(self, system_prompt: str, user_input: str) -> None:
        """
        Execute any preprocessing side-effects (e.g., summarizing old history, extracting facts).
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
        For example: "[System: Compressed old context...]"
        """
        return None


class DefaultStrategy(ContextStrategy):
    """
    Folds older conversation context into a running summary to save tokens.
    Used for 'default' and 'branching' strategies.
    """

    async def process_context(self, system_prompt: str, user_input: str) -> None:
        config = self._client._config
        user_msg_count = sum(1 for m in self._session.messages() if m.get("role") == "user")
        
        if config.compression_enabled and user_msg_count > config.compression_threshold:
            await self._compress_history()

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
        config = self._client._config
        user_msg_count = sum(1 for m in self._session.messages() if m.get("role") == "user")
        
        # This count includes the current input because add_user happens before strategy
        # However, to be perfectly accurate we only yield the message if we ACTUALLY compress.
        # But mirroring original logic:
        if config.compression_enabled and user_msg_count > config.compression_threshold:
            return "\n*[System: Сжимаю старый контекст для экономии токенов...]*\n\n"
        return None


class WindowStrategy(ContextStrategy):
    """
    Maintains a strict sliding window of the last N messages to preserve recent context.
    Forgets older history entirely.
    """
    def __init__(self, client: DeepSeekClient, session: ChatSession, window_size: int = 10) -> None:
        super().__init__(client, session)
        self.window_size = window_size

    async def process_context(self, system_prompt: str, user_input: str) -> None:
        # Sliding window relies entirely on how we build the history messages
        pass

    def build_history_messages(self, system_prompt: str) -> List[Dict[str, str]]:
        history_messages = [{"role": "system", "content": system_prompt}]
        messages_to_include = self._session.messages()[-self.window_size:]
        history_messages.extend(messages_to_include)
        return history_messages


class FactsStrategy(ContextStrategy):
    """
    Extracts explicit requirements and facts from the user input and injects them
    into the system prompt, enforcing them across the conversation window.
    """
    def __init__(self, client: DeepSeekClient, session: ChatSession, window_size: int = 10) -> None:
        super().__init__(client, session)
        self.window_size = window_size
        self._extracted = False

    async def process_context(self, system_prompt: str, user_input: str) -> None:
        self._extracted = True
        await self._extract_facts()

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

    def build_history_messages(self, system_prompt: str) -> List[Dict[str, str]]:
        if self._session.facts:
            system_prompt += f"\n\nIMPORTANT FACTS TO REMEMBER:\n{self._session.facts}"

        history_messages = [{"role": "system", "content": system_prompt}]
        messages_to_include = self._session.messages()[-self.window_size:]
        history_messages.extend(messages_to_include)
        return history_messages

    def get_system_message_for_response(self) -> Optional[str]:
        if self._extracted:
             return "\n*[System: Извлекаю и обновляю факты...]*\n\n"
        return None

def get_strategy(strategy_name: str, client: DeepSeekClient, session: ChatSession) -> ContextStrategy:
    """Factory method to instantiate the correct strategy."""
    if strategy_name in ("default", "branching"):
        return DefaultStrategy(client, session)
    elif strategy_name == "window":
        return WindowStrategy(client, session)
    elif strategy_name == "facts":
        return FactsStrategy(client, session)
    
    # Fallback to default
    return DefaultStrategy(client, session)
