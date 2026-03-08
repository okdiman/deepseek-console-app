"""Unit tests for TaskStateMachine — all transitions, edge cases, serialization, persistence."""
import json
import os
import tempfile

import pytest

from deepseek_chat.core.task_state import (
    ALLOWED_TRANSITIONS,
    TaskPhase, TaskState, TaskStateMachine, InvalidTransitionError,
)


# ── Fixtures ─────────────────────────────────────────────

@pytest.fixture
def tm():
    return TaskStateMachine()


@pytest.fixture
def tm_planning(tm):
    tm.start_task("Build feature X")
    return tm


@pytest.fixture
def tm_execution(tm_planning):
    tm_planning.set_plan(["Step A", "Step B", "Step C"])
    tm_planning.approve_plan()
    return tm_planning


@pytest.fixture
def tm_validation(tm_execution):
    for _ in range(3):
        tm_execution.step_done()
    tm_execution.advance_to_validation()
    return tm_execution


# ── Initial state ────────────────────────────────────────

class TestInitialState:
    def test_defaults(self, tm):
        assert tm.state.phase == TaskPhase.IDLE
        assert tm.state.task == ""
        assert tm.state.plan == []
        assert tm.state.done == []
        assert tm.state.current_step == 0
        assert tm.state.total_steps == 0
        assert tm.state.transition_log == []


# ── Start task ───────────────────────────────────────────

class TestStartTask:
    def test_idle_to_planning(self, tm):
        tm.start_task("Build something")
        assert tm.state.phase == TaskPhase.PLANNING
        assert tm.state.task == "Build something"

    def test_cannot_start_twice(self, tm_planning):
        with pytest.raises(InvalidTransitionError):
            tm_planning.start_task("Another task")


# ── Set plan & approve ───────────────────────────────────

class TestPlanApproval:
    def test_set_plan(self, tm_planning):
        tm_planning.set_plan(["A", "B", "C"])
        assert tm_planning.state.total_steps == 3
        assert tm_planning.state.current_step == 0

    def test_approve_plan(self, tm_planning):
        tm_planning.set_plan(["A"])
        tm_planning.approve_plan()
        assert tm_planning.state.phase == TaskPhase.EXECUTION

    def test_cannot_approve_empty_plan(self, tm_planning):
        with pytest.raises(InvalidTransitionError):
            tm_planning.approve_plan()

    def test_cannot_set_plan_outside_planning(self, tm_execution):
        with pytest.raises(InvalidTransitionError):
            tm_execution.set_plan(["X"])


# ── Step execution ───────────────────────────────────────

class TestStepDone:
    def test_step_done_increments(self, tm_execution):
        tm_execution.step_done()
        assert tm_execution.state.current_step == 1
        assert tm_execution.state.done == ["Step A"]

    def test_step_done_custom_description(self, tm_execution):
        tm_execution.step_done("Custom done text")
        assert tm_execution.state.done == ["Custom done text"]

    def test_step_done_overflow(self, tm_execution):
        for _ in range(3):
            tm_execution.step_done()
        with pytest.raises(InvalidTransitionError):
            tm_execution.step_done()

    def test_cannot_step_done_outside_execution(self, tm_planning):
        with pytest.raises(InvalidTransitionError):
            tm_planning.step_done()


# ── Validation ───────────────────────────────────────────

class TestValidation:
    def test_advance_to_validation(self, tm_execution):
        for _ in range(3):
            tm_execution.step_done()
        tm_execution.advance_to_validation()
        assert tm_execution.state.phase == TaskPhase.VALIDATION

    def test_complete(self, tm_validation):
        tm_validation.complete()
        assert tm_validation.state.phase == TaskPhase.DONE

    def test_reject_validation(self, tm_validation):
        tm_validation.reject_validation()
        assert tm_validation.state.phase == TaskPhase.EXECUTION

    def test_revert_to_step_from_validation(self, tm_validation):
        # We start with 3 completed steps in tm_validation (from fixture)
        assert tm_validation.state.current_step == 3
        tm_validation.revert_to_step(1)
        assert tm_validation.state.phase == TaskPhase.EXECUTION
        assert tm_validation.state.current_step == 1
        assert len(tm_validation.state.done) == 1

    def test_revert_to_step_from_execution(self, tm_execution):
        tm_execution.step_done()
        tm_execution.step_done()
        assert tm_execution.state.current_step == 2
        tm_execution.revert_to_step(0)
        assert tm_execution.state.phase == TaskPhase.EXECUTION
        assert tm_execution.state.current_step == 0
        assert len(tm_execution.state.done) == 0

    def test_revert_to_step_invalid_index(self, tm_validation):
        with pytest.raises(InvalidTransitionError):
            tm_validation.revert_to_step(-1)
        with pytest.raises(InvalidTransitionError):
            tm_validation.revert_to_step(3) # total_steps is 3, valid indices are 0, 1, 2

    def test_cannot_complete_outside_validation(self, tm_execution):
        with pytest.raises(InvalidTransitionError):
            tm_execution.complete()


# ── Pause / Resume ───────────────────────────────────────

class TestPauseResume:
    def test_pause_from_execution(self, tm_execution):
        tm_execution.pause()
        assert tm_execution.state.phase == TaskPhase.PAUSED
        assert tm_execution.state.previous_phase == TaskPhase.EXECUTION

    def test_resume(self, tm_execution):
        tm_execution.pause()
        tm_execution.resume()
        assert tm_execution.state.phase == TaskPhase.EXECUTION
        assert tm_execution.state.previous_phase is None

    def test_pause_from_planning(self, tm_planning):
        tm_planning.pause()
        assert tm_planning.state.phase == TaskPhase.PAUSED
        assert tm_planning.state.previous_phase == TaskPhase.PLANNING

    def test_cannot_pause_idle(self, tm):
        with pytest.raises(InvalidTransitionError):
            tm.pause()

    def test_cannot_pause_done(self, tm_validation):
        tm_validation.complete()
        with pytest.raises(InvalidTransitionError):
            tm_validation.pause()

    def test_pause_from_validation(self, tm_validation):
        tm_validation.pause()
        assert tm_validation.state.phase == TaskPhase.PAUSED
        assert tm_validation.state.previous_phase == TaskPhase.VALIDATION

    def test_resume_from_validation(self, tm_validation):
        tm_validation.pause()
        tm_validation.resume()
        assert tm_validation.state.phase == TaskPhase.VALIDATION

    def test_resume_from_planning(self, tm_planning):
        tm_planning.pause()
        tm_planning.resume()
        assert tm_planning.state.phase == TaskPhase.PLANNING


# ── Reset ────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_everything(self, tm_execution):
        tm_execution.step_done()
        tm_execution.reset()
        assert tm_execution.state.phase == TaskPhase.IDLE
        assert tm_execution.state.task == ""
        assert tm_execution.state.plan == []
        assert tm_execution.state.done == []


# ── Serialization ────────────────────────────────────────

class TestSerialization:
    def test_to_dict(self, tm_execution):
        tm_execution.step_done()
        d = tm_execution.state.to_dict()
        assert d["phase"] == "execution"
        assert d["current_step"] == 1
        assert d["plan"] == ["Step A", "Step B", "Step C"]
        assert d["done"] == ["Step A"]
        assert "transition_log" in d
        assert len(d["transition_log"]) > 0

    def test_from_dict(self, tm_execution):
        tm_execution.step_done()
        d = tm_execution.state.to_dict()
        restored = TaskState.from_dict(d)
        assert restored.phase == TaskPhase.EXECUTION
        assert restored.current_step == 1
        assert restored.plan == ["Step A", "Step B", "Step C"]
        assert len(restored.transition_log) == len(tm_execution.state.transition_log)

    def test_transition_log_roundtrip(self, tm_validation):
        d = tm_validation.state.to_dict()
        restored = TaskState.from_dict(d)
        assert len(restored.transition_log) == len(tm_validation.state.transition_log)
        for orig, rest in zip(tm_validation.state.transition_log, restored.transition_log):
            assert orig.from_phase == rest.from_phase
            assert orig.to_phase == rest.to_phase
            assert orig.timestamp == rest.timestamp


# ── Persistence ──────────────────────────────────────────

class TestPersistence:
    def test_save_and_load(self, tm_execution):
        tm_execution.step_done()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tm_execution.save(path)
            tm2 = TaskStateMachine()
            tm2.load(path)
            assert tm2.state.phase == TaskPhase.EXECUTION
            assert tm2.state.task == "Build feature X"
            assert tm2.state.current_step == 1
            assert tm2.state.done == ["Step A"]
            assert len(tm2.state.transition_log) == len(tm_execution.state.transition_log)
        finally:
            os.unlink(path)

    def test_load_missing_file(self, tm):
        tm.load("/nonexistent/path.json")
        assert tm.state.phase == TaskPhase.IDLE


# ── Prompt injection ─────────────────────────────────────

class TestPromptInjection:
    def test_idle_returns_empty(self, tm):
        assert tm.get_prompt_injection() == ""

    def test_planning_contains_marker_instruction(self, tm_planning):
        injection = tm_planning.get_prompt_injection()
        assert "[ACTIVE TASK STATE]" in injection
        assert "PLANNING" in injection
        assert "[PLAN_READY]" in injection

    def test_execution_contains_step_instruction(self, tm_execution):
        injection = tm_execution.get_prompt_injection()
        assert "EXECUTION" in injection
        assert "Step A" in injection
        assert "[STEP_DONE]" in injection

    def test_paused_contains_warning(self, tm_execution):
        tm_execution.pause()
        injection = tm_execution.get_prompt_injection()
        assert "PAUSED" in injection
        assert "Do NOT continue" in injection

    def test_prompt_contains_allowed_transitions(self, tm_planning):
        injection = tm_planning.get_prompt_injection()
        assert "Allowed transitions" in injection
        assert "FORBIDDEN" in injection

    def test_prompt_contains_no_skip_rule(self, tm_execution):
        injection = tm_execution.get_prompt_injection()
        assert "MUST NOT skip phases" in injection


# ── Full lifecycle ───────────────────────────────────────

class TestFullLifecycle:
    def test_happy_path(self, tm):
        tm.start_task("Build a widget")
        tm.set_plan(["Design", "Implement", "Test"])
        tm.approve_plan()
        for _ in range(3):
            tm.step_done()
        tm.advance_to_validation()
        assert tm.state.phase == TaskPhase.VALIDATION
        tm.complete()
        assert tm.state.phase == TaskPhase.DONE
        assert len(tm.state.done) == 3

    def test_with_pause_and_resume(self, tm):
        tm.start_task("Task with interruption")
        tm.set_plan(["A", "B"])
        tm.approve_plan()
        tm.step_done()
        tm.pause()
        assert tm.state.phase == TaskPhase.PAUSED
        tm.resume()
        assert tm.state.phase == TaskPhase.EXECUTION
        assert tm.state.current_step == 1
        tm.step_done()
        tm.advance_to_validation()
        tm.complete()
        assert tm.state.phase == TaskPhase.DONE


# ── Allowed Transitions Map ─────────────────────────────

class TestAllowedTransitions:
    """Verify the ALLOWED_TRANSITIONS map is correct and complete."""

    def test_all_phases_have_entries(self):
        for phase in TaskPhase:
            assert phase in ALLOWED_TRANSITIONS, f"Missing entry for {phase.value}"

    def test_idle_allowed(self, tm):
        assert tm.get_allowed_transitions() == ["planning"]

    def test_planning_allowed(self, tm_planning):
        allowed = tm_planning.get_allowed_transitions()
        assert "execution" in allowed
        assert "paused" in allowed
        assert "done" not in allowed
        assert "validation" not in allowed

    def test_execution_allowed(self, tm_execution):
        allowed = tm_execution.get_allowed_transitions()
        assert "execution" in allowed
        assert "validation" in allowed
        assert "paused" in allowed
        assert "done" not in allowed
        assert "planning" not in allowed

    def test_validation_allowed(self, tm_validation):
        allowed = tm_validation.get_allowed_transitions()
        assert "done" in allowed
        assert "execution" in allowed
        assert "paused" in allowed
        assert "planning" not in allowed

    def test_done_allowed(self, tm_validation):
        tm_validation.complete()
        allowed = tm_validation.get_allowed_transitions()
        assert "idle" in allowed
        assert "planning" not in allowed
        assert "execution" not in allowed

    def test_paused_allowed(self, tm_execution):
        tm_execution.pause()
        allowed = tm_execution.get_allowed_transitions()
        assert allowed == ["execution"]

    def test_paused_from_planning(self, tm_planning):
        tm_planning.pause()
        allowed = tm_planning.get_allowed_transitions()
        assert allowed == ["planning"]

    def test_paused_from_validation(self, tm_validation):
        tm_validation.pause()
        allowed = tm_validation.get_allowed_transitions()
        assert allowed == ["validation"]


# ── Forbidden transitions (parametrized) ─────────────────

_FORBIDDEN_PAIRS = [
    # (source_phase, action, description)
    ("idle", "approve_plan", "approve from idle"),
    ("idle", "step_done", "step_done from idle"),
    ("idle", "advance_to_validation", "advance from idle"),
    ("idle", "complete", "complete from idle"),
    ("idle", "pause", "pause from idle"),
    ("idle", "resume", "resume from idle"),
    ("planning", "step_done", "step_done from planning"),
    ("planning", "advance_to_validation", "advance from planning"),
    ("planning", "complete", "complete from planning"),
    ("planning", "resume", "resume from planning"),
    ("execution", "approve_plan", "approve from execution"),
    ("execution", "complete", "complete from execution"),
    ("execution", "resume", "resume from execution"),
    ("validation", "approve_plan", "approve from validation"),
    ("validation", "step_done", "step_done from validation"),
    ("validation", "start_task", "start from validation"),
    ("done", "approve_plan", "approve from done"),
    ("done", "step_done", "step_done from done"),
    ("done", "advance_to_validation", "advance from done"),
    ("done", "complete", "complete from done"),
    ("done", "pause", "pause from done"),
    ("done", "resume", "resume from done"),
    ("paused", "approve_plan", "approve from paused"),
    ("paused", "step_done", "step_done from paused"),
    ("paused", "advance_to_validation", "advance from paused"),
    ("paused", "complete", "complete from paused"),
    ("paused", "pause", "pause from paused"),
    ("paused", "start_task", "start from paused"),
]


def _build_tm_at_phase(phase_name: str) -> TaskStateMachine:
    """Helper to build a TaskStateMachine already at the specified phase."""
    tm = TaskStateMachine()
    if phase_name == "idle":
        return tm
    tm.start_task("Test task")
    if phase_name == "planning":
        return tm
    tm.set_plan(["A", "B"])
    tm.approve_plan()
    if phase_name == "execution":
        return tm
    for _ in range(2):
        tm.step_done()
    tm.advance_to_validation()
    if phase_name == "validation":
        return tm
    if phase_name == "done":
        tm.complete()
        return tm
    if phase_name == "paused":
        # Build a paused-from-execution state
        tm2 = TaskStateMachine()
        tm2.start_task("Test task")
        tm2.set_plan(["A", "B"])
        tm2.approve_plan()
        tm2.pause()
        return tm2
    raise ValueError(f"Unknown phase: {phase_name}")


class TestForbiddenTransitions:
    @pytest.mark.parametrize("source,action,desc", _FORBIDDEN_PAIRS, ids=[p[2] for p in _FORBIDDEN_PAIRS])
    def test_forbidden(self, source, action, desc):
        tm = _build_tm_at_phase(source)
        method = getattr(tm, action)

        with pytest.raises(InvalidTransitionError):
            if action == "start_task":
                method("goal")
            elif action == "step_done":
                method()
            elif action == "approve_plan":
                method()
            else:
                method()


# ── Transition Log ───────────────────────────────────────

class TestTransitionLog:
    def test_start_task_records_transition(self, tm):
        tm.start_task("Goal")
        assert len(tm.state.transition_log) == 1
        entry = tm.state.transition_log[0]
        assert entry.from_phase == "idle"
        assert entry.to_phase == "planning"
        assert entry.timestamp  # not empty

    def test_full_lifecycle_logs_all_transitions(self, tm):
        tm.start_task("Goal")
        tm.set_plan(["A"])
        tm.approve_plan()
        tm.step_done()
        tm.advance_to_validation()
        tm.complete()

        log = tm.state.transition_log
        phases = [(r.from_phase, r.to_phase) for r in log]
        assert ("idle", "planning") in phases
        assert ("planning", "execution") in phases
        assert ("execution", "validation") in phases
        assert ("validation", "done") in phases

    def test_pause_resume_logs(self, tm_execution):
        tm_execution.pause()
        tm_execution.resume()
        log = tm_execution.state.transition_log
        # Should contain pause and resume entries
        phases = [(r.from_phase, r.to_phase) for r in log]
        assert ("execution", "paused") in phases
        assert ("paused", "execution") in phases

    def test_reset_from_active_logs(self, tm_execution):
        tm_execution.reset()
        # reset creates a new state; the log on the *new* state has one entry
        assert len(tm_execution.state.transition_log) == 1
        assert tm_execution.state.transition_log[0].from_phase == "execution"
        assert tm_execution.state.transition_log[0].to_phase == "idle"

    def test_reset_from_idle_no_extra_log(self, tm):
        tm.reset()
        assert len(tm.state.transition_log) == 0

    def test_set_plan_does_not_create_transition(self, tm_planning):
        log_before = len(tm_planning.state.transition_log)
        tm_planning.set_plan(["A", "B"])
        assert len(tm_planning.state.transition_log) == log_before

    def test_step_done_does_not_create_transition(self, tm_execution):
        log_before = len(tm_execution.state.transition_log)
        tm_execution.step_done()
        assert len(tm_execution.state.transition_log) == log_before


# ── get_allowed_transitions ──────────────────────────────

class TestGetAllowedTransitions:
    @pytest.mark.parametrize("phase_name,expected", [
        ("idle", ["planning"]),
        ("planning", ["execution", "paused"]),
        ("execution", ["execution", "paused", "validation"]),
        ("validation", ["done", "execution", "paused"]),
    ])
    def test_allowed_for_each_phase(self, phase_name, expected):
        tm = _build_tm_at_phase(phase_name)
        assert tm.get_allowed_transitions() == expected

    def test_paused_returns_previous_phase(self):
        tm = _build_tm_at_phase("paused")
        allowed = tm.get_allowed_transitions()
        assert allowed == [tm.state.previous_phase.value]
