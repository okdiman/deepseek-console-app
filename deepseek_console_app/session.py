from typing import Dict, List


class ChatSession:
    """Stores conversation history for chat-style APIs."""

    def __init__(self, max_messages: int = 40) -> None:
        self._messages: List[Dict[str, str]] = []
        self._max_messages = max_messages

    def add_user(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, content: str) -> None:
        self._messages.append({"role": "assistant", "content": content})
        self._trim()

    def clear(self) -> None:
        self._messages = []

    def messages(self) -> List[Dict[str, str]]:
        return list(self._messages)

    def _trim(self) -> None:
        if len(self._messages) > self._max_messages:
            self._messages = self._messages[-self._max_messages :]
