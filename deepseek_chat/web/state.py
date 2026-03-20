from __future__ import annotations

import dataclasses
import os
from typing import Dict

from ..agents.python_agent import PythonAgent
from ..agents.general_agent import GeneralAgent
from ..core.client import DeepSeekClient
from ..core.config import ClientConfig, load_config
from ..core.session import ChatSession
from ..core.task_state import TaskStateMachine
from ..core.mcp import MCPRegistry, MCPManager

_config: ClientConfig = load_config()

_web_context_path = os.getenv("DEEPSEEK_WEB_CONTEXT_PATH", "").strip()
if _web_context_path:
    _config = dataclasses.replace(_config, context_path=os.path.expanduser(_web_context_path))

_client = DeepSeekClient(_config)

_mcp_registry = MCPRegistry.load()
_mcp_manager = MCPManager(_mcp_registry)

_sessions: Dict[str, ChatSession] = {
    "default": ChatSession(max_messages=_config.context_max_messages)
}
_active_strategy: str = "default"

_task_machines: Dict[str, TaskStateMachine] = {}

_AGENT_REGISTRY = {
    "python": "Python Agent",
    "general": "General Agent",
}

def get_agent(agent_id: str, session_id: str = "default") -> PythonAgent | GeneralAgent:
    session = get_session(session_id)
    task_machine = get_task_machine(session_id)
    if agent_id == "python":
        return PythonAgent(_client, session, task_machine=task_machine, mcp_manager=_mcp_manager)
    return GeneralAgent(_client, session, task_machine=task_machine, mcp_manager=_mcp_manager)

_DEFAULT_AGENT_ID = "general"

if _config.persist_context:
    _sessions["default"].load(_config.context_path)

def get_config() -> ClientConfig:
    return _config


def get_client() -> DeepSeekClient:
    return _client


def get_session(session_id: str = "default") -> ChatSession:
    if session_id not in _sessions:
        _sessions[session_id] = ChatSession(max_messages=_config.context_max_messages)
    return _sessions[session_id]

def get_all_sessions() -> Dict[str, ChatSession]:
    return _sessions

def create_branch(parent_id: str, message_index: int, new_branch_id: str) -> None:
    parent_session = get_session(parent_id)
    _sessions[new_branch_id] = parent_session.clone(up_to_index=message_index)

def delete_session(session_id: str) -> None:
    if session_id in _sessions:
        del _sessions[session_id]
    _task_machines.pop(session_id, None)

def get_task_machine(session_id: str = "default") -> TaskStateMachine:
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
