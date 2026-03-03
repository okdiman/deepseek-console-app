from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, TYPE_CHECKING, Optional

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
    Injects the Explicit Memory Store into the Agent's system prompt prior to generation.
    """
    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        memory_injection = agent._session.memory.get_system_prompt_injection()
        if memory_injection:
            return system_prompt + f"\n\n{memory_injection}"
        return system_prompt

    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        pass


class TokenTrackerHook(AgentHook):
    """
    Tracks and stores the token sizes of requests, histories, and responses.
    This hook requires `count_messages_tokens` and `count_text_tokens`.
    """
    def __init__(self):
        self._last_stats = None
        self._request_count = None
        self._history_count = None

    def get_last_stats(self) -> Any:
        return self._last_stats

    async def before_stream(self, agent: BaseAgent, user_input: str, system_prompt: str, history: List[Dict[str, str]]) -> str:
        from ..core.token_counter import count_messages_tokens

        model = agent._client._config.model
        request_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        self._request_count = count_messages_tokens(request_messages, model=model)
        self._history_count = count_messages_tokens(history, model=model)
        return system_prompt

    async def after_stream(self, agent: BaseAgent, full_response: str) -> None:
        from ..core.token_counter import count_text_tokens
        from .base_agent import TokenStats

        if not self._request_count or not self._history_count:
            return

        model = agent._client._config.model
        response_count = count_text_tokens(full_response, model=model)

        self._last_stats = TokenStats(
            request=self._request_count,
            history=self._history_count,
            response=response_count,
        )


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
            print(f"[DEBUG] Generated new session title: '{new_title}'")
            if new_title:
                agent._session.summary = new_title
        except Exception as e:
            print(f"[DEBUG] Error generating session title: {e}")
