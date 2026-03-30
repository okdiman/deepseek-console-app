"""Git Project MCP Server — exposes git information about the project to the LLM."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Git Project Server")

# Project root is two levels up from this file (mcp_servers/git_server.py → project root)
_PROJECT_ROOT = Path(__file__).parent.parent


def _git(*args: str, cwd: Path = _PROJECT_ROOT) -> str:
    """Run a git command and return stdout, or an error message on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return f"git error: {result.stderr.strip() or result.stdout.strip()}"
        return result.stdout.strip()
    except FileNotFoundError:
        return "git is not installed or not in PATH"
    except subprocess.TimeoutExpired:
        return "git command timed out"


@mcp.tool()
def get_current_branch() -> str:
    """Returns the current git branch name of the project."""
    return _git("rev-parse", "--abbrev-ref", "HEAD")


@mcp.tool()
def get_recent_commits(limit: int = 10) -> str:
    """Returns the last N git commits with short hash, author, relative date, and message.

    limit: Number of commits to return (default 10, max 50).
    """
    limit = min(max(1, limit), 50)
    out = _git(
        "log",
        f"--max-count={limit}",
        "--pretty=format:%h | %an | %ar | %s",
    )
    return out or "No commits found."


@mcp.tool()
def list_changed_files() -> str:
    """Returns the list of files with uncommitted changes (git status --short)."""
    out = _git("status", "--short")
    return out or "Working tree is clean."


@mcp.tool()
def get_file_diff(file_path: str) -> str:
    """Returns the git diff for a specific file (HEAD vs working tree + staged changes).

    file_path: Path relative to project root (e.g. 'deepseek_chat/core/config.py').
    """
    out = _git("diff", "HEAD", "--", file_path)
    return out or f"No diff found for '{file_path}'."


@mcp.tool()
def get_project_structure(max_depth: int = 3) -> str:
    """Returns a text tree of the project directory structure.

    Excludes __pycache__, .git, .venv, node_modules, *.pyc, and *.egg-info dirs.
    max_depth: How many directory levels to show (default 3, max 5).
    """
    max_depth = min(max(1, max_depth), 5)

    _SKIP = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache"}
    _SKIP_SUFFIXES = {".pyc", ".pyo"}

    lines: list[str] = [str(_PROJECT_ROOT.name) + "/"]

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        visible = [
            c for c in children
            if c.name not in _SKIP
            and not any(c.name.endswith(s) for s in _SKIP_SUFFIXES)
            and not c.name.endswith(".egg-info")
        ]

        for i, child in enumerate(visible):
            is_last = i == len(visible) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{child.name}{'/' if child.is_dir() else ''}")
            if child.is_dir():
                extension = "    " if is_last else "│   "
                _walk(child, prefix + extension, depth + 1)

    _walk(_PROJECT_ROOT, "", 1)
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
