import json
import os
from typing import Optional
from pydantic import BaseModel


class UserProfile(BaseModel):
    """
    Represents the personalization layer for an AI assistant.
    Holds user preferences, constraints, and professional context 
    which apply globally across all chat sessions.
    """
    name: str = ""
    role: str = ""
    style_preferences: str = ""
    formatting_rules: str = ""
    constraints: str = ""

    def is_empty(self) -> bool:
        return not any([
            self.name, self.role, self.style_preferences, 
            self.formatting_rules, self.constraints
        ])

    @classmethod
    def get_storage_path(cls) -> str:
        """Returns the default storage path for the global profile."""
        profile_path = os.getenv("DEEPSEEK_PROFILE_PATH", "~/.deepseek_chat/profile.json")
        return os.path.expanduser(profile_path)

    @classmethod
    def load(cls) -> "UserProfile":
        """Loads the UserProfile from disk, or returns an empty one if not found."""
        path = cls.get_storage_path()
        if not os.path.exists(path):
            return cls()
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return cls(**data)
        except Exception as e:
            print(f"[Error] Failed to load UserProfile from {path}: {e}")
            return cls()

    def save(self) -> None:
        """Saves the UserProfile to disk as JSON."""
        path = self.get_storage_path()
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.model_dump(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Error] Failed to save UserProfile to {path}: {e}")
