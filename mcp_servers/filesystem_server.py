"""Filesystem MCP Server — two-phase read/write access to the project.

Write operations are strictly two-phase:
  1. propose_*  — validates the change, persists it to change_store, returns a diff
  2. apply / discard — triggered ONLY by the user (web buttons or console commands)

The LLM has NO apply/discard tools. It physically cannot write files on its own.
"""
from __future__ import annotations

import difflib
import sys
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from deepseek_chat.core import change_store
from deepseek_chat.core.change_store import Proposal

_PROJECT_ROOT = Path(__file__).parent.parent

mcp = FastMCP("Filesystem Server")


def _rel(path: str) -> Path:
    """Resolve a project-relative path safely (no escaping above root)."""
    resolved = (_PROJECT_ROOT / path).resolve()
    if not str(resolved).startswith(str(_PROJECT_ROOT.resolve())):
        raise ValueError(f"Path '{path}' escapes the project root.")
    return resolved


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


def _unified_diff(path: str, old: str, new: str) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
        lineterm="",
    )
    return "".join(diff) or "(no textual changes)"


# ── Read tools ────────────────────────────────────────────────────────────────

@mcp.tool()
def read_file(path: str) -> str:
    """Read the contents of a file in the project.

    path: Path relative to project root (e.g. 'deepseek_chat/core/config.py').
    """
    try:
        return _rel(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return f"File not found: {path}"
    except Exception as e:
        return f"Error reading '{path}': {e}"


@mcp.tool()
def list_directory(path: str = ".", pattern: str = "*") -> str:
    """List files in a directory, filtered by glob pattern.

    path: Directory relative to project root (default: project root).
    pattern: Glob pattern to filter files (e.g. '*.py', '**/*.md').
    """
    _SKIP = {"__pycache__", ".git", ".claude", ".venv", "venv", "node_modules", ".pytest_cache"}
    try:
        base = _rel(path)
        if not base.is_dir():
            return f"Not a directory: {path}"
        results = []
        for p in sorted(base.rglob(pattern)):
            if any(part in _SKIP for part in p.parts):
                continue
            results.append(str(p.relative_to(_PROJECT_ROOT)))
        return "\n".join(results) if results else f"No files matching '{pattern}' in '{path}'."
    except Exception as e:
        return f"Error listing '{path}': {e}"


@mcp.tool()
def search_in_files(pattern: str, glob: str = "**/*.py") -> str:
    """Search for a regex pattern in project files.

    pattern: Text or regex to search for.
    glob: File glob to search in (default: all .py files).
    Returns up to 50 matches with file:line:content.
    """
    import re
    _SKIP = {"__pycache__", ".git", ".claude", ".venv", "venv", "node_modules"}
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Invalid regex '{pattern}': {e}"

    matches = []
    for p in sorted(_PROJECT_ROOT.rglob(glob)):
        if any(part in _SKIP for part in p.parts):
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    rel = str(p.relative_to(_PROJECT_ROOT))
                    matches.append(f"{rel}:{i}: {line.rstrip()}")
                    if len(matches) >= 50:
                        matches.append("... (truncated at 50 matches)")
                        return "\n".join(matches)
        except Exception:
            continue

    return "\n".join(matches) if matches else f"No matches for '{pattern}' in '{glob}'."


# ── Proposal tools (LLM can call these) ──────────────────────────────────────

@mcp.tool()
def propose_write(path: str, content: str) -> str:
    """Propose creating or overwriting a file. Saves the proposal for user review.

    The file is NOT written until the user approves via the web UI or /apply command.
    path: Path relative to project root.
    content: Full file content to write.
    """
    try:
        abs_path = _rel(path)
    except ValueError as e:
        return f"Error: {e}"

    if abs_path.exists():
        existing = abs_path.read_text(encoding="utf-8", errors="replace")
        preview = _unified_diff(path, existing, content)
        action = "overwrite"
    else:
        lines = content.splitlines()
        preview = "\n".join(f"+ {ln}" for ln in lines)
        action = "create"

    pid = _short_id()
    change_store.add(Proposal(id=pid, kind="write", path=path, preview=preview, content=content))

    return (
        f"Proposal `{pid}` — {action} `{path}`:\n\n"
        f"```diff\n{preview}\n```\n\n"
        f"⏳ Waiting for your approval. Use the **Apply / Discard** buttons in the UI, "
        f"or type `/apply {pid}` / `/discard {pid}` in the console."
    )


@mcp.tool()
def propose_edit(path: str, old_string: str, new_string: str) -> str:
    """Propose replacing an exact string in a file. Saves the proposal for user review.

    The file is NOT modified until the user approves via the web UI or /apply command.
    path: Path relative to project root.
    old_string: Exact text to find (must be unique in the file).
    new_string: Text to replace it with.
    """
    try:
        abs_path = _rel(path)
    except ValueError as e:
        return f"Error: {e}"

    try:
        original = abs_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return f"File not found: {path}"

    count = original.count(old_string)
    if count == 0:
        return f"String not found in '{path}'. Check for exact whitespace/indentation match."
    if count > 1:
        return (
            f"String appears {count} times in '{path}'. "
            f"Provide more surrounding context to make it unique."
        )

    modified = original.replace(old_string, new_string, 1)
    preview = _unified_diff(path, original, modified)

    pid = _short_id()
    change_store.add(Proposal(
        id=pid, kind="edit", path=path, preview=preview,
        old_string=old_string, new_string=new_string,
    ))

    return (
        f"Proposal `{pid}` — edit `{path}`:\n\n"
        f"```diff\n{preview}\n```\n\n"
        f"⏳ Waiting for your approval. Use the **Apply / Discard** buttons in the UI, "
        f"or type `/apply {pid}` / `/discard {pid}` in the console."
    )


@mcp.tool()
def propose_delete(path: str) -> str:
    """Propose deleting a file. Saves the proposal for user review.

    The file is NOT deleted until the user approves via the web UI or /apply command.
    path: Path relative to project root.
    """
    try:
        abs_path = _rel(path)
    except ValueError as e:
        return f"Error: {e}"

    if not abs_path.exists():
        return f"File not found: {path}"

    pid = _short_id()
    change_store.add(Proposal(id=pid, kind="delete", path=path, preview=f"Delete file: {path}"))

    return (
        f"Proposal `{pid}` — delete `{path}`.\n\n"
        f"⏳ Waiting for your approval. Use the **Apply / Discard** buttons in the UI, "
        f"or type `/apply {pid}` / `/discard {pid}` in the console."
    )


@mcp.tool()
def list_pending_changes() -> str:
    """List all proposals currently waiting for user approval."""
    proposals = change_store.list_all()
    if not proposals:
        return "No pending proposals."
    lines = [f"`{p.id}` — {p.kind} `{p.path}`" for p in proposals]
    return "\n".join(lines)


# ── Apply / discard (NOT MCP tools — called only by web routes / console) ─────

def apply_change(proposal_id: str) -> str:
    """Apply a proposal. Called by the web route or console — NOT by the LLM."""
    proposal = change_store.get(proposal_id)
    if proposal is None:
        pending = ", ".join(p.id for p in change_store.list_all()) or "none"
        return f"Proposal '{proposal_id}' not found. Pending: {pending}"

    try:
        abs_path = _rel(proposal.path)

        if proposal.kind == "write":
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(proposal.content, encoding="utf-8")
            change_store.remove(proposal_id)
            return f"✅ Written: `{proposal.path}`"

        elif proposal.kind == "edit":
            original = abs_path.read_text(encoding="utf-8", errors="replace")
            count = original.count(proposal.old_string)
            if count != 1:
                return (
                    f"❌ Cannot apply: target string now appears {count} times in "
                    f"'{proposal.path}' (file changed since proposal was created)."
                )
            modified = original.replace(proposal.old_string, proposal.new_string, 1)
            abs_path.write_text(modified, encoding="utf-8")
            change_store.remove(proposal_id)
            return f"✅ Edited: `{proposal.path}`"

        elif proposal.kind == "delete":
            abs_path.unlink()
            change_store.remove(proposal_id)
            return f"✅ Deleted: `{proposal.path}`"

    except Exception as e:
        return f"❌ Failed to apply '{proposal_id}': {e}"


def discard_change(proposal_id: str) -> str:
    """Discard a proposal. Called by the web route or console — NOT by the LLM."""
    if change_store.remove(proposal_id):
        return f"Proposal '{proposal_id}' discarded."
    return f"Proposal '{proposal_id}' not found."


# ── Test runner ───────────────────────────────────────────────────────────────

@mcp.tool()
def run_tests(test_path: str = "tests/") -> str:
    """Run pytest on the project (or a specific test file/directory).

    test_path: Path relative to project root (default: 'tests/').
    Returns test output truncated to 8000 chars.
    """
    import subprocess
    try:
        abs_path = _rel(test_path)
    except ValueError as e:
        return f"Error: {e}"

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(abs_path), "--tb=short", "-q"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        if len(output) > 8000:
            output = output[:8000] + "\n... (truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Tests timed out after 120 seconds."
    except Exception as e:
        return f"Error running tests: {e}"


if __name__ == "__main__":
    mcp.run()
