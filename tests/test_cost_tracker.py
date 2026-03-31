"""Unit tests for web cost_tracker — session-scoped cost tracking."""
import pytest

from deepseek_chat.web import cost_tracker


@pytest.fixture(autouse=True)
def reset_cost():
    """Ensure clean state for each test."""
    cost_tracker.reset_session_cost_usd("default")
    cost_tracker.reset_session_cost_usd("session_a")
    cost_tracker.reset_session_cost_usd("session_b")
    yield
    cost_tracker.reset_session_cost_usd("default")
    cost_tracker.reset_session_cost_usd("session_a")
    cost_tracker.reset_session_cost_usd("session_b")


class TestCostTracker:
    def test_default_is_zero(self):
        assert cost_tracker.get_session_cost_usd() == 0.0

    def test_add(self):
        cost_tracker.add_session_cost_usd(0.5)
        cost_tracker.add_session_cost_usd(0.3)
        assert abs(cost_tracker.get_session_cost_usd() - 0.8) < 1e-9

    def test_reset(self):
        cost_tracker.add_session_cost_usd(5.0)
        cost_tracker.reset_session_cost_usd()
        assert cost_tracker.get_session_cost_usd() == 0.0

    def test_add_accumulates(self):
        for _ in range(10):
            cost_tracker.add_session_cost_usd(0.1)
        assert abs(cost_tracker.get_session_cost_usd() - 1.0) < 1e-9

    def test_sessions_are_isolated(self):
        """Costs for different sessions must not bleed into each other."""
        cost_tracker.add_session_cost_usd(1.0, "session_a")
        cost_tracker.add_session_cost_usd(2.0, "session_b")
        assert cost_tracker.get_session_cost_usd("session_a") == 1.0
        assert cost_tracker.get_session_cost_usd("session_b") == 2.0
        assert cost_tracker.get_session_cost_usd("default") == 0.0

    def test_reset_affects_only_given_session(self):
        cost_tracker.add_session_cost_usd(3.0, "session_a")
        cost_tracker.add_session_cost_usd(4.0, "session_b")
        cost_tracker.reset_session_cost_usd("session_a")
        assert cost_tracker.get_session_cost_usd("session_a") == 0.0
        assert cost_tracker.get_session_cost_usd("session_b") == 4.0
