import json
import os
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    id: str
    name: str
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class MCPRegistryStore(BaseModel):
    servers: List[MCPServerConfig] = Field(default_factory=list)


class MCPRegistry:
    """Manages persistence of MCP server configurations"""
    
    DEFAULT_PATH = os.path.expanduser("~/.deepseek_chat/mcp_servers.json")
    
    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "MCPRegistry":
        if not os.path.exists(path):
            # Create default configuration with our local server
            default_store = MCPRegistryStore(
                servers=[
                    MCPServerConfig(
                        id="local_demo",
                        name="Local Demo Server",
                        command="python",
                        args=["mcp_servers/demo_server.py"],
                        env={},
                        enabled=True
                    ),
                    MCPServerConfig(
                        id="scheduler",
                        name="Scheduler Server",
                        command="python",
                        args=["mcp_servers/scheduler/scheduler_server.py"],
                        env={},
                        enabled=True
                    )
                ]
            )
            registry = cls()
            registry._store = default_store
            registry.save(path)
            return registry
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                store = MCPRegistryStore(**data)
                registry = cls()
                registry._store = store
                return registry
        except Exception:
            registry = cls()
            registry._store = MCPRegistryStore(servers=[])
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

