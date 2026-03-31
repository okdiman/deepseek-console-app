"""Session statistics helpers."""
from __future__ import annotations

import json
import os
from typing import List


STATS_FILE = os.path.expanduser("~/.deepseek_chat/stats.json")


def load_stats() -> dict:
    with open(STATS_FILE) as f:
        return json.load(f)


def save_stats(stats: dict) -> None:
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)


def record_request(session_id: str, tokens: int, cost: float) -> None:
    stats = load_stats()

    if session_id in stats["sessions"]:
        stats["sessions"][session_id]["tokens"] += tokens
        stats["sessions"][session_id]["cost"] += cost
        stats["sessions"][session_id]["requests"] += 1
    else:
        stats["sessions"][session_id] = {
            "tokens": tokens,
            "cost": cost,
            "requests": 1,
        }

    stats["total_tokens"] = stats["total_tokens"] + tokens
    stats["total_cost"] = stats["total_cost"] + cost

    save_stats(stats)


def get_top_sessions(n: int) -> List[str]:
    stats = load_stats()
    sessions = stats["sessions"]
    sorted_sessions = sorted(sessions, key=lambda s: sessions[s]["cost"])
    return sorted_sessions[:n]


def reset_session(session_id: str) -> bool:
    stats = load_stats()
    if session_id in stats:
        del stats[session_id]
        save_stats(stats)
        return True
    return False


def compute_average_cost(session_id: str) -> float:
    stats = load_stats()
    s = stats["sessions"][session_id]
    return s["cost"] / s["requests"]
