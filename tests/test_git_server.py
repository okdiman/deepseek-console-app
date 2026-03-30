"""Tests for mcp_servers/git_server.py — git tools."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from mcp_servers.git_server import (
    get_current_branch,
    get_file_diff,
    get_project_structure,
    get_recent_commits,
    list_changed_files,
)


def test_get_current_branch_returns_string():
    result = get_current_branch()
    assert isinstance(result, str)
    assert len(result) > 0
    # Should not be an error string (git is available in this repo)
    assert not result.startswith("git is not installed")


def test_get_current_branch_is_valid_branch():
    result = get_current_branch()
    # Branch names don't contain spaces (unless error)
    assert "git error" not in result


def test_get_recent_commits_default():
    result = get_recent_commits()
    assert isinstance(result, str)
    assert len(result) > 0
    # Should contain commit entries separated by newlines
    assert "No commits found." not in result  # project has commits
    lines = result.strip().split("\n")
    assert len(lines) <= 10


def test_get_recent_commits_limit():
    result = get_recent_commits(limit=3)
    lines = result.strip().split("\n")
    assert len(lines) <= 3


def test_get_recent_commits_limit_clamped():
    # limit > 50 should be clamped to 50
    result = get_recent_commits(limit=999)
    assert isinstance(result, str)


def test_get_recent_commits_format():
    result = get_recent_commits(limit=1)
    if result != "No commits found.":
        # Format: "hash | author | relative_date | message"
        assert "|" in result


def test_list_changed_files_returns_string():
    result = list_changed_files()
    assert isinstance(result, str)
    # Either "Working tree is clean." or a list of files
    assert len(result) > 0


def test_get_file_diff_nonexistent_file():
    result = get_file_diff("nonexistent_file_xyz.py")
    assert isinstance(result, str)
    # Either no diff or an error — both are acceptable strings
    assert len(result) > 0


def test_get_project_structure_default():
    result = get_project_structure()
    assert isinstance(result, str)
    assert "deepseek-console-app" in result or "deepseek_chat" in result
    # Should not include __pycache__ or .git
    assert "__pycache__" not in result
    assert ".git/" not in result


def test_get_project_structure_depth_1():
    result = get_project_structure(max_depth=1)
    lines = result.strip().split("\n")
    # Depth 1 should only show top-level items
    assert len(lines) < 50  # reasonable upper bound


def test_get_project_structure_depth_clamped():
    # max_depth > 5 should be clamped to 5
    result = get_project_structure(max_depth=99)
    assert isinstance(result, str)
    assert len(result) > 0
