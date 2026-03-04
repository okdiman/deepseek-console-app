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

# Pattern to extract numbered plan steps from agent response
_PLAN_STEP_RE = re.compile(r"^\s*\d+\.\s+(.+)$", re.MULTILINE)


class TaskStateHook(AgentHook):
    """
    Integrates TaskStateMachine into the agent pipeline.
    
    before_stream: injects current task context into the system prompt
    after_stream:  parses agent response for transition markers and applies them
    """

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

        injection = task_machine.get_prompt_injection()
        if injection:
            return system_prompt + "\n\n" + injection
        return system_prompt

    async def after_stream(self, agent: "BaseAgent", full_response: str) -> None:
        task_machine = getattr(agent, "_task_machine", None)
        if task_machine is None:
            return

        from ...core.task_state import TaskPhase, InvalidTransitionError

        state = task_machine.state

        # --- Planning phase: extract plan steps when agent signals readiness ---
        if state.phase == TaskPhase.PLANNING and _PLAN_READY_RE.search(full_response):
            steps = _PLAN_STEP_RE.findall(full_response)
            if steps:
                try:
                    task_machine.set_plan(steps)
                except InvalidTransitionError:
                    pass

        # --- Execution phase: handle step completion and validation readiness ---
        elif state.phase == TaskPhase.EXECUTION:
            if _STEP_DONE_RE.search(full_response):
                try:
                    task_machine.step_done()
                except InvalidTransitionError:
                    pass

            if _VALIDATION_RE.search(full_response):
                # Auto-complete remaining step before validation
                if state.current_step < state.total_steps:
                    try:
                        task_machine.step_done()
                    except InvalidTransitionError:
                        pass
                try:
                    task_machine.advance_to_validation()
                except InvalidTransitionError:
                    pass
            # Auto-advance when all steps are finished
            elif state.current_step >= state.total_steps and state.total_steps > 0:
                try:
                    task_machine.advance_to_validation()
                except InvalidTransitionError:
                    pass
