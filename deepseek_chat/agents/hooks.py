from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .base_agent import BaseAgent


class AgentHook(ABC):
    """
    Interface for an Agent Hook (Middleware) that can intercept and side-effect
    during the LLM response stream lifecycle.
    """
    
    @abstractmethod
    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        """
        Called right before the stream is executed. 
        Hooks can return a modified `system_prompt` string here.
        A return value of empty string or the unchanged prompt is perfectly fine.
        """
        return system_prompt

    @abstractmethod
    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        """
        Called immediately after the stream has fully yielded its response.
        Useful for firing background jobs or logging based on the full conversation.
        """
        pass


class UserProfileHook(AgentHook):
    """
    Injects context from the global UserProfile to personalize the agent responses.
    """
    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        from ..core.profile import UserProfile
        
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


class MemoryInjectionHook(AgentHook):
    """
    Injects the Explicit Memory Store into the conversation history as a late
    system message, placed right before the user's latest message.
    This structural placement ensures the LLM treats memory facts as a recent
    context update, preventing it from anchoring on stale conversation history.
    """
    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        from ..core.memory import MemoryStore
        memory = MemoryStore.load()
        memory_injection = memory.get_system_prompt_injection()
        if memory_injection:
            memory_msg = {"role": "system", "content": memory_injection}
            # Insert right before the last message (user's latest input)
            if len(history) >= 2:
                history.insert(-1, memory_msg)
            else:
                history.insert(0, memory_msg)
        return system_prompt

    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        pass




class AutoTitleHook(AgentHook):
    """
    Monitors session length and fires a background job to summarize the 
    conversation into a short title string if the session lacks one.
    """
    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        return system_prompt

    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        messages = agent._session.messages()
        total_msgs = len(messages)
        
        # Fire titling logic after 2 or 4 messages have been exchanged
        if total_msgs in (2, 4) and not agent._session.summary:
            await self._generate_title(agent, messages)

    async def _generate_title(self, agent: BaseAgent, messages: List[Dict[str, str]]) -> None:
        if not messages:
            return
            
        title_prompt = (
            "Напиши ОЧЕНЬ КРАТКИЙ заголовок (3-5 слов, без кавычек и точек в конце) "
            "для этого диалога, отражающий его основную суть."
        )
        
        request = [
            {"role": "system", "content": "You are a helpful assistant that generates extremely concise titles."},
        ]
        request.extend(messages[:4])
        request.append({"role": "user", "content": title_prompt})
        
        response_parts = []
        try:
            async for chunk in agent._client.stream_message(request, temperature=0.3):
                response_parts.append(chunk)
                
            new_title = "".join(response_parts).strip().strip('"').strip("'")
            if new_title:
                agent._session.summary = new_title
        except Exception:
            pass
