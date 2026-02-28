from __future__ import annotations

import os
from typing import Dict

from ..agents.android_agent import AndroidAgent
from ..agents.general_agent import GeneralAgent
from ..core.client import DeepSeekClient
from ..core.config import ClientConfig, load_config
from ..core.session import ChatSession

_config: ClientConfig = load_config()

_web_context_path = os.getenv("DEEPSEEK_WEB_CONTEXT_PATH", "").strip()
if _web_context_path:
    _config = _config.__class__(  # type: ignore[misc]
        provider=_config.provider,
        api_key=_config.api_key,
        api_url=_config.api_url,
        models_url=_config.models_url,
        model=_config.model,
        max_tokens=_config.max_tokens,
        read_timeout_seconds=_config.read_timeout_seconds,
        price_per_1k_prompt_usd=_config.price_per_1k_prompt_usd,
        price_per_1k_completion_usd=_config.price_per_1k_completion_usd,
        persist_context=_config.persist_context,
        context_path=os.path.expanduser(_web_context_path),
        context_max_messages=_config.context_max_messages,
        compression_enabled=_config.compression_enabled,
        compression_threshold=_config.compression_threshold,
        compression_keep=_config.compression_keep,
        optional_params=_config.optional_params,
    )

_client = DeepSeekClient(_config)

_sessions: Dict[str, ChatSession] = {
    "default": ChatSession(max_messages=_config.context_max_messages)
}
_active_strategy: str = "default"

_AGENT_REGISTRY = {
    "android": "Android Agent",
    "general": "General Agent",
}

def get_agent(agent_id: str, session_id: str = "default") -> AndroidAgent | GeneralAgent:
    session = get_session(session_id)
    if agent_id == "android":
        return AndroidAgent(_client, session)
    return GeneralAgent(_client, session)

_DEFAULT_AGENT_ID = "general"

_session_cost_usd = 0.0

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

def get_agent_registry() -> Dict[str, str]:
    return dict(_AGENT_REGISTRY)


def get_default_agent_id() -> str:
    return _DEFAULT_AGENT_ID


def get_default_agent_name() -> str:
    return _AGENT_REGISTRY[_DEFAULT_AGENT_ID]


def get_session_cost_usd() -> float:
    return _session_cost_usd


def set_session_cost_usd(value: float) -> None:
    global _session_cost_usd
    _session_cost_usd = value


def add_session_cost_usd(amount: float) -> None:
    global _session_cost_usd
    _session_cost_usd += amount


def reset_session_cost_usd() -> None:
    global _session_cost_usd
    _session_cost_usd = 0.0
