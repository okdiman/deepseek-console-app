"""
TaskStateHook — injects task state context into the system prompt
and auto-detects phase transitions from agent responses.
"""
from __future__ import annotations

import re
from typing import Dict, List, TYPE_CHECKING

from .base import AgentHook

if TYPE_CHECKING:
    from ..base_agent import BaseAgent


# Markers the agent includes in responses to signal transitions
_PLAN_READY_RE = re.compile(r"\[PLAN_READY\]", re.IGNORECASE)
_STEP_DONE_RE = re.compile(r"\[STEP_DONE\]", re.IGNORECASE)
_VALIDATION_RE = re.compile(r"\[READY_FOR_VALIDATION\]", re.IGNORECASE)
_REVERT_RE = re.compile(r"\[REVERT_TO_STEP:\s*(\d+)\]", re.IGNORECASE)
_RESUME_RE = re.compile(r"\[RESUME_TASK\]", re.IGNORECASE)

# Pattern to extract numbered plan steps from agent response
_PLAN_STEP_RE = re.compile(r"^\s*\d+\.\s+(.+)$", re.MULTILINE)


class TaskStateHook(AgentHook):
    """
    Integrates TaskStateMachine into the agent pipeline.
    
    before_stream: injects current task context into the system prompt
    after_stream:  parses agent response for transition markers and applies them
    """

    async def intercept_stream(
        self, agent: "BaseAgent", user_input: str, history: List[Dict[str, str]]
    ) -> Optional[str]:
        # We no longer hard-intercept here because the user needs to be able 
        # to converse with the agent to refine the plan before approving it.
        # The FSM already rejects any step_done attempts while in PLANNING.
        return None

    async def before_stream(
        self,
        agent: "BaseAgent",
        user_input: str,
        system_prompt: str,
        history: List[Dict[str, str]],
    ) -> str:
        task_machine = getattr(agent, "_task_machine", None)
        if task_machine is None:
            return system_prompt

        from ...core.task_state import TaskPhase

        injection = task_machine.get_prompt_injection()
        if injection:
            system_prompt = system_prompt + "\n\n" + injection

        state = task_machine.state
        if (state.phase == TaskPhase.PLANNING
                and state.plan
                and len(history) >= 2):
            gate_msg = {
                "role": "system",
                "content": (
                    "[SYSTEM GATE] The task plan has NOT been approved yet. "
                    "Phase is PLANNING. You are PROHIBITED from executing any steps or writing code. "
                    "You MAY discuss or refine the plan if the user asks, but you MUST NOT start execution. "
                    "If the user asks you to start/proceed without approving the plan, you must reply EXACTLY: "
                    "'Я не могу приступить к реализации, пока план не утверждён. Пожалуйста, "
                    "нажмите кнопку ✓ Approve Plan в панели задачи.' "
                    "Otherwise, respond to their refinements normally but end by asking them to approve the plan."
                ),
            }
            # Insert right before the last message (the current user message)
            history.insert(-1, gate_msg)

        return system_prompt

    async def after_stream(self, agent: "BaseAgent", full_response: str) -> None:
        task_machine = getattr(agent, "_task_machine", None)
        if task_machine is None:
            return

        from ...core.task_state import TaskPhase, InvalidTransitionError

        state = task_machine.state

        # --- Planning phase: extract plan steps when agent proposes a plan ---
        if state.phase == TaskPhase.PLANNING:
            # Always try to extract steps during planning, so the UI updates
            # as the agent refines the plan, even if they don't say [PLAN_READY] yet.
            steps = _PLAN_STEP_RE.findall(full_response)
            if steps:
                try:
                    task_machine.set_plan(steps)
                except InvalidTransitionError:
                    pass

        # --- Allow AI to auto-resume if requested by user ---
        if state.phase == TaskPhase.PAUSED:
            if _RESUME_RE.search(full_response):
                try:
                    task_machine.resume()
                except InvalidTransitionError:
                    pass
            return  # If we were paused, we don't process other execution markers

        # If streaming.py already processed live markers for the UI, don't double count
        if getattr(agent, "_skip_after_stream_markers", False):
            # Clean up the flag for future runs
            agent._skip_after_stream_markers = False
            return

        # --- Process ALL execution/validation markers sequentially in the order they appear ---
        if state.phase in {TaskPhase.EXECUTION, TaskPhase.VALIDATION}:
            # Find all markers and their positions
            matches = []
            for m in _STEP_DONE_RE.finditer(full_response):
                matches.append((m.start(), "STEP_DONE", None))
            for m in _VALIDATION_RE.finditer(full_response):
                matches.append((m.start(), "VALIDATION", None))
            for m in _REVERT_RE.finditer(full_response):
                matches.append((m.start(), "REVERT", int(m.group(1)) - 1))
            
            # Sort by position in text so we apply them chronologically
            matches.sort(key=lambda x: x[0])
            
            for _, marker_type, val in matches:
                current_phase = task_machine.state.phase
                
                if marker_type == "STEP_DONE" and current_phase == TaskPhase.EXECUTION:
                    try:
                        task_machine.step_done()
                    except InvalidTransitionError:
                        pass
                        
                elif marker_type == "VALIDATION" and current_phase == TaskPhase.EXECUTION:
                    # Auto-complete remaining step before validation if needed
                    if task_machine.state.current_step < task_machine.state.total_steps:
                        try:
                            task_machine.step_done()
                        except InvalidTransitionError:
                            pass
                    try:
                        task_machine.advance_to_validation()
                    except InvalidTransitionError:
                        pass
                        
                elif marker_type == "REVERT" and current_phase in {TaskPhase.EXECUTION, TaskPhase.VALIDATION}:
                    try:
                        task_machine.revert_to_step(val)
                    except InvalidTransitionError:
                        pass
