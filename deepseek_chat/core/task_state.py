"""
Task State Machine — finite state automaton for structured task execution.

Phases: idle → planning → execution → validation → done
Supports pause/resume from any active phase.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Set


class TaskPhase(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTION = "execution"
    VALIDATION = "validation"
    DONE = "done"
    PAUSED = "paused"


# ── Declarative transition map ───────────────────────────────
# Each key lists the phases reachable from it via normal transitions.
# PAUSED is special: its allowed targets are resolved dynamically
# from ``previous_phase`` (i.e. resume restores the phase before pause).

ALLOWED_TRANSITIONS: Dict[TaskPhase, Set[TaskPhase]] = {
    TaskPhase.IDLE:       {TaskPhase.PLANNING},
    TaskPhase.PLANNING:   {TaskPhase.EXECUTION, TaskPhase.PAUSED},
    TaskPhase.EXECUTION:  {TaskPhase.EXECUTION, TaskPhase.VALIDATION, TaskPhase.PAUSED},
    TaskPhase.VALIDATION: {TaskPhase.DONE, TaskPhase.EXECUTION, TaskPhase.PAUSED},
    TaskPhase.DONE:       {TaskPhase.IDLE},           # only via reset
    TaskPhase.PAUSED:     set(),                       # dynamic — uses previous_phase
}


@dataclass
class TransitionRecord:
    from_phase: str
    to_phase: str
    timestamp: str

    def to_dict(self) -> Dict:
        return {"from": self.from_phase, "to": self.to_phase, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: Dict) -> "TransitionRecord":
        return cls(
            from_phase=data.get("from", ""),
            to_phase=data.get("to", ""),
            timestamp=data.get("timestamp", ""),
        )


@dataclass
class TaskState:
    task: str = ""
    phase: TaskPhase = TaskPhase.IDLE
    previous_phase: Optional[TaskPhase] = None
    current_step: int = 0
    total_steps: int = 0
    plan: List[str] = field(default_factory=list)
    done: List[str] = field(default_factory=list)
    transition_log: List[TransitionRecord] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "task": self.task,
            "phase": self.phase.value,
            "previous_phase": self.previous_phase.value if self.previous_phase else None,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "plan": list(self.plan),
            "done": list(self.done),
            "transition_log": [r.to_dict() for r in self.transition_log],
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
            transition_log=[
                TransitionRecord.from_dict(r) for r in data.get("transition_log", [])
            ],
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

    # ── Transition helpers ───────────────────────────────────

    def _validate_transition(self, target: TaskPhase) -> None:
        """Raise InvalidTransitionError if transition from current phase to *target* is forbidden."""
        current = self._state.phase

        # PAUSED has dynamic targets
        if current == TaskPhase.PAUSED:
            if self._state.previous_phase is not None and target == self._state.previous_phase:
                return
            raise InvalidTransitionError(
                f"Cannot transition from '{current.value}' to '{target.value}'. "
                f"Allowed: resume to '{self._state.previous_phase.value if self._state.previous_phase else 'unknown'}'"
            )

        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if target not in allowed:
            allowed_names = sorted(p.value for p in allowed) if allowed else ["none"]
            raise InvalidTransitionError(
                f"Cannot transition from '{current.value}' to '{target.value}'. "
                f"Allowed transitions: {', '.join(allowed_names)}"
            )

    def _record_transition(self, from_phase: TaskPhase, to_phase: TaskPhase) -> None:
        """Append a record to the transition log."""
        self._state.transition_log.append(TransitionRecord(
            from_phase=from_phase.value,
            to_phase=to_phase.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    def get_allowed_transitions(self) -> List[str]:
        """Return a list of phase names reachable from the current phase."""
        current = self._state.phase
        if current == TaskPhase.PAUSED:
            if self._state.previous_phase is not None:
                return [self._state.previous_phase.value]
            return []
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        return sorted(p.value for p in allowed)

    # ── Transitions ──────────────────────────────────────────────

    def start_task(self, goal: str) -> None:
        """Start a new task. idle → planning"""
        self._validate_transition(TaskPhase.PLANNING)
        old = self._state.phase
        self._state = TaskState(
            task=goal,
            phase=TaskPhase.PLANNING,
        )
        self._record_transition(old, TaskPhase.PLANNING)

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
                f"Cannot approve plan: current phase is '{self._state.phase.value}', expected 'planning'. "
                f"Allowed transitions: {', '.join(self.get_allowed_transitions())}"
            )
        if not self._state.plan:
            raise InvalidTransitionError("Cannot approve plan: plan is empty")
        old = self._state.phase
        self._state.phase = TaskPhase.EXECUTION
        self._record_transition(old, TaskPhase.EXECUTION)

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
        
        # Automatically transition if this was the last step
        if self._state.current_step >= self._state.total_steps and self._state.total_steps > 0:
            if self._state.phase == TaskPhase.EXECUTION:
                self.advance_to_validation()

    def advance_to_validation(self) -> None:
        """Agent moves task to validation when all steps are done. execution → validation"""
        if self._state.phase == TaskPhase.VALIDATION:
            return # Already in validation
        self._validate_transition(TaskPhase.VALIDATION)
        old = self._state.phase
        self._state.phase = TaskPhase.VALIDATION
        self._record_transition(old, TaskPhase.VALIDATION)

    def complete(self) -> None:
        """User confirms task is done. validation → done"""
        self._validate_transition(TaskPhase.DONE)
        old = self._state.phase
        self._state.phase = TaskPhase.DONE
        self._record_transition(old, TaskPhase.DONE)

    def reject_validation(self) -> None:
        """Send task back to execution without changing the step index. validation → execution"""
        self._validate_transition(TaskPhase.EXECUTION)
        old = self._state.phase
        self._state.phase = TaskPhase.EXECUTION
        self._record_transition(old, TaskPhase.EXECUTION)

    def revert_to_step(self, step_idx: int) -> None:
        """Revert task back to execution at a specific step. validation/execution → execution"""
        self._validate_transition(TaskPhase.EXECUTION)
        if step_idx < 0 or step_idx >= self._state.total_steps:
            raise InvalidTransitionError(f"Invalid step index {step_idx}")
            
        old = self._state.phase
        self._state.phase = TaskPhase.EXECUTION
        self._state.current_step = step_idx
        # Truncate the 'done' array so the UI resets checks for subsequent steps
        self._state.done = self._state.done[:step_idx]
        
        self._record_transition(old, TaskPhase.EXECUTION)

    def pause(self) -> None:
        """Pause the task, remembering current phase. active → paused"""
        self._validate_transition(TaskPhase.PAUSED)
        if self._state.phase not in self._PAUSABLE:
            raise InvalidTransitionError(
                f"Cannot pause: current phase '{self._state.phase.value}' is not pausable"
            )
        old = self._state.phase
        self._state.previous_phase = self._state.phase
        self._state.phase = TaskPhase.PAUSED
        self._record_transition(old, TaskPhase.PAUSED)

    def resume(self) -> None:
        """Resume from pause, restoring previous phase. paused → previous"""
        if self._state.phase != TaskPhase.PAUSED:
            raise InvalidTransitionError(
                f"Cannot resume: current phase is '{self._state.phase.value}', expected 'paused'"
            )
        if self._state.previous_phase is None:
            raise InvalidTransitionError("Cannot resume: no previous phase stored")
        self._validate_transition(self._state.previous_phase)
        old = self._state.phase
        target = self._state.previous_phase
        self._state.phase = target
        self._state.previous_phase = None
        self._record_transition(old, target)

    def reset(self) -> None:
        """Reset to idle. Can be called from any phase."""
        old = self._state.phase
        self._state = TaskState()
        if old != TaskPhase.IDLE:
            self._record_transition(old, TaskPhase.IDLE)

    # ── Prompt injection ─────────────────────────────────────────

    def get_prompt_injection(self) -> str:
        """Build a context block for the system prompt describing current task state."""
        s = self._state
        if s.phase == TaskPhase.IDLE:
            return ""

        lines = ["[ACTIVE TASK STATE]"]
        lines.append(f"Task: {s.task}")
        lines.append(f"Phase: {s.phase.value}")

        # Allowed transitions from current phase
        allowed = self.get_allowed_transitions()
        if allowed:
            lines.append(f"Allowed transitions from '{s.phase.value}': {', '.join(allowed)}")
        lines.append(
            "STRICT RULE: You MUST NOT skip phases. Transitions outside the allowed list above are FORBIDDEN."
        )

        if s.phase == TaskPhase.PAUSED:
            lines.append(f"Paused from: {s.previous_phase.value if s.previous_phase else 'unknown'}")
            lines.append(
                "The task is PAUSED. If the user explicitly asks you to resume or continue the task, "
                "you MUST output the marker [RESUME_TASK]. This will unpause the task.\n"
                "Otherwise, converse normally but Do NOT continue task work."
            )
            return "\n".join(lines)

        if s.plan:
            lines.append(f"Plan ({s.current_step}/{s.total_steps} done):")
            for i, step in enumerate(s.plan):
                marker = "✅" if i < s.current_step else ("👉" if i == s.current_step else "⬚")
                lines.append(f"  {marker} {i + 1}. {step}")

        if s.done:
            lines.append(f"Completed: {', '.join(s.done)}")

        if s.phase == TaskPhase.PLANNING:
            if not s.plan:
                lines.append(
                    "You are in PLANNING phase. Analyze the task, break it into concrete steps, "
                    "and respond with a plan. Use the marker [PLAN_READY] at the END of your "
                    "response when the plan is complete. Format steps as a numbered list.\n"
                    "After presenting the plan you MUST STOP. Do NOT start execution."
                )
            else:
                lines.append(
                    "⚠️ PHASE IS STILL: PLANNING. The plan has been proposed but NOT YET APPROVED by the user.\n"
                    "🚫 ABSOLUTE PROHIBITION: Do NOT start execution, do NOT write code, "
                    "do NOT implement anything, do NOT perform any steps from the plan.\n"
                    "The ONLY transition allowed is: user clicks '✓ Approve Plan' button.\n"
                    "No matter what the user writes in chat — even if they say 'go ahead', "
                    "'start', 'execute', 'implement', 'proceed' — you MUST refuse and reply:\n"
                    "'Я не могу приступить к выполнению, пока план не будет утверждён. "
                    "Пожалуйста, нажмите кнопку ✓ Approve Plan в панели задачи.'\n"
                    "THIS IS A HARD SYSTEM CONSTRAINT, NOT A SUGGESTION."
                )
        elif s.phase == TaskPhase.EXECUTION:
            if s.current_step < s.total_steps:
                lines.append(
                    f"You are in EXECUTION phase. Work on step {s.current_step + 1}: "
                    f"\"{s.plan[s.current_step]}\".\n"
                    "IMPORTANT RULES:\n"
                    "- You CANNOT skip to validation or done without completing all steps.\n"
                    "- 🚨 MANDATORY STOP RULE: If a step requires user data, preferences, or choices (e.g. 'budget', 'location', 'preferences'), "
                    "you MUST ask the user for them. When you ask a question, you MUST STOP GENERATING TEXT IMMEDIATELY. "
                    "Do not attempt to guess, provide hypothetical examples, or move to the next step. Wait for the user to reply.\n"
                    "- NEVER output [STEP_DONE] if your response contains a question. A step with a pending question is BLOCKING and incomplete.\n"
                    "- Include [STEP_DONE] ONLY when you have solid data, the step is 100% resolved, and you are NOT asking any questions.\n"
                    "- 🚀 PROACTIVE EXECUTION: If (and ONLY if) you have all the necessary information and are NOT asking any questions, "
                    "write the output, include [STEP_DONE], and IMMEDIATELY start working on the next step "
                    "in the same response."
                )
            else:
                lines.append(
                    "You are in EXECUTION phase. All plan steps are complete.\n"
                    "Use the marker [READY_FOR_VALIDATION] to proceed to validation."
                )

        if s.phase in {TaskPhase.EXECUTION, TaskPhase.VALIDATION}:
            lines.append(
                "If the user is not satisfied or if you realize a mistake was made, you can roll back to a prior step.\n"
                "Use the marker [REVERT_TO_STEP: N] where N is the 1-based step number (e.g. [REVERT_TO_STEP: 2]).\n"
                "This will transition the task back to execution at that step, and you can rewrite the code or plan from there."
            )

        if s.phase == TaskPhase.VALIDATION:
            lines.append(
                "You are in VALIDATION phase. Review all completed work, verify results, "
                "and summarize what was accomplished. The user will confirm completion.\n"
                "You CANNOT mark the task as done — only the user can complete it.\n"
                "If the user is not satisfied, they can ask to revise the plan or rewrite parts of the code."
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
