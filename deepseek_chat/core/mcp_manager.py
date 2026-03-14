import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
import httpx

from .mcp_registry import MCPRegistry, MCPServerConfig

logger = logging.getLogger(__name__)

_READY_POLL_INTERVAL = 0.1   # seconds between readiness checks
_READY_TIMEOUT = 10.0        # max seconds to wait for a server to initialize
_RESTART_DELAY = 3.0         # seconds before retrying after a crash
_MAX_RESTARTS = 5            # give up after this many consecutive crashes


class MCPManager:
    """Manages the lifecycle of multiple MCP server sessions."""

    def __init__(self, registry: MCPRegistry):
        self._registry = registry
        self._sessions: Dict[str, ClientSession] = {}
        self._server_tasks: Dict[str, asyncio.Task] = {}
        self._shutdown_events: Dict[str, asyncio.Event] = {}
        self._aggregated_tools: List[Dict[str, Any]] = []
        self._tool_routes: Dict[str, str] = {}
        self._original_tool_names: Dict[str, str] = {}

    async def start_all(self) -> None:
        """Start all enabled servers in the registry."""
        for config in self._registry.get_all():
            if config.enabled:
                await self.start_server(config)
        await self._refresh_tools()

    async def _run_server_task(self, config: MCPServerConfig, shutdown_event: asyncio.Event) -> None:
        """
        Background task that holds the MCP connection open.
        Supports stdio, sse, and streamable_http transports.
        Auto-restarts on crash up to _MAX_RESTARTS consecutive times.
        Stops cleanly when shutdown_event is set.
        """
        consecutive_crashes = 0

        while not shutdown_event.is_set():
            try:
                async with self._open_transport(config) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self._sessions[config.id] = session
                        consecutive_crashes = 0
                        logger.info("MCP server '%s' ready (transport=%s).", config.id, config.transport)
                        await self._refresh_tools()

                        await shutdown_event.wait()
                        break

            except asyncio.CancelledError:
                break

            except Exception as e:
                self._sessions.pop(config.id, None)
                if shutdown_event.is_set():
                    break

                consecutive_crashes += 1
                logger.error(
                    "MCP server '%s' crashed (%d/%d): %s",
                    config.id, consecutive_crashes, _MAX_RESTARTS, e,
                )

                if consecutive_crashes >= _MAX_RESTARTS:
                    logger.error("MCP server '%s': max restarts exceeded, giving up.", config.id)
                    break

                logger.info("Restarting MCP server '%s' in %.0fs...", config.id, _RESTART_DELAY)
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=_RESTART_DELAY)
                    break
                except asyncio.TimeoutError:
                    pass

        self._sessions.pop(config.id, None)
        await self._refresh_tools()
        logger.info("MCP server task for '%s' exited.", config.id)

    @asynccontextmanager
    async def _open_transport(self, config: MCPServerConfig):
        """Async context manager yielding (read, write) for the configured transport."""
        if config.transport == "sse":
            if not config.url:
                raise ValueError(f"MCP server '{config.id}': transport=sse requires a url")
            async with sse_client(config.url, headers=config.headers or None) as (read, write):
                yield read, write
        elif config.transport == "streamable_http":
            if not config.url:
                raise ValueError(f"MCP server '{config.id}': transport=streamable_http requires a url")
            http_client = httpx.AsyncClient(headers=config.headers or {}, timeout=30)
            async with http_client:
                async with streamable_http_client(config.url, http_client=http_client) as (read, write, _):
                    yield read, write
        else:
            # stdio (default)
            if not config.command:
                raise ValueError(f"MCP server '{config.id}': transport=stdio requires a command")
            server_params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )
            async with stdio_client(server_params) as (read, write):
                yield read, write

    async def start_server(self, config: MCPServerConfig) -> bool:
        """Start a single MCP server and wait until it is ready."""
        if config.id in self._server_tasks:
            logger.warning("Server '%s' is already running.", config.id)
            return True

        endpoint = config.url if config.transport in ("sse", "streamable_http") else f"{config.command} {' '.join(config.args)}"
        logger.info("Starting MCP server: %s [%s] %s", config.name, config.transport, endpoint)

        shutdown_event = asyncio.Event()
        task = asyncio.create_task(self._run_server_task(config, shutdown_event))
        self._shutdown_events[config.id] = shutdown_event
        self._server_tasks[config.id] = task

        # Wait until the session is populated (or the task fails / timeout reached)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _READY_TIMEOUT
        while loop.time() < deadline:
            if config.id in self._sessions:
                return True
            if task.done():
                logger.warning("MCP server '%s' task ended before becoming ready.", config.id)
                return False
            await asyncio.sleep(_READY_POLL_INTERVAL)

        logger.warning("MCP server '%s' did not become ready within %.0fs.", config.id, _READY_TIMEOUT)
        return False

    async def stop_server(self, server_id: str) -> bool:
        """Stop a specific MCP server."""
        if server_id not in self._server_tasks:
            return False

        logger.info("Stopping MCP server: %s", server_id)
        event = self._shutdown_events.pop(server_id, None)
        if event:
            event.set()

        task = self._server_tasks.pop(server_id, None)
        if task:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()

        self._sessions.pop(server_id, None)
        await self._refresh_tools()
        return True

    async def stop_all(self) -> None:
        """Stop all running servers."""
        for sid in list(self._server_tasks.keys()):
            await self.stop_server(sid)
        self._aggregated_tools = []
        self._tool_routes = {}
        self._original_tool_names = {}

    async def reload_server(self, server_id: str) -> None:
        """Reload a server (e.g. after config change or toggle)."""
        await self.stop_server(server_id)
        config = self._registry.get_server(server_id)
        if config and config.enabled:
            await self.start_server(config)
        await self._refresh_tools()

    async def _refresh_tools(self) -> None:
        """Query all active sessions and rebuild the aggregated tool list."""
        self._aggregated_tools = []
        self._tool_routes = {}
        self._original_tool_names = {}

        for server_id, session in list(self._sessions.items()):
            try:
                response = await session.list_tools()
                for tool in response.tools:
                    prefixed = f"{server_id}__{tool.name}"
                    self._aggregated_tools.append({
                        "type": "function",
                        "function": {
                            "name": prefixed,
                            "description": tool.description or "",
                            "parameters": tool.inputSchema,
                        },
                    })
                    self._tool_routes[prefixed] = server_id
                    self._original_tool_names[prefixed] = tool.name
            except Exception as e:
                logger.error("Error fetching tools from server '%s': %s", server_id, e)

    def get_aggregated_tools(self) -> List[Dict[str, Any]]:
        return self._aggregated_tools

    async def execute_tool(self, tool_name: str, arguments: dict) -> Any:
        """Route and execute a tool call."""
        if tool_name not in self._tool_routes:
            raise ValueError(f"Unknown tool: {tool_name}")

        server_id = self._tool_routes[tool_name]
        original_name = self._original_tool_names[tool_name]
        session = self._sessions.get(server_id)
        if not session:
            raise RuntimeError(f"MCP server '{server_id}' is not running.")

        logger.info("Executing tool '%s' on server '%s'", original_name, server_id)
        response = await session.call_tool(original_name, arguments)

        if not response.content:
            return ""

        texts = []
        for block in response.content:
            if hasattr(block, "text"):
                texts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                texts.append(block["text"])
            else:
                texts.append(str(block))
        return "\n".join(texts)
