"""
Shared schedule utilities for the scheduler package.
Extracted so both scheduler_server.py and scheduler_runner.py can import
without creating a circular dependency.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional


def compute_next_run(schedule: str, from_time: Optional[datetime] = None) -> Optional[str]:
    """
    Compute the next run time based on a simplified schedule string.
    Supported formats:
      - 'once'           → None (no next run)
      - 'every_Nm'       → N minutes from now  (e.g. every_5m)
      - 'every_Nh'       → N hours from now     (e.g. every_1h)
      - 'daily_HH:MM'    → next occurrence of HH:MM UTC
    """
    now = from_time or datetime.now(timezone.utc)

    if schedule == "once":
        return None

    m = re.match(r"^every_(\d+)m$", schedule)
    if m:
        return (now + timedelta(minutes=int(m.group(1)))).isoformat()

    m = re.match(r"^every_(\d+)h$", schedule)
    if m:
        return (now + timedelta(hours=int(m.group(1)))).isoformat()

    m = re.match(r"^daily_(\d{2}):(\d{2})$", schedule)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.isoformat()

    return None
