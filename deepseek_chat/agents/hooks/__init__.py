"""
Agent Hooks package — each hook is a separate module.

Re-exports all hook classes for convenient importing:
    from .hooks import AgentHook, MemoryInjectionHook, UserProfileHook, AutoTitleHook, TaskStateHook, InvariantGuardHook
"""
from .base import AgentHook
from .memory_injection import MemoryInjectionHook
from .user_profile import UserProfileHook
from .auto_title import AutoTitleHook
from .task_state import TaskStateHook
from .invariant_guard import InvariantGuardHook
from .rag_hook import RagHook

__all__ = [
    "AgentHook",
    "MemoryInjectionHook",
    "UserProfileHook",
    "AutoTitleHook",
    "TaskStateHook",
    "InvariantGuardHook",
    "RagHook",
]
