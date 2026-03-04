"""
Task State Machine — finite state automaton for structured task execution.

Phases: idle → planning → execution → validation → done
Supports pause/resume from any active phase.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class TaskPhase(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTION = "execution"
    VALIDATION = "validation"
    DONE = "done"
    PAUSED = "paused"


@dataclass
class TaskState:
    task: str = ""
    phase: TaskPhase = TaskPhase.IDLE
    previous_phase: Optional[TaskPhase] = None
    current_step: int = 0
    total_steps: int = 0
    plan: List[str] = field(default_factory=list)
    done: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "task": self.task,
            "phase": self.phase.value,
            "previous_phase": self.previous_phase.value if self.previous_phase else None,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "plan": list(self.plan),
            "done": list(self.done),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "TaskState":
        return cls(
            task=data.get("task", ""),
            phase=TaskPhase(data.get("phase", "idle")),
            previous_phase=TaskPhase(data["previous_phase"]) if data.get("previous_phase") else None,
            current_step=data.get("current_step", 0),
            total_steps=data.get("total_steps", 0),
            plan=data.get("plan", []),
            done=data.get("done", []),
        )


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""
    pass


class TaskStateMachine:
    """
    Finite state automaton for structured task execution.
    
    Transition rules:
        idle → planning          : start_task()
        planning → execution     : approve_plan()     👤 user
        execution → execution    : step_done()        🤖 agent
        execution → validation   : advance_to_validation()  🤖 agent
        validation → done        : complete()         👤 user
        validation → execution   : reject_validation()
        any active → paused      : pause()            👤 user
        paused → previous_phase  : resume()           👤 user
        any → idle               : reset()
    """

    _PAUSABLE = {TaskPhase.PLANNING, TaskPhase.EXECUTION, TaskPhase.VALIDATION}

    def __init__(self) -> None:
        self._state = TaskState()

    @property
    def state(self) -> TaskState:
        return self._state

    # ── Transitions ──────────────────────────────────────────────

    def start_task(self, goal: str) -> None:
        """Start a new task. idle → planning"""
        if self._state.phase != TaskPhase.IDLE:
            raise InvalidTransitionError(
                f"Cannot start task: current phase is '{self._state.phase.value}', expected 'idle'"
            )
        self._state = TaskState(
            task=goal,
            phase=TaskPhase.PLANNING,
        )

    def set_plan(self, steps: List[str]) -> None:
        """Agent proposes a plan during the planning phase."""
        if self._state.phase != TaskPhase.PLANNING:
            raise InvalidTransitionError(
                f"Cannot set plan: current phase is '{self._state.phase.value}', expected 'planning'"
            )
        self._state.plan = list(steps)
        self._state.total_steps = len(steps)
        self._state.current_step = 0

    def approve_plan(self) -> None:
        """User approves the plan. planning → execution"""
        if self._state.phase != TaskPhase.PLANNING:
            raise InvalidTransitionError(
                f"Cannot approve plan: current phase is '{self._state.phase.value}', expected 'planning'"
            )
        if not self._state.plan:
            raise InvalidTransitionError("Cannot approve plan: plan is empty")
        self._state.phase = TaskPhase.EXECUTION

    def step_done(self, step_description: str = "") -> None:
        """Agent marks current step as done and advances. execution → execution"""
        if self._state.phase != TaskPhase.EXECUTION:
            raise InvalidTransitionError(
                f"Cannot mark step done: current phase is '{self._state.phase.value}', expected 'execution'"
            )
        if self._state.current_step >= self._state.total_steps:
            raise InvalidTransitionError("All steps already completed")

        desc = step_description or (
            self._state.plan[self._state.current_step]
            if self._state.current_step < len(self._state.plan)
            else f"Step {self._state.current_step + 1}"
        )
        self._state.done.append(desc)
        self._state.current_step += 1

    def advance_to_validation(self) -> None:
        """Agent moves task to validation when all steps are done. execution → validation"""
        if self._state.phase != TaskPhase.EXECUTION:
            raise InvalidTransitionError(
                f"Cannot advance to validation: current phase is '{self._state.phase.value}', expected 'execution'"
            )
        self._state.phase = TaskPhase.VALIDATION

    def complete(self) -> None:
        """User confirms task is done. validation → done"""
        if self._state.phase != TaskPhase.VALIDATION:
            raise InvalidTransitionError(
                f"Cannot complete: current phase is '{self._state.phase.value}', expected 'validation'"
            )
        self._state.phase = TaskPhase.DONE

    def reject_validation(self) -> None:
        """Send task back to execution. validation → execution"""
        if self._state.phase != TaskPhase.VALIDATION:
            raise InvalidTransitionError(
                f"Cannot reject: current phase is '{self._state.phase.value}', expected 'validation'"
            )
        self._state.phase = TaskPhase.EXECUTION

    def pause(self) -> None:
        """Pause the task, remembering current phase. active → paused"""
        if self._state.phase not in self._PAUSABLE:
            raise InvalidTransitionError(
                f"Cannot pause: current phase '{self._state.phase.value}' is not pausable"
            )
        self._state.previous_phase = self._state.phase
        self._state.phase = TaskPhase.PAUSED

    def resume(self) -> None:
        """Resume from pause, restoring previous phase. paused → previous"""
        if self._state.phase != TaskPhase.PAUSED:
            raise InvalidTransitionError(
                f"Cannot resume: current phase is '{self._state.phase.value}', expected 'paused'"
            )
        if self._state.previous_phase is None:
            raise InvalidTransitionError("Cannot resume: no previous phase stored")
        self._state.phase = self._state.previous_phase
        self._state.previous_phase = None

    def reset(self) -> None:
        """Reset to idle. Can be called from any phase."""
        self._state = TaskState()

    # ── Prompt injection ─────────────────────────────────────────

    def get_prompt_injection(self) -> str:
        """Build a context block for the system prompt describing current task state."""
        s = self._state
        if s.phase == TaskPhase.IDLE:
            return ""

        lines = ["[ACTIVE TASK STATE]"]
        lines.append(f"Task: {s.task}")
        lines.append(f"Phase: {s.phase.value}")

        if s.phase == TaskPhase.PAUSED:
            lines.append(f"Paused from: {s.previous_phase.value if s.previous_phase else 'unknown'}")
            lines.append("The task is PAUSED. Wait for user to resume. Do NOT continue task work.")
            return "\n".join(lines)

        if s.plan:
            lines.append(f"Plan ({s.current_step}/{s.total_steps} done):")
            for i, step in enumerate(s.plan):
                marker = "✅" if i < s.current_step else ("👉" if i == s.current_step else "⬚")
                lines.append(f"  {marker} {i + 1}. {step}")

        if s.done:
            lines.append(f"Completed: {', '.join(s.done)}")

        if s.phase == TaskPhase.PLANNING:
            lines.append(
                "You are in PLANNING phase. Analyze the task, break it into concrete steps, "
                "and respond with a plan. Use the marker [PLAN_READY] at the END of your "
                "response when the plan is complete. Format steps as a numbered list."
            )
        elif s.phase == TaskPhase.EXECUTION:
            if s.current_step < s.total_steps:
                lines.append(
                    f"You are in EXECUTION phase. Work on step {s.current_step + 1}: "
                    f"\"{s.plan[s.current_step]}\".\n"
                    "IMPORTANT RULES:\n"
                    "- If you need clarification or user input to complete this step, "
                    "ask the question and do NOT include [STEP_DONE]. Wait for the answer.\n"
                    "- Include [STEP_DONE] ONLY after you have delivered the actual "
                    "result/output for this step (code, analysis, answer, etc.).\n"
                    "- After [STEP_DONE], continue with the next step automatically.\n"
                    "- When ALL steps are finished, include [READY_FOR_VALIDATION]."
                )
            else:
                lines.append(
                    "All planned steps are complete. Include [READY_FOR_VALIDATION] marker."
                )
        elif s.phase == TaskPhase.VALIDATION:
            lines.append(
                "You are in VALIDATION phase. Review all completed work, verify results, "
                "and summarize what was accomplished. The user will confirm completion."
            )
        elif s.phase == TaskPhase.DONE:
            lines.append("Task is DONE. Proceed with normal conversation.")

        return "\n".join(lines)

    # ── Persistence ──────────────────────────────────────────────

    def save(self, path: str) -> None:
        if not path:
            return
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    def load(self, path: str) -> None:
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._state = TaskState.from_dict(data)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            self._state = TaskState()
