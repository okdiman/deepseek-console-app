"""Unit tests for AgentHooks — TaskStateHook, MemoryInjectionHook, UserProfileHook, InvariantGuardHook."""
from unittest.mock import MagicMock, patch

import pytest

from deepseek_chat.agents.hooks.task_state import TaskStateHook
from deepseek_chat.agents.hooks.memory_injection import MemoryInjectionHook
from deepseek_chat.agents.hooks.user_profile import UserProfileHook
from deepseek_chat.agents.hooks.invariant_guard import InvariantGuardHook
from deepseek_chat.core.task_state import TaskStateMachine, TaskPhase


# ── Helpers ──────────────────────────────────────────────

def make_agent(task_machine=None):
    """Create a mock BaseAgent with optional task machine."""
    agent = MagicMock()
    # Explicit False so getattr(..., False) returns False instead of a truthy Mock
    agent._skip_after_stream_markers = False
    if task_machine is not None:
        agent._task_machine = task_machine
    else:
        # getattr should return None
        spec = MagicMock(spec=[])
        agent.configure_mock(**{"_task_machine": None})
        # Actually delete so getattr(..., None) works
        del agent._task_machine
    return agent


def make_history(system_prompt="You are helpful.", user_msg="Hello"):
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]


# ── TaskStateHook ────────────────────────────────────────

class TestTaskStateHookBeforeStream:
    @pytest.mark.asyncio
    async def test_injects_prompt_when_active(self):
        hook = TaskStateHook()
        tm = TaskStateMachine()
        tm.start_task("Build feature")
        agent = make_agent(task_machine=tm)
        history = make_history()

        result = await hook.before_stream(agent, "test input", "base prompt", history)
        assert "[ACTIVE TASK STATE]" in result
        assert "PLANNING" in result

    @pytest.mark.asyncio
    async def test_no_injection_when_idle(self):
        hook = TaskStateHook()
        tm = TaskStateMachine()
        agent = make_agent(task_machine=tm)
        history = make_history()

        result = await hook.before_stream(agent, "test", "base prompt", history)
        assert result == "base prompt"

    @pytest.mark.asyncio
    async def test_no_injection_without_task_machine(self):
        hook = TaskStateHook()
        agent = make_agent(task_machine=None)
        history = make_history()

        result = await hook.before_stream(agent, "test", "base prompt", history)
        assert result == "base prompt"


class TestTaskStateHookAfterStream:
    @pytest.mark.asyncio
    async def test_plan_ready_sets_plan(self):
        hook = TaskStateHook()
        tm = TaskStateMachine()
        tm.start_task("Build feature")
        agent = make_agent(task_machine=tm)

        response = "Here's my plan:\n1. Design API\n2. Implement endpoints\n3. Write tests\n[PLAN_READY]"
        await hook.after_stream(agent, response)

        assert tm.state.total_steps == 3
        assert tm.state.plan == ["Design API", "Implement endpoints", "Write tests"]

    @pytest.mark.asyncio
    async def test_step_done_increments(self):
        hook = TaskStateHook()
        tm = TaskStateMachine()
        tm.start_task("Task")
        tm.set_plan(["A", "B"])
        tm.approve_plan()
        agent = make_agent(task_machine=tm)

        await hook.after_stream(agent, "Completed step [STEP_DONE]")
        assert tm.state.current_step == 1

    @pytest.mark.asyncio
    async def test_validation_ready(self):
        hook = TaskStateHook()
        tm = TaskStateMachine()
        tm.start_task("Task")
        tm.set_plan(["A"])
        tm.approve_plan()
        agent = make_agent(task_machine=tm)

        await hook.after_stream(agent, "All done [READY_FOR_VALIDATION]")
        assert tm.state.phase == TaskPhase.VALIDATION

    @pytest.mark.asyncio
    async def test_auto_advance_when_all_steps_done(self):
        hook = TaskStateHook()
        tm = TaskStateMachine()
        tm.start_task("Task")
        tm.set_plan(["Only step"])
        tm.approve_plan()
        tm.step_done()
        agent = make_agent(task_machine=tm)

        # Response without explicit marker, but all steps are done
        await hook.after_stream(agent, "Everything is finished")
        assert tm.state.phase == TaskPhase.VALIDATION

    @pytest.mark.asyncio
    async def test_no_crash_without_task_machine(self):
        hook = TaskStateHook()
        agent = make_agent(task_machine=None)
        await hook.after_stream(agent, "some response")


# ── MemoryInjectionHook ──────────────────────────────────

class TestMemoryInjectionHook:
    @pytest.mark.asyncio
    async def test_injects_memory_before_last_message(self):
        hook = MemoryInjectionHook()
        agent = MagicMock()
        history = make_history()

        # Patch at the source module where MemoryStore is defined
        with patch("deepseek_chat.core.memory.MemoryStore.load") as mock_load:
            mock_instance = MagicMock()
            mock_instance.get_system_prompt_injection.return_value = "MEMORY INJECTION"
            mock_load.return_value = mock_instance

            result = await hook.before_stream(agent, "hi", "sys prompt", history)

        assert len(history) == 3
        assert history[-2]["role"] == "system"
        assert history[-2]["content"] == "MEMORY INJECTION"
        assert result == "sys prompt"

    @pytest.mark.asyncio
    async def test_no_injection_when_memory_empty(self):
        hook = MemoryInjectionHook()
        agent = MagicMock()
        history = make_history()

        with patch("deepseek_chat.core.memory.MemoryStore.load") as mock_load:
            mock_instance = MagicMock()
            mock_instance.get_system_prompt_injection.return_value = ""
            mock_load.return_value = mock_instance

            await hook.before_stream(agent, "hi", "sys prompt", history)

        assert len(history) == 2  # unchanged

    @pytest.mark.asyncio
    async def test_single_message_history(self):
        hook = MemoryInjectionHook()
        agent = MagicMock()
        history = [{"role": "user", "content": "hello"}]

        with patch("deepseek_chat.core.memory.MemoryStore.load") as mock_load:
            mock_instance = MagicMock()
            mock_instance.get_system_prompt_injection.return_value = "MEM"
            mock_load.return_value = mock_instance

            await hook.before_stream(agent, "hi", "sys prompt", history)

        assert len(history) == 2
        assert history[0]["content"] == "MEM"


# ── UserProfileHook ──────────────────────────────────────

class TestUserProfileHook:
    @pytest.mark.asyncio
    async def test_appends_profile_to_prompt(self):
        hook = UserProfileHook()
        agent = MagicMock()
        history = make_history()

        with patch("deepseek_chat.core.memory.profile.UserProfile.load") as mock_load:
            mock_instance = MagicMock()
            mock_instance.is_empty.return_value = False
            mock_instance.name = "Dmitriy"
            mock_instance.role = "Developer"
            mock_instance.style_preferences = ""
            mock_instance.formatting_rules = ""
            mock_instance.constraints = ""
            mock_load.return_value = mock_instance

            result = await hook.before_stream(agent, "hi", "base prompt", history)

        assert "USER PROFILE" in result
        assert "Dmitriy" in result
        assert "Developer" in result

    @pytest.mark.asyncio
    async def test_empty_profile_no_change(self):
        hook = UserProfileHook()
        agent = MagicMock()
        history = make_history()

        with patch("deepseek_chat.core.memory.profile.UserProfile.load") as mock_load:
            mock_instance = MagicMock()
            mock_instance.is_empty.return_value = True
            mock_load.return_value = mock_instance

            result = await hook.before_stream(agent, "hi", "base prompt", history)

        assert result == "base prompt"


# ── InvariantGuardHook ───────────────────────────────────

class TestInvariantGuardHook:
    @pytest.mark.asyncio
    async def test_injects_invariants_before_last_message(self):
        hook = InvariantGuardHook()
        agent = MagicMock()
        history = make_history()

        with patch("deepseek_chat.core.memory.invariants.InvariantStore.load") as mock_load:
            mock_instance = MagicMock()
            mock_instance.get_system_prompt_injection.return_value = "INVARIANT RULES"
            mock_load.return_value = mock_instance

            result = await hook.before_stream(agent, "hi", "sys prompt", history)

        assert len(history) == 3
        assert history[-2]["content"] == "INVARIANT RULES"
        assert result == "sys prompt"

    @pytest.mark.asyncio
    async def test_no_injection_when_empty(self):
        hook = InvariantGuardHook()
        agent = MagicMock()
        history = make_history()

        with patch("deepseek_chat.core.memory.invariants.InvariantStore.load") as mock_load:
            mock_instance = MagicMock()
            mock_instance.get_system_prompt_injection.return_value = ""
            mock_load.return_value = mock_instance

            await hook.before_stream(agent, "hi", "sys prompt", history)

        assert len(history) == 2  # unchanged
