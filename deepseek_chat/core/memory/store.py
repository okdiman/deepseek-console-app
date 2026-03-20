import json
import os
from typing import Dict, List, Any

from deepseek_chat.core.paths import DATA_DIR

class MemoryStore:
    """
    Standalone memory component that encapsulates the explicit memory layers
    (Working Memory and Long-Term Memory) for use across any agent.
    """

    def __init__(self) -> None:
        self.working_memory: List[str] = []
        self.long_term_memory: List[str] = []

    def set_working_memory(self, facts: List[str]) -> None:
        self.working_memory = list(facts)

    def add_working_memory(self, fact: str) -> None:
        if fact not in self.working_memory:
            self.working_memory.append(fact)

    def remove_working_memory(self, index: int) -> None:
        if 0 <= index < len(self.working_memory):
            self.working_memory.pop(index)

    def set_long_term_memory(self, facts: List[str]) -> None:
        self.long_term_memory = list(facts)

    def add_long_term_memory(self, fact: str) -> None:
        if fact not in self.long_term_memory:
            self.long_term_memory.append(fact)

    def remove_long_term_memory(self, index: int) -> None:
        if 0 <= index < len(self.long_term_memory):
            self.long_term_memory.pop(index)

    def clear_working_memory(self) -> None:
        """Clears working memory (session-scoped). Called on /clear or new session."""
        self.working_memory = []

    def get_system_prompt_injection(self) -> str:
        """
        Returns a formatted string containing all memory layers
        to be injected into an agent's system prompt.
        """
        parts = []

        if self.long_term_memory or self.working_memory:
            parts.append(
                "CRITICAL: The following memory sections contain GROUND TRUTH facts about the user. "
                "You MUST use this information in your responses. If your previous responses in the "
                "conversation contradict this memory, the MEMORY IS CORRECT and your previous responses were wrong. "
                "Always prioritize memory data over conversation history."
            )
            parts.append("")

        if self.long_term_memory:
            parts.append("[LONG-TERM MEMORY (Permanent — persists across all sessions)]")
            for i, fact in enumerate(self.long_term_memory, 1):
                parts.append(f"{i}. {fact}")
            parts.append("") # padding

        if self.working_memory:
            parts.append("[WORKING MEMORY (Temporary — clears on session reset)]")
            for i, fact in enumerate(self.working_memory, 1):
                parts.append(f"{i}. {fact}")
            parts.append("") # padding

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize memory for persistence."""
        return {
            "working_memory": self.working_memory,
            "long_term_memory": self.long_term_memory
        }

    @classmethod
    def get_storage_path(cls) -> str:
        """Returns the default storage path for the global memory."""
        memory_path = os.getenv("DEEPSEEK_MEMORY_PATH", str(DATA_DIR / "memory.json"))
        return os.path.expanduser(memory_path)

    @classmethod
    def load(cls) -> "MemoryStore":
        """Deserializes memory from the global persistent file."""
        store = cls()
        path = cls.get_storage_path()
        if not os.path.exists(path):
            return store

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                store.working_memory = data.get("working_memory", [])
                store.long_term_memory = data.get("long_term_memory", [])
        except Exception as e:
            print(f"[Error] Failed to load MemoryStore from {path}: {e}")

        return store

    def save(self) -> None:
        """Saves memory to the global persistent JSON file."""
        path = self.get_storage_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Error] Failed to save MemoryStore to {path}: {e}")
