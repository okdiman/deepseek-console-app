from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional

from ..core.client import DeepSeekClient, StreamMetrics
from ..core.session import ChatSession
from ..core.task_state import TaskStateMachine
from .strategies import get_strategy
from .hooks import AgentHook


@dataclass(frozen=True)
class AgentResult:
    content: str
    metrics: Optional[StreamMetrics]


class BaseAgent:
    """
    Pipeline-based abstract base class for AI agents.
    Executes the LLM request/response stream while delegating side-effects 
    (memory, tokens, auto-titles) to injected `AgentHook` instances.
    """
    
    SYSTEM_PROMPT = ""  # Must be overridden by subclasses

    def __init__(self, client: DeepSeekClient, session: ChatSession, hooks: Optional[List[AgentHook]] = None) -> None:
        self._client = client
        self._session = session
        self._hooks = hooks or []

    async def stream_reply(
        self, user_input: str, temperature: Optional[float] = None, top_p: Optional[float] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream the assistant reply. Executes pre-stream and post-stream hooks to manage side-effects.
        """
        self._session.add_user(user_input)

        context_strategy = get_strategy(self._client, self._session)
        await context_strategy.process_context(self.SYSTEM_PROMPT, user_input)

        system_msg = context_strategy.get_system_message_for_response()
        if system_msg:
            yield system_msg

        # 1. Apply pre-stream hooks to modify system prompt
        system_prompt = self.SYSTEM_PROMPT
        history_messages = context_strategy.build_history_messages(self.SYSTEM_PROMPT)

        for hook in self._hooks:
            system_prompt = await hook.before_stream(self, user_input, system_prompt, history_messages)

        # Load available MCP tools to optionally supply to the client
        from ..web.state import get_mcp_manager
        mcp_manager = get_mcp_manager()
        active_tools = mcp_manager.get_aggregated_tools()
        tools_payload = active_tools if active_tools else None

        # Re-build final request combining hooked prompt and user input
        history_messages[0] = {"role": "system", "content": system_prompt}

        # 1.5. Check for intercepts
        for hook in self._hooks:
            intercept = await hook.intercept_stream(self, user_input, history_messages)
            if intercept is not None:
                yield intercept
                self._session.add_assistant(intercept)
                return

        response_parts: List[str] = []
        try:
            # 2. Execute LLM stream
            async for chunk in self._client.stream_message(
                history_messages, temperature=temperature, top_p=top_p, tools=tools_payload
            ):
                import json
                try:
                    if chunk.startswith('{"__type__": "tool_call_start"'):
                        data = json.loads(chunk)
                        name = data.get("name", "unknown_tool")
                        yield f"\n\n⚙️ *Executing Tool `{name}`...*\n"
                        continue

                    # Check if the chunk is our special tool_calls payload
                    if chunk.startswith('{"__type__": "tool_calls"'):
                        data = json.loads(chunk)
                        
                        # We only keep the text immediately preceding the tool call to save
                        response = "".join(response_parts).strip()
                        if response:
                            self._session.add_assistant(response)
                        
                        tool_calls = data["calls"]
                        
                        # Append ONE assistant message containing all tool calls
                        self._session.add_tool_calls(tool_calls)
                        
                        # Execute tools matching the payload
                        for tc in tool_calls:
                            fn_name = tc["function"]["name"]
                            fn_args_str = tc["function"]["arguments"]
                            
                            try:
                                args_dict = json.loads(fn_args_str) if fn_args_str else {}
                            except json.JSONDecodeError:
                                args_dict = {}
                            
                            try:
                                result = await mcp_manager.execute_tool(fn_name, args_dict)
                                yield f"✅ *Tool returned result*\n\n"
                            except Exception as e:
                                result = f"Error executing tool: {e}"
                                yield f"❌ *Tool failed: {e}*\n\n"
                                
                            self._session.add_tool_result(
                                tool_call_id=tc["id"],
                                name=fn_name,
                                content=str(result)
                            )
                            
                        # Recurse with new messages to let the model generate the final response
                        new_history_messages = context_strategy.build_history_messages(system_prompt)
                        async for follow_up_chunk in self._client.stream_message(
                            new_history_messages, temperature=temperature, top_p=top_p, tools=tools_payload
                        ):
                             response_parts.append(follow_up_chunk)
                             yield follow_up_chunk
                        
                        return # End current outer stream since inner stream handled it

                except Exception as e:
                    import traceback
                    print(f"ERROR IN TOOL CALL RECURSION: {e}")
                    traceback.print_exc()
                    yield f"\n\n*(System Error during tool recursion: {e})*\n"
                    return
                
                response_parts.append(chunk)
                yield chunk
        finally:
            response = "".join(response_parts).strip()
            if response:
                self._session.add_assistant(response)
                
            # 3. Execute post-stream hooks for background tasks/logging
            for hook in self._hooks:
                await hook.after_stream(self, response)

    async def ask(
        self, user_input: str, temperature: Optional[float] = None, top_p: Optional[float] = None
    ) -> AgentResult:
        """
        Non-streaming helper that collects the full response using the Hook pipeline.
        """
        response_parts: List[str] = []
        async for chunk in self.stream_reply(user_input, temperature=temperature, top_p=top_p):
            response_parts.append(chunk)

        content = "".join(response_parts).strip()
        metrics = self._client.last_metrics()
        return AgentResult(
            content=content,
            metrics=metrics,
        )
