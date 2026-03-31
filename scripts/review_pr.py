#!/usr/bin/env python3
"""
Automated PR code review script.

Usage:
    python scripts/review_pr.py --diff diff.patch [--output review.json]
    git diff origin/main...HEAD | python scripts/review_pr.py

Output (stdout):
    Human-readable markdown summary.

Output (--output FILE):
    JSON file for GitHub Actions inline review posting:
    {
      "verdict": "REQUEST_CHANGES",
      "summary": "...",
      "comments": [{"path": "file.py", "line": 42, "body": "..."}]
    }

Environment variables:
    PROVIDER / DEEPSEEK_API_KEY / GROQ_API_KEY — same as the main app (.env is loaded)
    RAG_ENABLED — set to "false" to skip RAG (recommended in CI without Ollama)
    MAX_DIFF_CHARS — diff truncation limit in characters (default: 60000)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

# Ensure project root is on the import path when run as a script
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from deepseek_chat.agents.code_review_agent import CodeReviewAgent
from deepseek_chat.core.client import DeepSeekClient
from deepseek_chat.core.config import load_config
from deepseek_chat.core.session import ChatSession

_MAX_DIFF_CHARS = int(os.getenv("MAX_DIFF_CHARS", "60000"))
_TRUNCATION_NOTICE = (
    "\n\n⚠️ [Diff truncated — only the first {kept} of {total} characters are shown.]\n"
)


# ── Diff parser ───────────────────────────────────────────────────────────────

def parse_changed_lines(diff: str) -> dict[str, list[int]]:
    """Parse unified diff → {filepath: [new-side line numbers of added lines]}.

    Only '+' lines (additions) are collected — these are the lines GitHub
    allows inline review comments on (side=RIGHT).
    """
    result: dict[str, list[int]] = {}
    current_file: str | None = None
    new_line = 0

    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
            result.setdefault(current_file, [])
            new_line = 0
        elif raw.startswith("@@ "):
            m = re.search(r"\+(\d+)", raw)
            if m:
                new_line = int(m.group(1))
        elif current_file is not None:
            if raw.startswith("+++") or raw.startswith("---"):
                continue
            if raw.startswith("+"):
                result[current_file].append(new_line)
                new_line += 1
            elif raw.startswith("-"):
                pass  # deleted line — new_line does not advance
            elif not raw.startswith("\\"):
                new_line += 1  # context line

    return result


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(diff: str, changed_lines: dict[str, list[int]]) -> str:
    total = len(diff)
    if total > _MAX_DIFF_CHARS:
        diff = diff[:_MAX_DIFF_CHARS] + _TRUNCATION_NOTICE.format(
            kept=_MAX_DIFF_CHARS, total=total
        )

    parts: list[str] = []

    if changed_lines:
        parts.append("**Changed lines available for inline comments:**")
        for path, lines in sorted(changed_lines.items()):
            displayed = sorted(lines)[:30]
            suffix = f" … (+{len(lines) - 30} more)" if len(lines) > 30 else ""
            parts.append(f"  - `{path}`: {', '.join(str(n) for n in displayed)}{suffix}")
        parts.append("")

    parts.append("**Diff:**")
    parts.append("```diff")
    parts.append(diff)
    parts.append("```")

    return "\n".join(parts)


# ── JSON extraction ───────────────────────────────────────────────────────────

def extract_review_json(text: str) -> dict:
    """Extract the JSON review object from LLM response.

    Handles three cases:
    1. Raw JSON  →  { ... }
    2. Fenced    →  ```json\\n{ ... }\\n```
    3. Embedded  →  prose ... { ... } ... prose
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))

    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))

    raise ValueError(f"No JSON found in LLM response:\n{text[:300]}")


def validate_comments(
    comments: list[dict], changed_lines: dict[str, list[int]]
) -> tuple[list[dict], list[dict]]:
    """Split comments into (valid, skipped).

    Valid = line is actually in the diff for that file.
    Skipped = LLM referenced a line that isn't in the diff (hallucinated).
    """
    valid, skipped = [], []
    for c in comments:
        path = c.get("path", "")
        line = c.get("line")
        if isinstance(line, int) and line in changed_lines.get(path, []):
            valid.append(c)
        else:
            skipped.append(c)
    return valid, skipped


# ── Agent runner ──────────────────────────────────────────────────────────────

async def _run_review(diff: str, changed_lines: dict[str, list[int]]) -> dict:
    config = load_config()
    client = DeepSeekClient(config)
    session = ChatSession(max_messages=10)
    agent = CodeReviewAgent(client, session)

    prompt = _build_prompt(diff, changed_lines)
    result = await agent.ask(prompt)
    return extract_review_json(result.content)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _render_markdown(review: dict, valid: list[dict], skipped: list[dict]) -> str:
    verdict_emoji = {"APPROVE": "✅", "COMMENT": "💬", "REQUEST_CHANGES": "❌"}.get(
        review.get("verdict", ""), "🔍"
    )
    lines = [
        f"## 🤖 AI Code Review  {verdict_emoji} {review.get('verdict', '')}",
        "",
        review.get("summary", ""),
        "",
    ]
    if valid:
        lines.append("### Inline comments")
        for c in valid:
            lines.append(f"- **`{c['path']}:{c['line']}`** — {c['body']}")
        lines.append("")
    if skipped:
        lines.append(
            f"*{len(skipped)} comment(s) skipped — line numbers not found in diff.*"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run AI code review on a git diff.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--diff", metavar="FILE",
        help="Path to diff file. If omitted, reads from stdin.",
    )
    parser.add_argument(
        "--output", metavar="FILE",
        help="Write JSON review to this file (for GitHub Actions inline posting).",
    )
    args = parser.parse_args()

    if args.diff:
        diff = Path(args.diff).read_text(encoding="utf-8", errors="replace")
    else:
        if sys.stdin.isatty():
            print("Error: provide --diff FILE or pipe a diff via stdin.", file=sys.stderr)
            sys.exit(1)
        diff = sys.stdin.read()

    if not diff.strip():
        print("Error: diff is empty — nothing to review.", file=sys.stderr)
        sys.exit(1)

    changed_lines = parse_changed_lines(diff)
    review = asyncio.run(_run_review(diff, changed_lines))

    comments = review.get("comments") or []
    valid, skipped = validate_comments(comments, changed_lines)
    review["comments"] = valid  # only valid inline comments go to GitHub

    if args.output:
        Path(args.output).write_text(json.dumps(review, ensure_ascii=False, indent=2))

    print(_render_markdown(review, valid, skipped))


if __name__ == "__main__":
    main()
