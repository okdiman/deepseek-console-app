"""Unit tests for streaming.py marker helpers — _collect_task_markers, _apply_task_markers."""

import os
import json
import pytest

# state.py runs load_config() at import time — provide a dummy key
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-for-unit-tests")

from deepseek_chat.web.streaming import _collect_task_markers, _apply_task_markers
from deepseek_chat.core.task_state import TaskStateMachine, TaskPhase


# ── Helpers ──────────────────────────────────────────────

def make_executing_tm(steps: int = 2) -> TaskStateMachine:
    tm = TaskStateMachine()
    tm.start_task("test task")
    tm.set_plan([f"Step {i + 1}" for i in range(steps)])
    tm.approve_plan()
    return tm


# ── _collect_task_markers ────────────────────────────────

class TestCollectTaskMarkers:
    def test_no_markers_empty_result(self):
        assert _collect_task_markers("hello world", 0) == []

    def test_step_done_detected(self):
        markers = _collect_task_markers("Done [STEP_DONE]", 0)
        assert len(markers) == 1
        assert markers[0][2] == "STEP_DONE"

    def test_validation_long_form(self):
        markers = _collect_task_markers("Ready [READY_FOR_VALIDATION]", 0)
        assert len(markers) == 1
        assert markers[0][2] == "VALIDATION"

    def test_validation_short_form(self):
        markers = _collect_task_markers("[VALIDATION]", 0)
        assert len(markers) == 1
        assert markers[0][2] == "VALIDATION"

    def test_revert_marker_parsed(self):
        markers = _collect_task_markers("[REVERT_TO_STEP: 3]", 0)
        assert len(markers) == 1
        assert markers[0][2] == "REVERT"
        assert markers[0][3] == 2  # 1-indexed → 0-indexed

    def test_revert_marker_step_1(self):
        markers = _collect_task_markers("[REVERT_TO_STEP: 1]", 0)
        assert markers[0][3] == 0

    def test_resume_marker(self):
        markers = _collect_task_markers("[RESUME_TASK]", 0)
        assert len(markers) == 1
        assert markers[0][2] == "RESUME"

    def test_case_insensitive(self):
        assert len(_collect_task_markers("[step_done]", 0)) == 1
        assert len(_collect_task_markers("[ready_for_validation]", 0)) == 1
        assert len(_collect_task_markers("[resume_task]", 0)) == 1

    def test_multiple_markers_sorted_by_position(self):
        text = "[STEP_DONE] then [READY_FOR_VALIDATION]"
        markers = _collect_task_markers(text, 0)
        assert len(markers) == 2
        assert markers[0][2] == "STEP_DONE"
        assert markers[1][2] == "VALIDATION"
        assert markers[0][0] < markers[1][0]

    def test_last_idx_filters_already_processed(self):
        text = "[STEP_DONE] more text [STEP_DONE]"
        first_end = text.index("]") + 1
        markers = _collect_task_markers(text, first_end)
        assert len(markers) == 1  # only second occurrence

    def test_last_idx_zero_finds_all(self):
        text = "[STEP_DONE] [STEP_DONE]"
        markers = _collect_task_markers(text, 0)
        assert len(markers) == 2

    def test_returns_start_end_indices(self):
        text = "prefix [STEP_DONE] suffix"
        markers = _collect_task_markers(text, 0)
        start, end = markers[0][0], markers[0][1]
        assert text[start:end] == "[STEP_DONE]"


# ── _apply_task_markers ──────────────────────────────────

class TestApplyTaskMarkersNoOp:
    def test_plain_text_no_events(self):
        tm = make_executing_tm()
        new_idx, events = _apply_task_markers(tm, "no markers here", 0)
        assert events == []
        assert new_idx == 0

    def test_idle_phase_ignored(self):
        tm = TaskStateMachine()  # idle
        _, events = _apply_task_markers(tm, "[STEP_DONE]", 0)
        assert events == []

    def test_planning_phase_ignored(self):
        tm = TaskStateMachine()
        tm.start_task("task")  # PLANNING
        _, events = _apply_task_markers(tm, "[STEP_DONE]", 0)
        assert events == []

    def test_done_phase_ignored(self):
        tm = make_executing_tm(steps=1)
        tm.step_done()
        tm.advance_to_validation()
        tm.complete()
        _, events = _apply_task_markers(tm, "[STEP_DONE]", 0)
        assert events == []


class TestApplyTaskMarkersStepDone:
    def test_step_done_increments_step(self):
        tm = make_executing_tm(steps=2)
        _apply_task_markers(tm, "[STEP_DONE]", 0)
        assert tm.state.current_step == 1

    def test_step_done_emits_sse_event(self):
        tm = make_executing_tm(steps=2)
        _, events = _apply_task_markers(tm, "[STEP_DONE]", 0)
        assert len(events) == 1
        data = json.loads(events[0].replace("data: ", "").strip())
        assert "task_state" in data

    def test_step_done_advances_last_idx(self):
        tm = make_executing_tm(steps=2)
        text = "[STEP_DONE]"
        new_idx, _ = _apply_task_markers(tm, text, 0)
        assert new_idx == len(text)

    def test_two_step_dones_processed(self):
        tm = make_executing_tm(steps=2)
        _, events = _apply_task_markers(tm, "[STEP_DONE] [STEP_DONE]", 0)
        assert tm.state.current_step == 2
        assert len(events) == 2


class TestApplyTaskMarkersValidation:
    def test_validation_transitions_phase(self):
        tm = make_executing_tm(steps=1)
        _apply_task_markers(tm, "[READY_FOR_VALIDATION]", 0)
        assert tm.state.phase == TaskPhase.VALIDATION

    def test_validation_emits_event(self):
        tm = make_executing_tm(steps=1)
        _, events = _apply_task_markers(tm, "[READY_FOR_VALIDATION]", 0)
        assert len(events) >= 1

    def test_validation_auto_completes_last_step(self):
        # If current_step < total, step_done is called automatically before advancing
        tm = make_executing_tm(steps=2)
        tm.step_done()  # step 1 done, step 2 still pending
        _apply_task_markers(tm, "[READY_FOR_VALIDATION]", 0)
        assert tm.state.phase == TaskPhase.VALIDATION


class TestApplyTaskMarkersRevert:
    def test_revert_from_execution(self):
        tm = make_executing_tm(steps=3)
        tm.step_done()
        tm.step_done()
        _, events = _apply_task_markers(tm, "[REVERT_TO_STEP: 1]", 0)
        assert len(events) == 1

    def test_revert_from_validation(self):
        tm = make_executing_tm(steps=2)
        tm.step_done()
        tm.step_done()
        tm.advance_to_validation()
        _, events = _apply_task_markers(tm, "[REVERT_TO_STEP: 1]", 0)
        assert len(events) == 1
        assert tm.state.phase == TaskPhase.EXECUTION


class TestApplyTaskMarkersResume:
    def test_resume_from_paused(self):
        tm = make_executing_tm(steps=2)
        tm.pause()
        assert tm.state.phase == TaskPhase.PAUSED
        _, events = _apply_task_markers(tm, "[RESUME_TASK]", 0)
        assert tm.state.phase == TaskPhase.EXECUTION
        assert len(events) == 1


class TestApplyTaskMarkersIncrementalProcessing:
    def test_second_call_from_new_idx_finds_nothing(self):
        tm = make_executing_tm(steps=2)
        text = "[STEP_DONE]"
        new_idx, _ = _apply_task_markers(tm, text, 0)
        # Call again from new_idx — same text, no new markers
        _, events2 = _apply_task_markers(tm, text, new_idx)
        assert events2 == []
        assert tm.state.current_step == 1  # unchanged

    def test_incremental_accumulation(self):
        tm = make_executing_tm(steps=2)
        text1 = "Working on step 1..."
        text2 = text1 + "[STEP_DONE]"
        # First chunk — no markers
        new_idx, events1 = _apply_task_markers(tm, text1, 0)
        assert events1 == []
        # Second chunk extends the text
        new_idx, events2 = _apply_task_markers(tm, text2, new_idx)
        assert len(events2) == 1
        assert tm.state.current_step == 1


class TestApplyTaskMarkersEventPayload:
    def test_event_contains_allowed_transitions(self):
        tm = make_executing_tm(steps=2)
        _, events = _apply_task_markers(tm, "[STEP_DONE]", 0)
        data = json.loads(events[0].replace("data: ", "").strip())
        assert "allowed_transitions" in data["task_state"]

    def test_event_sse_format(self):
        tm = make_executing_tm(steps=2)
        _, events = _apply_task_markers(tm, "[STEP_DONE]", 0)
        assert events[0].startswith("data: ")
        assert events[0].endswith("\n\n")
