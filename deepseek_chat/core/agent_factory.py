"""
Standalone agent factory — no web-layer imports.

Use this to build an agent + MCPManager pair in any context
(console, background runner, tests) without depending on
deepseek_chat.web.state or FastAPI.
"""

from __future__ import annotations

from ..agents.background_agent import BackgroundAgent
from ..core.client import DeepSeekClient
from ..core.config import load_config
from ..core.mcp import MCPManager, MCPRegistry
from ..core.session import ChatSession


def build_background_agent(
    registry_path: str = MCPRegistry.DEFAULT_PATH,
) -> tuple[BackgroundAgent, MCPManager]:
    """
    Build a BackgroundAgent with its own MCPManager.

    The caller is responsible for:
      - calling await manager.start_all() before using the agent
      - calling await manager.stop_all() on shutdown

    Returns (agent, manager).
    """
    config = load_config()
    client = DeepSeekClient(config)
    session = ChatSession(max_messages=config.context_max_messages)
    registry = MCPRegistry.load(registry_path)
    manager = MCPManager(registry)
    agent = BackgroundAgent(client, session, mcp_manager=manager)
    return agent, manager


def build_client() -> "DeepSeekClient":
    """Build a standalone DeepSeekClient from the current config."""
    return DeepSeekClient(load_config())


def build_manager(registry_path: str = MCPRegistry.DEFAULT_PATH) -> MCPManager:
    """Build a standalone MCPManager. Caller must call await manager.start_all()."""
    return MCPManager(MCPRegistry.load(registry_path))
