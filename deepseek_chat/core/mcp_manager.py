import asyncio
import logging
from typing import Dict, List, Optional, Any
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .mcp_registry import MCPRegistry, MCPServerConfig

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages the lifecycle of multiple MCP server sessions."""

    def __init__(self, registry: MCPRegistry):
        self._registry = registry
        # Map of server_id -> ClientSession
        self._sessions: Dict[str, ClientSession] = {}
        # Map of server_id -> Task (the background task running the context managers)
        self._server_tasks: Dict[str, asyncio.Task] = {}
        # Map of server_id -> asyncio.Event (used to signal the task to shutdown)
        self._shutdown_events: Dict[str, asyncio.Event] = {}
        # Cached list of aggregated tools across all active servers
        self._aggregated_tools: List[Dict[str, Any]] = []
        # Mapping from prefixed tool name -> server_id to route executions correctly
        self._tool_routes: Dict[str, str] = {}
        
        # Original tool names (prefixed_name -> original name)
        self._original_tool_names: Dict[str, str] = {}

    async def start_all(self) -> None:
        """Start all enabled servers in the registry."""
        configs = self._registry.get_all()
        for config in configs:
            if config.enabled:
                await self.start_server(config)
                
        await self._refresh_tools()

    async def _run_server_task(self, config: MCPServerConfig, shutdown_event: asyncio.Event) -> None:
        """
        Background task that holds the AsyncContextManagers open.
        This avoids 'cancel scope' errors that happen when using AsyncExitStack across different tasks.
        """
        env = config.env if config.env else None
        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=env
        )
        
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._sessions[config.id] = session
                    logger.info(f"MCP Server {config.id} initialized successfully.")
                    
                    # Wait until we are told to shutdown via the event
                    await shutdown_event.wait()
                    
        except asyncio.CancelledError:
            logger.info(f"MCP Server {config.id} task cancelled.")
        except Exception as e:
            logger.error(f"MCP Server {config.id} crashed: {e}")
        finally:
            self._sessions.pop(config.id, None)

    async def start_server(self, config: MCPServerConfig) -> bool:
        """Start a single MCP server given its configuration."""
        if config.id in self._server_tasks:
            logger.warning(f"Server {config.id} is already running.")
            return True

        logger.info(f"Starting MCP Server Task: {config.name} ({config.command} {' '.join(config.args)})")
        
        shutdown_event = asyncio.Event()
        task = asyncio.create_task(self._run_server_task(config, shutdown_event))
        
        self._shutdown_events[config.id] = shutdown_event
        self._server_tasks[config.id] = task
        
        # Give it a moment to initialize before we try to list tools
        # A more robust way would be a Ready event, but a short sleep is typically enough for local Stdio
        await asyncio.sleep(1.0)
        
        return True

    async def stop_server(self, server_id: str) -> bool:
        """Stop a specific MCP server."""
        if server_id not in self._server_tasks:
            return False
            
        try:
            logger.info(f"Stopping MCP Server Task: {server_id}")
            # Signal the background task to exit its context managers cleanly
            event = self._shutdown_events.pop(server_id, None)
            if event:
                event.set()
                
            task = self._server_tasks.pop(server_id, None)
            if task:
                # Wait for the task to finish cleanup with a timeout
                try:
                    await asyncio.wait_for(task, timeout=3.0)
                except asyncio.TimeoutError:
                    task.cancel()
                    
            self._sessions.pop(server_id, None)
            
            # Re-aggregate tools since a server was removed
            await self._refresh_tools()
            
            return True
        except Exception as e:
            logger.error(f"Error stopping MCP server {server_id}: {e}")
            return False

    async def stop_all(self) -> None:
        """Stop all running servers."""
        server_ids = list(self._server_tasks.keys())
        for sid in server_ids:
            await self.stop_server(sid)
            
        self._aggregated_tools = []
        self._tool_routes = {}
        self._original_tool_names = {}

    async def reload_server(self, server_id: str) -> None:
        """Reload a specific server (e.g. after config change or toggle)."""
        # Stop if currently running
        await self.stop_server(server_id)
        
        # Check if it should be restarted
        config = self._registry.get_server(server_id)
        if config and config.enabled:
            await self.start_server(config)
            
        # Re-fetch all tools since the landscape changed
        await self._refresh_tools()

    async def _refresh_tools(self) -> None:
        """Query all active servers and aggregate their tools."""
        self._aggregated_tools = []
        self._tool_routes = {}
        self._original_tool_names = {}
        
        for server_id, session in self._sessions.items():
            try:
                # Ask the server what tools it provides
                response = await session.list_tools()
                for tool in response.tools:
                    # To avoid collisions between different servers that might both have a 'search' tool,
                    # we prefix the tool name globally for the LLM.
                    prefixed_name = f"{server_id}__{tool.name}"
                    
                    # Convert MCP Type to Standard dict for LLM payload
                    # Note: You might need to adjust formatting depending on the specific API shape
                    # the LLM expects, but standard OpenAI format is usually expected.
                    tool_def = {
                        "type": "function",
                        "function": {
                            "name": prefixed_name,
                            "description": tool.description or "",
                            "parameters": tool.inputSchema
                        }
                    }
                    self._aggregated_tools.append(tool_def)
                    self._tool_routes[prefixed_name] = server_id
                    self._original_tool_names[prefixed_name] = tool.name
                    
            except Exception as e:
                logger.error(f"Error fetching tools from server {server_id}: {e}")

    def get_aggregated_tools(self) -> List[Dict[str, Any]]:
        """Return the list of all tools available across all running servers."""
        return self._aggregated_tools

    async def execute_tool(self, tool_name: str, arguments: dict) -> Any:
        """Execute a tool routing it to the correct server session."""
        if tool_name not in self._tool_routes:
            raise ValueError(f"Unknown tool: {tool_name}")
            
        server_id = self._tool_routes[tool_name]
        original_name = self._original_tool_names[tool_name]
        
        session = self._sessions.get(server_id)
        if not session:
            raise RuntimeError(f"Server {server_id} is not running.")
            
        # Call the tool via the MCP SDK, using the ORIGINAL name, not the prefixed one
        logger.info(f"Executing tool {original_name} on server {server_id}")
        response = await session.call_tool(original_name, arguments)
        
        # Extract the tool output from the response (MCP responses can have multiple content blocks)
        if not response.content:
            return ""
            
        # Simplistic extraction assuming text content for now
        texts = []
        for content_block in response.content:
            if hasattr(content_block, "text"):
                texts.append(content_block.text)
            elif isinstance(content_block, dict) and "text" in content_block:
                texts.append(content_block["text"])
            else:
                texts.append(str(content_block))
                
        return "\n".join(texts)
