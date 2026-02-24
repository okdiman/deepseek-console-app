import json
import os
from datetime import datetime
from typing import Dict, List, Optional


class ChatSession:
    """Stores conversation history for chat-style APIs."""

    _FORMAT_VERSION = 1

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

    def load(self, path: str) -> None:
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            return
        except json.JSONDecodeError:
            self._messages = []
            return

        messages = payload.get("messages", [])
        if isinstance(messages, list):
            valid_messages: List[Dict[str, str]] = []
            for item in messages:
                if (
                    isinstance(item, dict)
                    and item.get("role") in {"user", "assistant"}
                    and isinstance(item.get("content"), str)
                ):
                    valid_messages.append(
                        {"role": item["role"], "content": item["content"]}
                    )
            self._messages = valid_messages
            self._trim()

    def save(self, path: str, provider: Optional[str], model: Optional[str]) -> None:
        if not path:
            return

        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        payload = {
            "format_version": self._FORMAT_VERSION,
            "provider": provider or "",
            "model": model or "",
            "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "messages": self.messages(),
        }

        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    def _trim(self) -> None:
        if len(self._messages) > self._max_messages:
            self._messages = self._messages[-self._max_messages :]
