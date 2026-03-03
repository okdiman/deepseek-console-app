from typing import Dict, List, Any

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

    def get_system_prompt_injection(self) -> str:
        """
        Returns a formatted string containing all memory layers
        to be injected into an agent's system prompt.
        """
        parts = []
        
        if self.long_term_memory:
            parts.append("[LONG-TERM MEMORY (Persistent Profile & Core Rules)]")
            for i, fact in enumerate(self.long_term_memory, 1):
                parts.append(f"{i}. {fact}")
            parts.append("") # padding
            
        if self.working_memory:
            parts.append("[WORKING MEMORY (Current Task Context)]")
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
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryStore":
        """Deserialize memory from persistence."""
        store = cls()
        if data:
            store.working_memory = data.get("working_memory", [])
            store.long_term_memory = data.get("long_term_memory", [])
        return store
