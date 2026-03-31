#!/usr/bin/env python3
"""
Automated PR code review script.

Usage:
    python scripts/review_pr.py --diff diff.patch [--changed-files file1.py file2.py]
    git diff origin/main...HEAD | python scripts/review_pr.py

Output:
    Structured markdown review to stdout:
      ## 🐛 Potential Bugs
      ## 🏗️ Architectural Issues
      ## 💡 Recommendations
      ## ✅ Summary

Environment variables:
    PROVIDER / DEEPSEEK_API_KEY / GROQ_API_KEY — same as the main app (.env is loaded)
    RAG_ENABLED — set to "false" to skip RAG (recommended in CI without Ollama)
    MAX_DIFF_CHARS — truncation limit in characters (default: 60000)
"""

from __future__ import annotations

import argparse
import asyncio
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

_MAX_DIFF_CHARS = int(__import__("os").getenv("MAX_DIFF_CHARS", "60000"))
_TRUNCATION_NOTICE = "\n\n⚠️ *[Diff truncated — only the first {kept} characters of {total} are shown.]*\n"


def _build_prompt(diff: str, changed_files: list[str]) -> str:
    total = len(diff)
    if total > _MAX_DIFF_CHARS:
        kept = _MAX_DIFF_CHARS
        diff = diff[:kept] + _TRUNCATION_NOTICE.format(kept=kept, total=total)

    parts = []
    if changed_files:
        parts.append("**Changed files:**")
        for f in changed_files:
            parts.append(f"  - `{f}`")
        parts.append("")

    parts.append("**Diff:**")
    parts.append("```diff")
    parts.append(diff)
    parts.append("```")

    return "\n".join(parts)


async def _run_review(diff: str, changed_files: list[str]) -> str:
    config = load_config()
    client = DeepSeekClient(config)
    session = ChatSession(max_messages=10)
    agent = CodeReviewAgent(client, session)

    prompt = _build_prompt(diff, changed_files)
    result = await agent.ask(prompt)
    return result.content


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run AI code review on a git diff.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--diff",
        metavar="FILE",
        help="Path to the diff file. If omitted, reads from stdin.",
    )
    parser.add_argument(
        "--changed-files",
        metavar="FILE",
        nargs="*",
        default=[],
        help="List of changed file paths (informational context for the reviewer).",
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

    review = asyncio.run(_run_review(diff, args.changed_files))
    print(review)


if __name__ == "__main__":
    main()
