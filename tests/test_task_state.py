"""Unit tests for TaskStateMachine — all transitions, edge cases, serialization, persistence."""
import json
import os
import tempfile

import pytest

from deepseek_chat.core.task_state import (
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

    def test_from_dict(self, tm_execution):
        tm_execution.step_done()
        d = tm_execution.state.to_dict()
        restored = TaskState.from_dict(d)
        assert restored.phase == TaskPhase.EXECUTION
        assert restored.current_step == 1
        assert restored.plan == ["Step A", "Step B", "Step C"]


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
