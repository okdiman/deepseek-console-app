"""Session cost tracking for the web application."""
from __future__ import annotations


_session_cost_usd = 0.0


def get_session_cost_usd() -> float:
    return _session_cost_usd


def set_session_cost_usd(value: float) -> None:
    global _session_cost_usd
    _session_cost_usd = value


def add_session_cost_usd(amount: float) -> None:
    global _session_cost_usd
    _session_cost_usd += amount


def reset_session_cost_usd() -> None:
    global _session_cost_usd
    _session_cost_usd = 0.0
