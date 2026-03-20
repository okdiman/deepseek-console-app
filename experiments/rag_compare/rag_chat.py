#!/usr/bin/env python3
"""
RAG Mini-Chat — Day 25.

Production-like interactive chat that combines:
  - Conversation history (ChatSession with persistence)
  - RAG retrieval with reranking and citations (RagHook)
  - Long-term + working memory (MemoryInjectionHook)
  - Dialogue task memory: goal, clarifications, constraints, explored topics
    (DialogueTaskHook)
  - Sources printed after every response

Usage:
    python3 experiments/rag_compare/rag_chat.py

Commands:
    /task      — show current dialogue task memory
    /memory    — show current working + long-term memory
    /clear     — clear conversation history and dialogue task memory
    /help      — show this help
    /quit      — exit
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from deepseek_chat.agents.hooks.dialogue_task_hook import DialogueTaskHook
from deepseek_chat.agents.hooks.invariant_guard import InvariantGuardHook
from deepseek_chat.agents.hooks.memory_injection import MemoryInjectionHook
from deepseek_chat.agents.hooks.rag_hook import RagHook
from deepseek_chat.agents.hooks.user_profile import UserProfileHook
from deepseek_chat.agents.base_agent import BaseAgent
from deepseek_chat.core.client import DeepSeekClient
from deepseek_chat.core.config import load_config
from deepseek_chat.core.dialogue_task import DialogueTask
from deepseek_chat.core.memory import MemoryStore
from deepseek_chat.core.session import ChatSession


# ── Agent ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a knowledgeable assistant with access to a curated knowledge base "
    "on Python, transformers, RAG systems, and concurrency. "
    "Always ground your answers in retrieved sources and cite them using [N] notation. "
    "Keep track of the conversation goal and mark progress with task memory markers. "
    "Be concise, precise, and never hallucinate beyond the provided context."
)


class RagChatAgent(BaseAgent):
    SYSTEM_PROMPT = SYSTEM_PROMPT


# ── Display helpers ────────────────────────────────────────────────────────────

def _print_sources(chunks: list) -> None:
    if not chunks:
        return
    print("\n\033[90m" + "─" * 50)
    print("📚 Sources retrieved:")
    for i, chunk in enumerate(chunks, 1):
        title = chunk.get("title", "")
        section = chunk.get("section", "")
        source = Path(chunk.get("source", "")).name
        score = chunk.get("score", 0.0)
        label = f"{title} › {section}" if section else f"{title} ({source})"
        print(f"  [{i}] {label}  (score={score:.3f})")
    print("─" * 50 + "\033[0m")


def _print_task(task: DialogueTask) -> None:
    print("\n\033[94m" + task.get_summary() + "\033[0m")


def _print_memory(mem: MemoryStore) -> None:
    print("\n\033[93m── Memory ────────────────────────────────────────")
    if mem.long_term_memory:
        print("Long-term:")
        for i, f in enumerate(mem.long_term_memory, 1):
            print(f"  {i}. {f}")
    if mem.working_memory:
        print("Working:")
        for i, f in enumerate(mem.working_memory, 1):
            print(f"  {i}. {f}")
    if not mem.long_term_memory and not mem.working_memory:
        print("(empty)")
    print("──────────────────────────────────────────────────\033[0m")


def _print_welcome() -> None:
    print("=" * 60)
    print("🧠 RAG Mini-Chat  (Day 25)")
    print("=" * 60)
    print("Commands: /task  /summary  /memory  /clear  /help  /quit")
    print("Sources are shown after every response.")
    print("=" * 60)


def _print_help() -> None:
    print(
        "\nCommands:\n"
        "  /task     — show full dialogue task memory\n"
        "  /summary  — show compact conversation summary\n"
        "  /memory   — show working + long-term memory\n"
        "  /clear    — clear conversation history and dialogue task\n"
        "  /help     — this message\n"
        "  /quit     — exit\n"
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

async def main() -> None:
    config = load_config()
    client = DeepSeekClient(config)
    session = ChatSession(max_messages=config.context_max_messages)

    rag_hook = RagHook()
    hooks = [
        rag_hook,
        MemoryInjectionHook(),
        DialogueTaskHook(),
        UserProfileHook(),
        InvariantGuardHook(),
    ]
    agent = RagChatAgent(client, session, hooks=hooks)

    # Load persisted session
    if config.persist_context:
        session.load(config.context_path)

    _print_welcome()
    session_cost = 0.0

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("/quit", "/exit", "quit", "exit"):
            print("👋 Goodbye!")
            break

        if cmd in ("/help", "help"):
            _print_help()
            continue

        if cmd == "/task":
            _print_task(DialogueTask.load())
            continue

        if cmd == "/summary":
            task = DialogueTask.load()
            n = len(session.messages())
            print(f"\n\033[94m{task.get_summary()}")
            print(f"Turns      : {n // 2}")
            print(f"\033[0m", end="")
            continue

        if cmd == "/memory":
            _print_memory(MemoryStore.load())
            continue

        if cmd == "/clear":
            session.clear()
            session_cost = 0.0
            task = DialogueTask.load()
            task.clear()
            task.save()
            if config.persist_context:
                session.save(config.context_path, config.provider, config.model)
            print("🧹 Conversation and task memory cleared.")
            continue

        # ── Stream response ────────────────────────────────────────────────
        print("\nAssistant: ", end="", flush=True)
        full_response: list[str] = []

        try:
            async for chunk in agent.stream_reply(user_input):
                print(chunk, end="", flush=True)
                full_response.append(chunk)
        except Exception as exc:
            print(f"\n❌ Error: {exc}")
            continue

        print()  # newline after streaming

        # Show RAG sources
        _print_sources(rag_hook.last_chunks)

        # Persist session
        if config.persist_context:
            session.save(config.context_path, config.provider, config.model)

        # Cost tracking
        metrics = client.last_metrics()
        if metrics:
            duration_ms = metrics.duration_seconds * 1000.0
            cost = metrics.cost_usd or 0.0
            session_cost += cost
            tokens = metrics.total_tokens or "?"
            print(
                f"\033[90m⏱  {duration_ms:.0f}ms | tokens={tokens}"
                f" | cost=${cost:.5f} | session=${session_cost:.5f}\033[0m"
            )


if __name__ == "__main__":
    asyncio.run(main())
