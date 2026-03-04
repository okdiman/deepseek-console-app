"""
UserProfileHook — injects global UserProfile context into the system prompt.
"""
from __future__ import annotations

from typing import Dict, List, TYPE_CHECKING

from .base import AgentHook

if TYPE_CHECKING:
    from ..base_agent import BaseAgent


class UserProfileHook(AgentHook):
    """
    Injects context from the global UserProfile to personalize the agent responses.
    """
    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        from ...core.profile import UserProfile
        
        profile = UserProfile.load()
        if profile.is_empty():
            return system_prompt
            
        profile_blocks = ["[USER PROFILE PARAMETERS]"]
        if profile.name:
            profile_blocks.append(f"Name: {profile.name}")
        if profile.role:
            profile_blocks.append(f"Role: {profile.role}")
        if profile.style_preferences:
            profile_blocks.append(f"Style Preferences: {profile.style_preferences}")
        if profile.formatting_rules:
            profile_blocks.append(f"Formatting Rules: {profile.formatting_rules}")
        if profile.constraints:
            profile_blocks.append(f"Strict Constraints: {profile.constraints}")
            
        profile_string = "\n".join(profile_blocks)
        
        # We append the profile instructions at the very end of the system prompt
        # to ensure the LLM prioritizes these constraints.
        return system_prompt + f"\n\n{profile_string}"

    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        pass
