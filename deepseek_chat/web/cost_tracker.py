"""Session cost tracking for the web application.

Costs are tracked per session_id so that concurrent users don't mix up totals.
All functions accept an optional session_id (default: "default") for backward
compatibility with callers that haven't been updated yet.
"""
from __future__ import annotations

from collections import defaultdict

_costs: dict[str, float] = defaultdict(float)


def get_session_cost_usd(session_id: str = "default") -> float:
    return _costs[session_id]


def add_session_cost_usd(amount: float, session_id: str = "default") -> None:
    _costs[session_id] += amount


def reset_session_cost_usd(session_id: str = "default") -> None:
    _costs[session_id] = 0.0
