"""
DialogueTask — structured task memory for the current conversation.

Tracks the user's goal, clarifications, fixed constraints, explored topics,
and questions that couldn't be answered (unresolved). Updated via markers
the agent embeds in responses.

Markers the agent should output:
  [GOAL: <text>]        — sets / updates the conversation goal
  [CLARIFIED: <text>]   — records a user clarification (user-stated facts only)
  [CONSTRAINT: <text>]  — records a user-imposed rule or restriction
  [TOPIC: <text>]       — marks a topic as substantively answered
  [UNRESOLVED: <text>]  — records a question that couldn't be answered (IDK)

Storage: DIALOGUE_TASK_PATH env var (default: <DATA_DIR>/dialogue_task.json)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List

from deepseek_chat.core.paths import DATA_DIR


@dataclass
class DialogueTask:
    goal: str = ""
    clarifications: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    explored_topics: List[str] = field(default_factory=list)
    unresolved_questions: List[str] = field(default_factory=list)

    # ── mutation ──────────────────────────────────────────────────────────────

    def apply_marker(self, marker_type: str, value: str) -> None:
        """Apply a single parsed marker to this task state."""
        value = value.strip()
        if not value:
            return
        mt = marker_type.upper()
        if mt == "GOAL":
            self.goal = value
        elif mt == "CLARIFIED":
            if value not in self.clarifications:
                self.clarifications.append(value)
        elif mt == "CONSTRAINT":
            if value not in self.constraints:
                self.constraints.append(value)
        elif mt == "TOPIC":
            if value not in self.explored_topics:
                self.explored_topics.append(value)
            # When a topic is answered, remove any matching unresolved question
            self.unresolved_questions = [
                q for q in self.unresolved_questions
                if q.lower() not in value.lower() and value.lower() not in q.lower()
            ]
        elif mt == "UNRESOLVED":
            if value not in self.unresolved_questions:
                self.unresolved_questions.append(value)

    def clear(self) -> None:
        self.goal = ""
        self.clarifications = []
        self.constraints = []
        self.explored_topics = []
        self.unresolved_questions = []

    # ── prompt injection ──────────────────────────────────────────────────────

    def get_injection(self) -> str:
        """Return a formatted block to append to the system prompt."""
        marker_instructions = (
            "## Dialogue Task Memory — marker rules\n"
            "Embed these markers anywhere in your response to update task memory.\n"
            "Rules are STRICT — read carefully before using any marker.\n\n"
            "[GOAL: <text>]\n"
            "  WHEN: ALWAYS on your FIRST response if the user's intent is clear.\n"
            "  CRITICAL: set based on what the USER ASKS, NOT on what you can answer.\n"
            "  Even if you have no context and must say IDK — still emit [GOAL:].\n"
            "  LANGUAGE: always write the goal in ENGLISH regardless of the user's language.\n"
            "  Example: user asks 'explain attention mechanism' → [GOAL: understand attention mechanism]\n"
            "  Update only if the goal genuinely shifts in a later turn.\n\n"
            "[CLARIFIED: <text>]\n"
            "  WHEN: the USER explicitly states a preference, background, or detail\n"
            "        about their needs — e.g. 'I prefer math', 'I am a beginner'.\n"
            "  NEVER: your observations about the context, corpus, or missing info.\n\n"
            "[CONSTRAINT: <text>]\n"
            "  WHEN: the USER explicitly restricts your approach, language, or tools —\n"
            "        e.g. 'only Python', 'no external APIs', 'max 2 paragraphs'.\n"
            "  NEVER: system prompt instructions like 'answer from context only'.\n\n"
            "[TOPIC: <text>]\n"
            "  WHEN: you just gave a SUBSTANTIVE answer to a specific question.\n"
            "  NEVER: when you said 'I don't know' or 'not in context'.\n"
            "  Emit after EVERY answered question — use specific names:\n"
            "    [TOPIC: scaled dot-product attention]  [TOPIC: role of sqrt(d_k)]\n\n"
            "[UNRESOLVED: <text>]\n"
            "  WHEN: you cannot answer because information is absent from the context.\n"
            "  Write the USER'S question concisely: [UNRESOLVED: how does sqrt(d_k) work?]\n"
            "  This helps track what still needs to be answered in future turns."
        )

        is_empty = (
            not self.goal
            and not self.clarifications
            and not self.constraints
            and not self.explored_topics
            and not self.unresolved_questions
        )
        if is_empty:
            return (
                "## Dialogue Task Memory\n"
                "No goal established yet. Set it immediately when the user's intent\n"
                "is clear, based on what they ask (not on what you can answer).\n\n"
                + marker_instructions
            )

        parts = ["## Dialogue Task Memory"]
        parts.append(f"Goal: {self.goal}" if self.goal else "Goal: (not set yet — set with [GOAL:])")

        if self.clarifications:
            parts.append(f"User clarifications ({len(self.clarifications)}):")
            for i, c in enumerate(self.clarifications, 1):
                parts.append(f"  {i}. {c}")

        if self.constraints:
            parts.append(f"User constraints ({len(self.constraints)}):")
            for i, c in enumerate(self.constraints, 1):
                parts.append(f"  {i}. {c}")

        if self.explored_topics:
            parts.append(f"Answered topics ({len(self.explored_topics)}) — do not repeat these:")
            for i, t in enumerate(self.explored_topics, 1):
                parts.append(f"  {i}. {t}")

        if self.unresolved_questions:
            parts.append(f"Unresolved questions ({len(self.unresolved_questions)}) — answer if context now allows:")
            for i, q in enumerate(self.unresolved_questions, 1):
                parts.append(f"  {i}. {q}")

        parts.append("")
        parts.append(marker_instructions)
        return "\n".join(parts)

    def get_summary(self) -> str:
        """Human-readable summary for /summary command."""
        lines = ["── Dialogue Summary ──────────────────────────────"]
        lines.append(f"Goal       : {self.goal or '(not set)'}")
        if self.clarifications:
            lines.append(f"Clarified  :")
            for c in self.clarifications:
                lines.append(f"  • {c}")
        if self.constraints:
            lines.append(f"Constraints:")
            for c in self.constraints:
                lines.append(f"  • {c}")
        if self.explored_topics:
            lines.append(f"Answered   :")
            for t in self.explored_topics:
                lines.append(f"  ✓ {t}")
        if self.unresolved_questions:
            lines.append(f"Unresolved :")
            for q in self.unresolved_questions:
                lines.append(f"  ? {q}")
        lines.append("──────────────────────────────────────────────────")
        return "\n".join(lines)

    # ── persistence ───────────────────────────────────────────────────────────

    @staticmethod
    def _storage_path() -> str:
        path = os.getenv("DIALOGUE_TASK_PATH", str(DATA_DIR / "dialogue_task.json"))
        return os.path.expanduser(path)

    def save(self) -> None:
        path = self._storage_path()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "goal": self.goal,
                    "clarifications": self.clarifications,
                    "constraints": self.constraints,
                    "explored_topics": self.explored_topics,
                    "unresolved_questions": self.unresolved_questions,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    @classmethod
    def load(cls) -> "DialogueTask":
        path = cls._storage_path()
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(
                goal=data.get("goal", ""),
                clarifications=data.get("clarifications", []),
                constraints=data.get("constraints", []),
                explored_topics=data.get("explored_topics", []),
                unresolved_questions=data.get("unresolved_questions", []),
            )
        except Exception:
            return cls()
