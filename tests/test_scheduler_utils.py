"""Unit tests for mcp_servers/scheduler/scheduler_utils.py — compute_next_run()."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp_servers'))

from datetime import datetime, timedelta, timezone
from scheduler.scheduler_utils import compute_next_run


_T = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)  # fixed reference point


class TestOnce:
    def test_once_returns_none(self):
        assert compute_next_run("once", from_time=_T) is None


class TestEveryMinutes:
    def test_every_5m(self):
        result = compute_next_run("every_5m", from_time=_T)
        assert result == (_T + timedelta(minutes=5)).isoformat()

    def test_every_1m(self):
        result = compute_next_run("every_1m", from_time=_T)
        assert result == (_T + timedelta(minutes=1)).isoformat()

    def test_every_30m(self):
        result = compute_next_run("every_30m", from_time=_T)
        assert result == (_T + timedelta(minutes=30)).isoformat()

    def test_every_90m(self):
        result = compute_next_run("every_90m", from_time=_T)
        assert result == (_T + timedelta(minutes=90)).isoformat()


class TestEveryHours:
    def test_every_1h(self):
        result = compute_next_run("every_1h", from_time=_T)
        assert result == (_T + timedelta(hours=1)).isoformat()

    def test_every_24h(self):
        result = compute_next_run("every_24h", from_time=_T)
        assert result == (_T + timedelta(hours=24)).isoformat()

    def test_every_2h(self):
        result = compute_next_run("every_2h", from_time=_T)
        assert result == (_T + timedelta(hours=2)).isoformat()


class TestDailySchedule:
    def test_daily_future_same_day(self):
        # 12:00 now, target 14:00 → today
        now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run("daily_14:00", from_time=now)
        expected = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc).isoformat()
        assert result == expected

    def test_daily_past_advances_to_tomorrow(self):
        # 15:00 now, target 14:00 → tomorrow
        now = datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run("daily_14:00", from_time=now)
        expected = datetime(2026, 1, 16, 14, 0, 0, tzinfo=timezone.utc).isoformat()
        assert result == expected

    def test_daily_exact_time_advances_to_tomorrow(self):
        # Exact match: candidate <= now, so advance
        now = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run("daily_14:00", from_time=now)
        expected = datetime(2026, 1, 16, 14, 0, 0, tzinfo=timezone.utc).isoformat()
        assert result == expected

    def test_daily_midnight(self):
        now = datetime(2026, 1, 15, 1, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run("daily_00:00", from_time=now)
        expected = datetime(2026, 1, 16, 0, 0, 0, tzinfo=timezone.utc).isoformat()
        assert result == expected

    def test_daily_seconds_zeroed(self):
        now = datetime(2026, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        result = compute_next_run("daily_11:00", from_time=now)
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.second == 0
        assert dt.microsecond == 0


class TestUnknownSchedule:
    def test_unknown_returns_none(self):
        assert compute_next_run("weekly_monday", from_time=_T) is None

    def test_empty_string_returns_none(self):
        assert compute_next_run("", from_time=_T) is None

    def test_garbage_returns_none(self):
        assert compute_next_run("every_5x", from_time=_T) is None

    def test_partial_match_returns_none(self):
        assert compute_next_run("every_m", from_time=_T) is None


class TestDefaultNow:
    def test_uses_current_time_when_no_from_time(self):
        result = compute_next_run("every_1m")
        assert result is not None
        # Result should be in ISO format
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None
