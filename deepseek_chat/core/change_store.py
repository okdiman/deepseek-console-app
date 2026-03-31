"""Shared persistent store for filesystem change proposals.

Proposals are written here by filesystem_server.py (MCP subprocess) and
applied/discarded by the user via web routes or console commands.
The LLM cannot apply proposals — it can only create them.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional

from deepseek_chat.core.paths import DATA_DIR

_STORE_PATH = DATA_DIR / "pending_changes.json"


@contextlib.contextmanager
def _file_lock():
    """Cross-process exclusive lock via fcntl (POSIX) or no-op on Windows."""
    lock_path = Path(str(_STORE_PATH) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        yield
        return
    import fcntl
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


@dataclass
class Proposal:
    id: str
    kind: Literal["write", "edit", "delete"]
    path: str
    preview: str
    content: Optional[str] = None       # for write
    old_string: Optional[str] = None    # for edit
    new_string: Optional[str] = None    # for edit


def _load() -> Dict[str, dict]:
    try:
        return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: Dict[str, dict]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def add(proposal: Proposal) -> None:
    with _file_lock():
        data = _load()
        data[proposal.id] = asdict(proposal)
        _save(data)


def get(proposal_id: str) -> Optional[Proposal]:
    with _file_lock():
        data = _load()
        raw = data.get(proposal_id)
        if raw is None:
            return None
        return Proposal(**raw)


def remove(proposal_id: str) -> bool:
    with _file_lock():
        data = _load()
        if proposal_id not in data:
            return False
        del data[proposal_id]
        _save(data)
        return True


def list_all() -> List[Proposal]:
    with _file_lock():
        return [Proposal(**v) for v in _load().values()]


def clear() -> None:
    with _file_lock():
        if _STORE_PATH.exists():
            _STORE_PATH.unlink()
