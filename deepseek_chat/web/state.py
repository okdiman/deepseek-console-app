from __future__ import annotations

import asyncio
import dataclasses
import os
from typing import Dict

from ..agents.python_agent import PythonAgent
from ..agents.general_agent import GeneralAgent
from ..agents.dev_help_agent import DevHelpAgent
from ..agents.support_agent import SupportAgent
from ..agents.code_assistant_agent import CodeAssistantAgent
from ..core.client import DeepSeekClient
from ..core.config import ClientConfig, load_config
from ..core.session import ChatSession
from ..core.task_state import TaskStateMachine
from ..core.mcp import MCPRegistry, MCPManager

_startup_config: ClientConfig = load_config()

_web_context_path = os.getenv("DEEPSEEK_WEB_CONTEXT_PATH", "").strip()
if _web_context_path:
    _startup_config = dataclasses.replace(
        _startup_config, context_path=os.path.expanduser(_web_context_path)
    )

_OLLAMA_DEFAULTS = {
    "provider": "ollama",
    "api_key": "ollama",
    "api_url": "http://localhost:11434/v1/chat/completions",
    "models_url": "",
    "model": "qwen2.5:7b",
    "price_per_1k_prompt_usd": 0.0,
    "price_per_1k_completion_usd": 0.0,
}

# Per-session provider configs and cached clients.
# New sessions inherit the config of the "default" session at creation time.
_session_configs: Dict[str, ClientConfig] = {"default": _startup_config}
_session_clients: Dict[str, DeepSeekClient] = {"default": DeepSeekClient(_startup_config)}

_mcp_registry = MCPRegistry.load()
_mcp_manager = MCPManager(_mcp_registry)

_sessions: Dict[str, ChatSession] = {
    "default": ChatSession(max_messages=_startup_config.context_max_messages)
}
_active_strategy: str = "default"

_task_machines: Dict[str, TaskStateMachine] = {}

# Protects lazy-initialization of per-session objects.
# Without this, two concurrent requests for the same new session_id could
# both pass the `if session_id not in _sessions` check and create duplicate state.
_session_init_lock: asyncio.Lock | None = None


def _get_session_init_lock() -> asyncio.Lock:
    """Return the session init lock, creating it lazily inside the running loop."""
    global _session_init_lock
    if _session_init_lock is None:
        _session_init_lock = asyncio.Lock()
    return _session_init_lock


_AGENT_REGISTRY = {
    "python": "Python Agent",
    "general": "General Agent",
    "dev_help": "Dev Help Agent",
    "support": "Support Agent",
    "code_assistant": "Code Assistant",
}

_DEFAULT_AGENT_ID = "general"

if _startup_config.persist_context:
    _sessions["default"].load(_startup_config.context_path)


def get_config(session_id: str = "default") -> ClientConfig:
    return _session_configs.get(session_id, _startup_config)


def get_client(session_id: str = "default") -> DeepSeekClient:
    if session_id not in _session_clients:
        _session_clients[session_id] = DeepSeekClient(get_config(session_id))
    return _session_clients[session_id]


def set_provider(provider: str, session_id: str = "default") -> None:
    """Switch the LLM provider for a session. New sessions inherit from 'default'."""
    if provider == "ollama":
        new_config = dataclasses.replace(_startup_config, **_OLLAMA_DEFAULTS)
    elif provider == _startup_config.provider:
        new_config = _startup_config
    else:
        raise ValueError(f"Unknown provider '{provider}'. Supported: 'ollama', '{_startup_config.provider}'")
    _session_configs[session_id] = new_config
    _session_clients[session_id] = DeepSeekClient(new_config)


def get_agent(
    agent_id: str, session_id: str = "default"
) -> PythonAgent | GeneralAgent | DevHelpAgent | SupportAgent | CodeAssistantAgent:
    session = get_session(session_id)
    task_machine = get_task_machine(session_id)
    client = get_client(session_id)
    if agent_id == "python":
        return PythonAgent(client, session, task_machine=task_machine, mcp_manager=_mcp_manager)
    if agent_id == "dev_help":
        return DevHelpAgent(client, session, mcp_manager=_mcp_manager)
    if agent_id == "support":
        return SupportAgent(client, session, mcp_manager=_mcp_manager)
    if agent_id == "code_assistant":
        return CodeAssistantAgent(client, session, mcp_manager=_mcp_manager)
    return GeneralAgent(client, session, task_machine=task_machine, mcp_manager=_mcp_manager)


async def get_session_async(session_id: str = "default") -> ChatSession:
    """Async version — safe for concurrent requests on the same new session_id."""
    if session_id not in _sessions:
        async with _get_session_init_lock():
            # Double-checked locking: re-check after acquiring the lock.
            if session_id not in _sessions:
                inherited = _session_configs.get("default", _startup_config)
                _session_configs[session_id] = inherited
                _session_clients[session_id] = DeepSeekClient(inherited)
                _sessions[session_id] = ChatSession(max_messages=inherited.context_max_messages)
    return _sessions[session_id]


def get_session(session_id: str = "default") -> ChatSession:
    """Sync version — safe for single-threaded/startup use only."""
    if session_id not in _sessions:
        inherited = _session_configs.get("default", _startup_config)
        _session_configs[session_id] = inherited
        _session_clients[session_id] = DeepSeekClient(inherited)
        _sessions[session_id] = ChatSession(max_messages=inherited.context_max_messages)
    return _sessions[session_id]

def get_all_sessions() -> Dict[str, ChatSession]:
    return _sessions

def create_branch(parent_id: str, message_index: int, new_branch_id: str) -> None:
    parent_session = get_session(parent_id)
    _sessions[new_branch_id] = parent_session.clone(up_to_index=message_index)

def delete_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
    _task_machines.pop(session_id, None)
    _session_configs.pop(session_id, None)
    _session_clients.pop(session_id, None)

async def get_task_machine_async(session_id: str = "default") -> TaskStateMachine:
    """Async version — safe for concurrent requests on the same new session_id."""
    if session_id not in _task_machines:
        async with _get_session_init_lock():
            if session_id not in _task_machines:
                _task_machines[session_id] = TaskStateMachine()
    return _task_machines[session_id]


def get_task_machine(session_id: str = "default") -> TaskStateMachine:
    """Sync version — safe for single-threaded/startup use only."""
    if session_id not in _task_machines:
        _task_machines[session_id] = TaskStateMachine()
    return _task_machines[session_id]

def get_agent_registry() -> Dict[str, str]:
    return dict(_AGENT_REGISTRY)


def get_default_agent_id() -> str:
    return _DEFAULT_AGENT_ID


def get_default_agent_name() -> str:
    return _AGENT_REGISTRY[_DEFAULT_AGENT_ID]

def get_mcp_registry() -> MCPRegistry:
    return _mcp_registry

def get_mcp_manager() -> MCPManager:
    return _mcp_manager
