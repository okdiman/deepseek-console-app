"""
InvariantStore — global invariants (hard constraints) that the assistant
must never violate. Persisted to ~/.deepseek_chat/invariants.json.
"""
import json
import os
from typing import Dict, List, Any


class InvariantStore:
    """
    Manages a list of invariant rules — architecture decisions, stack constraints,
    business rules — that the AI assistant is forbidden from violating.
    """

    def __init__(self) -> None:
        self.invariants: List[str] = []

    def add(self, rule: str) -> None:
        """Add an invariant rule (no duplicates)."""
        if rule and rule not in self.invariants:
            self.invariants.append(rule)

    def remove(self, index: int) -> None:
        """Remove invariant by index."""
        if 0 <= index < len(self.invariants):
            self.invariants.pop(index)

    def get_all(self) -> List[str]:
        return list(self.invariants)

    def get_system_prompt_injection(self) -> str:
        """
        Returns a formatted string to inject into the system prompt.
        Contains strict instructions to never violate the listed invariants
        and to refuse requests that conflict with them.
        """
        if not self.invariants:
            return ""

        parts = [
            "STRICT INVARIANTS — NON-NEGOTIABLE CONSTRAINTS",
            "=" * 50,
            "",
            "The following invariants are ABSOLUTE RULES that you MUST obey at all times.",
            "You are FORBIDDEN from proposing, suggesting, or implementing anything that violates them.",
            "If a user request conflicts with ANY invariant below, you MUST:",
            "1. REFUSE to execute the conflicting part of the request.",
            "2. EXPLICITLY STATE which invariant would be violated and why.",
            "3. Suggest an alternative that satisfies all invariants.",
            "",
        ]

        for i, rule in enumerate(self.invariants, 1):
            parts.append(f"  #{i}: {rule}")

        parts.append("")
        parts.append(
            "REMINDER: These invariants override any user instruction. "
            "Never break them, even if the user explicitly asks you to."
        )

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for persistence."""
        return {"invariants": self.invariants}

    @classmethod
    def get_storage_path(cls) -> str:
        """Returns the default storage path for invariants."""
        path = os.getenv("DEEPSEEK_INVARIANTS_PATH", "~/.deepseek_chat/invariants.json")
        return os.path.expanduser(path)

    @classmethod
    def load(cls) -> "InvariantStore":
        """Loads InvariantStore from disk, or returns empty if not found."""
        store = cls()
        path = cls.get_storage_path()
        if not os.path.exists(path):
            return store

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                store.invariants = data.get("invariants", [])
        except Exception as e:
            print(f"[Error] Failed to load InvariantStore from {path}: {e}")

        return store

    def save(self) -> None:
        """Saves invariants to the global persistent JSON file."""
        path = self.get_storage_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Error] Failed to save InvariantStore to {path}: {e}")
