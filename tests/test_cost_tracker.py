"""Unit tests for web cost_tracker — simple state management."""
import pytest

from deepseek_chat.web import cost_tracker


@pytest.fixture(autouse=True)
def reset_cost():
    """Ensure clean state for each test."""
    cost_tracker.reset_session_cost_usd()
    yield
    cost_tracker.reset_session_cost_usd()


class TestCostTracker:
    def test_default_is_zero(self):
        assert cost_tracker.get_session_cost_usd() == 0.0

    def test_set(self):
        cost_tracker.set_session_cost_usd(1.23)
        assert cost_tracker.get_session_cost_usd() == 1.23

    def test_add(self):
        cost_tracker.add_session_cost_usd(0.5)
        cost_tracker.add_session_cost_usd(0.3)
        assert abs(cost_tracker.get_session_cost_usd() - 0.8) < 1e-9

    def test_reset(self):
        cost_tracker.set_session_cost_usd(5.0)
        cost_tracker.reset_session_cost_usd()
        assert cost_tracker.get_session_cost_usd() == 0.0

    def test_add_accumulates(self):
        for _ in range(10):
            cost_tracker.add_session_cost_usd(0.1)
        assert abs(cost_tracker.get_session_cost_usd() - 1.0) < 1e-9
