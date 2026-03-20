#!/usr/bin/env python3
"""
Day 25 — Experiment runner.

Runs two predefined scenarios (10–12 messages each) against the full
RAG + DialogueTask + Memory agent stack. Records per-turn data and
saves a JSON log + markdown analysis report.

Usage:
    python3 experiments/rag_compare/run_scenarios.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from deepseek_chat.agents.base_agent import BaseAgent
from deepseek_chat.agents.hooks.dialogue_task_hook import DialogueTaskHook
from deepseek_chat.agents.hooks.invariant_guard import InvariantGuardHook
from deepseek_chat.agents.hooks.memory_injection import MemoryInjectionHook
from deepseek_chat.agents.hooks.rag_hook import RagHook
from deepseek_chat.core.client import DeepSeekClient
from deepseek_chat.core.config import load_config
from deepseek_chat.core.dialogue_task import DialogueTask
from deepseek_chat.core.session import ChatSession


# ── Agent definition ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a knowledgeable assistant with access to a curated knowledge base "
    "on Python, transformers, RAG systems, and concurrency. "
    "Always ground your answers in retrieved sources and cite them using [N] notation. "
    "Keep track of the conversation goal and mark progress with task memory markers. "
    "Be concise and precise."
)


class ExperimentAgent(BaseAgent):
    SYSTEM_PROMPT = SYSTEM_PROMPT


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class TurnRecord:
    turn: int
    user_input: str
    response: str
    task_memory: dict
    chunks_retrieved: int
    chunk_titles: List[str]
    has_citation_brackets: bool      # response contains [N]
    has_sources_section: bool        # response contains "Sources:" or similar
    response_length: int
    elapsed_s: float


@dataclass
class ScenarioResult:
    name: str
    description: str
    turns: List[TurnRecord] = field(default_factory=list)
    rag_active: bool = False


# ── Scenarios ─────────────────────────────────────────────────────────────────

SCENARIO_1 = {
    "name": "Transformer Attention Deep-Dive",
    "description": (
        "User explores transformer attention mechanism step by step. "
        "Tests: goal tracking, topic accumulation, no repetition."
    ),
    "messages": [
        "Привет! Я хочу разобраться, как работает механизм внимания (attention) в трансформерах. С чего начнём?",
        "Окей, но мне важно понять математику. Без неё не интересно.",
        "Хорошо, покажи формулу scaled dot-product attention и объясни каждый множитель.",
        "Зачем делить на sqrt(d_k)? Что происходит без этого деления?",
        "Понял. Теперь объясни multi-head attention — чем он отличается от обычного?",
        "Сколько голов обычно используется и почему именно столько?",
        "А как позиционная кодировка связана с attention? Почему нельзя обойтись без неё?",
        "Подожди, мы уже разобрали self-attention и multi-head. Что ещё осталось для полного понимания?",
        "Объясни cross-attention — в каких архитектурах он нужен?",
        "Хорошо, можешь подвести итог: какие ключевые концепции мы разобрали?",
        "Покажи минимальный Python-код self-attention без библиотек.",
        "Спасибо! Какие источники ты использовал в этом разговоре?",
    ],
}

SCENARIO_2 = {
    "name": "RAG System Design with Constraints",
    "description": (
        "User designs a RAG system under specific constraints. "
        "Tests: constraint accumulation, goal maintenance, source citation."
    ),
    "messages": [
        "Мне нужно спроектировать RAG-систему для поиска по документации. Помоги.",
        "Важно: только Python, никаких Java или Go.",
        "И ещё ограничение: embedding-модель должна быть локальной, без внешних API.",
        "Какую базу для хранения эмбеддингов лучше взять? Мне нужно что-то лёгкое.",
        "SQLite подходит? Как хранить в нём векторы?",
        "Хорошо. Как реализовать cosine similarity поиск прямо в SQLite без расширений?",
        "Понял. Теперь chunking — как лучше разбивать документацию на чанки?",
        "У нас markdown-документация. Есть ли смысл разбивать по заголовкам ## ?",
        "Расскажи про reranking — зачем он нужен после первичного поиска?",
        "Подведи итог: какую архитектуру ты рекомендуешь с учётом всех моих ограничений?",
    ],
}


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_scenario(
    scenario_def: dict,
    config,
    client: DeepSeekClient,
    task_path: str,
    context_path: str,
) -> ScenarioResult:
    result = ScenarioResult(
        name=scenario_def["name"],
        description=scenario_def["description"],
    )

    # Fresh session + task memory for each scenario
    session = ChatSession(max_messages=config.context_max_messages)
    task = DialogueTask()
    task.save()  # write empty file at task_path

    rag_hook = RagHook()
    hooks = [
        rag_hook,
        MemoryInjectionHook(),
        DialogueTaskHook(),
        InvariantGuardHook(),
    ]
    agent = ExperimentAgent(client, session, hooks=hooks)

    print(f"\n{'='*60}")
    print(f"Scenario: {scenario_def['name']}")
    print(f"{'='*60}")

    for i, user_msg in enumerate(scenario_def["messages"], 1):
        print(f"\n[Turn {i}/{len(scenario_def['messages'])}] {user_msg[:70]}...")

        chunks_before = list(rag_hook.last_chunks)
        t0 = time.time()
        response_parts: list[str] = []

        try:
            async for chunk in agent.stream_reply(user_msg):
                response_parts.append(chunk)
                print(chunk, end="", flush=True)
        except Exception as exc:
            print(f"\n  ERROR: {exc}")
            response_parts.append(f"[ERROR: {exc}]")

        elapsed = time.time() - t0
        response = "".join(response_parts)
        print()

        # Read updated task memory
        current_task = DialogueTask.load()

        # Analyse response
        has_citation = bool(re.search(r"\[\d+\]", response))
        has_sources = bool(re.search(r"(источник|source|according to|\[1\]|\[2\])", response, re.IGNORECASE))
        chunks = list(rag_hook.last_chunks)

        turn = TurnRecord(
            turn=i,
            user_input=user_msg,
            response=response,
            task_memory={
                "goal": current_task.goal,
                "clarifications": list(current_task.clarifications),
                "constraints": list(current_task.constraints),
                "explored_topics": list(current_task.explored_topics),
            },
            chunks_retrieved=len(chunks),
            chunk_titles=[
                (f"{c.get('title','')} › {c.get('section','')}" if c.get("section") else c.get("title", ""))
                for c in chunks
            ],
            has_citation_brackets=has_citation,
            has_sources_section=has_sources,
            response_length=len(response),
            elapsed_s=round(elapsed, 2),
        )
        result.turns.append(turn)
        result.rag_active = result.rag_active or len(chunks) > 0

        goal_preview = repr(current_task.goal[:50])
        print(f"  [task] goal={goal_preview}"
              f" | clarif={len(current_task.clarifications)}"
              f" | constraints={len(current_task.constraints)}"
              f" | topics={len(current_task.explored_topics)}"
              f" | chunks={len(chunks)}"
              f" | cite={has_citation}")

        await asyncio.sleep(0.5)  # be gentle with API rate limits

    return result


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyse(results: List[ScenarioResult]) -> str:
    lines = [
        "# Day 25 — RAG Mini-Chat: Experiment Analysis",
        "",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}",
        f"**Scenarios:** {len(results)}",
        "",
    ]

    for sr in results:
        turns = sr.turns
        n = len(turns)

        goal_by_turn = [t.task_memory["goal"] for t in turns]
        final_goal = goal_by_turn[-1] if goal_by_turn else ""
        goal_set_at = next((i+1 for i, g in enumerate(goal_by_turn) if g), None)

        all_clarif = turns[-1].task_memory["clarifications"] if turns else []
        all_constraints = turns[-1].task_memory["constraints"] if turns else []
        all_topics = turns[-1].task_memory["explored_topics"] if turns else []

        turns_with_citations = sum(1 for t in turns if t.has_citation_brackets)
        turns_with_sources = sum(1 for t in turns if t.has_sources_section)
        avg_chunks = sum(t.chunks_retrieved for t in turns) / n if n else 0
        avg_elapsed = sum(t.elapsed_s for t in turns) / n if n else 0
        total_elapsed = sum(t.elapsed_s for t in turns)

        lines += [
            f"## Scenario: {sr.name}",
            "",
            f"> {sr.description}",
            "",
            f"**RAG active:** {'Yes' if sr.rag_active else 'No (Ollama unavailable or index empty)'}",
            f"**Turns:** {n}",
            f"**Total time:** {total_elapsed:.1f}s  |  avg per turn: {avg_elapsed:.1f}s",
            "",
            "### Dialogue Task Memory",
            "",
            f"- **Goal established at turn:** {goal_set_at or 'never'}",
            f"- **Final goal:** {final_goal or '(not set)'}",
            f"- **Clarifications accumulated:** {len(all_clarif)}",
        ]
        for c in all_clarif:
            lines.append(f"  - {c}")
        lines.append(f"- **Constraints accumulated:** {len(all_constraints)}")
        for c in all_constraints:
            lines.append(f"  - {c}")
        lines.append(f"- **Explored topics marked:** {len(all_topics)}")
        for t in all_topics:
            lines.append(f"  - {t}")

        lines += [
            "",
            "### Citation & Sources",
            "",
            f"- Turns with `[N]` citations: **{turns_with_citations}/{n}**",
            f"- Turns with source references: **{turns_with_sources}/{n}**",
            f"- Avg chunks retrieved per turn: **{avg_chunks:.1f}**",
            "",
            "### Goal Continuity (turn-by-turn)",
            "",
            "| Turn | Goal set? | Clarif | Constrain | Topics | Chunks | Cited |",
            "|------|-----------|--------|-----------|--------|--------|-------|",
        ]
        for t in turns:
            tm = t.task_memory
            lines.append(
                f"| {t.turn} "
                f"| {'✓' if tm['goal'] else '—'} "
                f"| {len(tm['clarifications'])} "
                f"| {len(tm['constraints'])} "
                f"| {len(tm['explored_topics'])} "
                f"| {t.chunks_retrieved} "
                f"| {'✓' if t.has_citation_brackets else '—'} |"
            )

        lines += ["", "### Per-Turn Responses", ""]
        for t in turns:
            snippet = t.response[:300].replace("\n", " ")
            lines += [
                f"**Turn {t.turn}** _{t.elapsed_s}s_",
                f"> {snippet}{'...' if len(t.response) > 300 else ''}",
                "",
            ]

        lines.append("---")
        lines.append("")

    # Overall summary
    all_turns = [t for sr in results for t in sr.turns]
    total_n = len(all_turns)
    total_cited = sum(1 for t in all_turns if t.has_citation_brackets)
    total_with_sources = sum(1 for t in all_turns if t.has_sources_section)
    goals_set = sum(1 for sr in results if sr.turns and sr.turns[-1].task_memory["goal"])

    lines += [
        "## Overall Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total turns | {total_n} |",
        f"| Scenarios with goal established | {goals_set}/{len(results)} |",
        f"| Turns with [N] citations | {total_cited}/{total_n} ({100*total_cited//total_n if total_n else 0}%) |",
        f"| Turns with source references | {total_with_sources}/{total_n} ({100*total_with_sources//total_n if total_n else 0}%) |",
        f"| RAG active scenarios | {sum(1 for sr in results if sr.rag_active)}/{len(results)} |",
        "",
        "### Conclusions",
        "",
    ]

    # Auto-generate conclusions
    if goals_set == len(results):
        lines.append("✅ **Goal tracking:** Agent established a goal in every scenario.")
    else:
        lines.append(f"⚠️ **Goal tracking:** Goal established in {goals_set}/{len(results)} scenarios.")

    total_clarif = sum(len(sr.turns[-1].task_memory["clarifications"]) for sr in results if sr.turns)
    total_constraints = sum(len(sr.turns[-1].task_memory["constraints"]) for sr in results if sr.turns)
    total_topics = sum(len(sr.turns[-1].task_memory["explored_topics"]) for sr in results if sr.turns)

    lines.append(f"✅ **Memory accumulation:** {total_clarif} clarifications, {total_constraints} constraints, {total_topics} explored topics accumulated across scenarios.")

    if total_cited / total_n >= 0.5 if total_n else False:
        lines.append(f"✅ **Citations:** Present in {total_cited}/{total_n} turns — agent cites sources consistently.")
    else:
        lines.append(f"⚠️ **Citations:** Only {total_cited}/{total_n} turns have [N] citations — may need RAG to be active.")

    if any(sr.rag_active for sr in results):
        lines.append("✅ **RAG pipeline:** Active — retrieved and injected document chunks.")
    else:
        lines.append("⚠️ **RAG pipeline:** Inactive (Ollama unavailable) — agent answered from general knowledge only.")

    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    config = load_config()
    client = DeepSeekClient(config)

    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)
    json_path = out_dir / "day25_experiment_log.json"
    md_path = out_dir / "day25_analysis.md"

    # Use temp files for task + context to avoid polluting real session
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        task_path = tf.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        context_path = tf.name

    os.environ["DIALOGUE_TASK_PATH"] = task_path
    os.environ["DEEPSEEK_CONTEXT_PATH"] = context_path

    results: List[ScenarioResult] = []

    for scenario_def in [SCENARIO_1, SCENARIO_2]:
        # Reset task file between scenarios
        DialogueTask().save()

        sr = await run_scenario(
            scenario_def, config, client, task_path, context_path
        )
        results.append(sr)

    # ── Save JSON log ─────────────────────────────────────────────────────────
    log_data = []
    for sr in results:
        log_data.append({
            "name": sr.name,
            "description": sr.description,
            "rag_active": sr.rag_active,
            "turns": [asdict(t) for t in sr.turns],
        })

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ JSON log saved: {json_path}")

    # ── Save markdown analysis ────────────────────────────────────────────────
    report = analyse(results)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"✅ Analysis saved: {md_path}")

    # Cleanup temp files
    for p in [task_path, context_path]:
        try:
            os.unlink(p)
        except OSError:
            pass

    print("\n" + "=" * 60)
    print("EXPERIMENT COMPLETE")
    print("=" * 60)
    print(report[-2000:])  # Print tail of report


if __name__ == "__main__":
    asyncio.run(main())
