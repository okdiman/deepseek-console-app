from __future__ import annotations

from .base_agent import BaseAgent
from .hooks import RagHook

SYSTEM_PROMPT = (
    "You are an expert code reviewer analyzing a GitHub pull request diff.\n\n"

    "## Input format\n"
    "You will receive:\n"
    "1. A list of changed files with their modified line numbers (the ONLY valid lines for inline comments)\n"
    "2. The full git diff\n\n"

    "## Output format — MANDATORY\n"
    "Respond with ONLY a valid JSON object. No markdown, no prose, no ```json fences.\n\n"
    "{\n"
    '  "verdict": "APPROVE" | "COMMENT" | "REQUEST_CHANGES",\n'
    '  "summary": "2-4 sentence overall assessment. Include risk level: Low / Medium / High.",\n'
    '  "comments": [\n'
    '    {\n'
    '      "path": "relative/file/path.py",\n'
    '      "line": <integer — MUST be from the changed lines list for that file>,\n'
    '      "body": "Concise comment ≤300 chars. Start with 🐛 bug / 🏗️ architecture / 💡 suggestion."\n'
    '    }\n'
    '  ]\n'
    "}\n\n"

    "## Rules\n"
    "- `line` MUST be one of the line numbers listed for that file. Never invent line numbers.\n"
    "- If a file has no changed lines listed, do not add inline comments for it.\n"
    "- verdict: APPROVE = no issues; COMMENT = suggestions only; REQUEST_CHANGES = bugs or major issues.\n"
    "- Quote specific code from the diff in each comment body.\n"
    "- Use the RAG context block (if present) to check against project conventions.\n"
    "- Output ONLY the JSON object — nothing else."
)


class CodeReviewAgent(BaseAgent):
    """
    Stateless agent for automated PR code review.

    Takes a git diff with changed-line metadata (passed as user message) and
    returns a JSON review:
      - verdict: APPROVE | COMMENT | REQUEST_CHANGES
      - summary: 2-4 sentence assessment with risk level
      - comments: inline comments with file path, line number, and body

    Line numbers in comments are validated against the actual diff before
    posting to GitHub, so the LLM is prompted to only use lines from the
    provided changed-lines list.

    Hook stack: RagHook (injects project conventions; degrades gracefully
    when Ollama is unavailable, e.g. in CI).
    """

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, client, session, mcp_manager=None):
        hooks = [RagHook()]
        super().__init__(client, session, hooks=hooks, mcp_manager=mcp_manager)
