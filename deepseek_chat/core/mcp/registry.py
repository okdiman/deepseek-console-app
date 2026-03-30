import json
import os
import sys
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from deepseek_chat.core.paths import DATA_DIR

_PYTHON = sys.executable


class MCPServerConfig(BaseModel):
    id: str
    name: str
    # stdio transport fields
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    # http/sse transport fields
    transport: str = "stdio"   # "stdio" | "sse" | "streamable_http"
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class MCPRegistryStore(BaseModel):
    servers: List[MCPServerConfig] = Field(default_factory=list)


_BUILTIN_SERVERS: List[MCPServerConfig] = [
    MCPServerConfig(
        id="local_demo",
        name="Local Demo Server",
        command=_PYTHON,
        args=["mcp_servers/demo_server.py"],
        env={},
        enabled=True,
    ),
    MCPServerConfig(
        id="scheduler",
        name="Scheduler Server",
        command=_PYTHON,
        args=["mcp_servers/scheduler/scheduler_server.py"],
        env={},
        enabled=True,
    ),
    MCPServerConfig(
        id="pipeline",
        name="Pipeline Server",
        command=_PYTHON,
        args=["mcp_servers/pipeline_server.py"],
        env={},
        enabled=True,
    ),
    MCPServerConfig(
        id="git_project",
        name="Git Project Server",
        command=_PYTHON,
        args=["mcp_servers/git_server.py"],
        env={},
        enabled=True,
    ),
    MCPServerConfig(
        id="filesystem",
        name="Filesystem Server",
        command=_PYTHON,
        args=["mcp_servers/filesystem_server.py"],
        env={},
        enabled=True,
    ),
]


class MCPRegistry:
    """Manages persistence of MCP server configurations"""

    DEFAULT_PATH = str(DATA_DIR / "mcp_servers.json")

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "MCPRegistry":
        if not os.path.exists(path):
            registry = cls()
            registry._store = MCPRegistryStore(servers=list(_BUILTIN_SERVERS))
            registry.save(path)
            return registry

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                store = MCPRegistryStore(**data)
                registry = cls()
                registry._store = store
        except Exception:
            registry = cls()
            registry._store = MCPRegistryStore(servers=[])

        # Ensure all built-in servers are present; also sync command/args in case the
        # Python interpreter path changed (e.g. after re-creating the virtualenv).
        builtin_map = {b.id: b for b in _BUILTIN_SERVERS}
        changed = False
        existing_ids = {s.id for s in registry._store.servers}
        for bid, builtin in builtin_map.items():
            if bid not in existing_ids:
                registry._store.servers.append(builtin)
                changed = True
            else:
                # Update command/args for existing builtins (preserves enabled/env/etc.)
                for s in registry._store.servers:
                    if s.id == bid and (s.command != builtin.command or s.args != builtin.args):
                        s.command = builtin.command
                        s.args = builtin.args
                        changed = True
        if changed:
            registry.save(path)

        return registry

    def __init__(self) -> None:
        self._store = MCPRegistryStore()

    def get_all(self) -> List[MCPServerConfig]:
        return self._store.servers

    def get_server(self, server_id: str) -> Optional[MCPServerConfig]:
        for s in self._store.servers:
            if s.id == server_id:
                return s
        return None

    def add_server(self, config: MCPServerConfig) -> None:
        # Replace if exists
        for i, s in enumerate(self._store.servers):
            if s.id == config.id:
                self._store.servers[i] = config
                return
        self._store.servers.append(config)

    def remove_server(self, server_id: str) -> bool:
        initial_len = len(self._store.servers)
        self._store.servers = [s for s in self._store.servers if s.id != server_id]
        return len(self._store.servers) < initial_len

    def save(self, path: str = DEFAULT_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._store.model_dump_json(indent=2))
