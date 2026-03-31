"""Tests for BaseAgent tool execution timeout (asyncio.wait_for)."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from deepseek_chat.agents.base_agent import BaseAgent
from deepseek_chat.core.config import ClientConfig


class _SimpleAgent(BaseAgent):
    SYSTEM_PROMPT = "test"


def _tool_calls_chunk(name: str, call_id: str = "call_1") -> str:
    return json.dumps({
        "__type__": "tool_calls",
        "calls": [{"id": call_id, "function": {"name": name, "arguments": "{}"}}],
    })


async def _collect(gen) -> list:
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return chunks


def _make_client(streams):
    """Client mock that returns streams[0] on first call, streams[1] on second, etc."""
    call_count = [0]

    async def _fake_stream(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        for chunk in streams[idx]:
            yield chunk

    client = MagicMock()
    client.stream_message = _fake_stream
    client.last_metrics.return_value = None
    # Minimal config so strategies.py doesn't blow up on MagicMock attribute access.
    client.config = MagicMock(spec=ClientConfig)
    client.config.compression_enabled = False
    client.config.compression_threshold = 10
    client.config.compression_keep = 4
    client.config.max_messages = 40
    return client


def _make_session():
    session = MagicMock()
    session.messages.return_value = []
    session.summary = ""
    session.facts = []
    session.add_user = MagicMock()
    session.add_assistant = MagicMock()
    session.add_tool_calls = MagicMock()
    session.add_tool_result = MagicMock()
    return session


@pytest.mark.asyncio
async def test_tool_timeout_yields_error_chunk():
    """A hung MCP tool must time out in ≤ 0.1 s and yield an error chunk."""
    # First LLM call emits a tool_calls chunk; second call returns the final answer.
    client = _make_client([
        [_tool_calls_chunk("srv__slow")],   # first stream: triggers tool call
        ["final answer"],                    # second stream: after tool result
    ])
    session = _make_session()

    async def _hung_tool(name, args):
        await asyncio.sleep(999)

    mcp_manager = MagicMock()
    mcp_manager.execute_tool = _hung_tool
    mcp_manager.get_aggregated_tools.return_value = [
        {"type": "function", "function": {"name": "srv__slow", "description": "", "parameters": {}}}
    ]

    agent = _SimpleAgent(client, session, mcp_manager=mcp_manager)

    import deepseek_chat.agents.base_agent as ba_mod
    original_wait_for = ba_mod.asyncio.wait_for

    async def _fast_wait_for(coro, timeout):
        # Override to use 0.05s so the test doesn't actually wait 30s.
        return await original_wait_for(coro, timeout=0.05)

    ba_mod.asyncio.wait_for = _fast_wait_for
    try:
        chunks = await _collect(agent.stream_reply("hi"))
    finally:
        ba_mod.asyncio.wait_for = original_wait_for

    combined = "".join(chunks)
    assert "timed out" in combined.lower() or "timeout" in combined.lower()
