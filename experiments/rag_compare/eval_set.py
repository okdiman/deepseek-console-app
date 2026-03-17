"""
10 control questions for RAG vs no-RAG benchmark.

Each EvalCase has:
  - question:          the query sent to the LLM
  - expected_keywords: keywords that should appear in a correct answer
  - expected_sources:  corpus filenames that should be retrieved
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class EvalCase:
    question: str
    expected_keywords: List[str]
    expected_sources: List[str]  # corpus filenames (basename only)


EVAL_SET: List[EvalCase] = [
    # ── External corpus ───────────────────────────────────────────────────
    EvalCase(
        question="What is the PEP 8 recommendation for maximum line length?",
        expected_keywords=["79", "line length", "characters"],
        expected_sources=["pep8_style_guide.md"],
    ),
    EvalCase(
        question="How does scaled dot-product attention work in transformers?",
        expected_keywords=["query", "key", "value", "softmax"],
        expected_sources=["transformer_architecture.md"],
    ),
    EvalCase(
        question="What are the main components of Retrieval-Augmented Generation?",
        expected_keywords=["retriever", "generator", "knowledge"],
        expected_sources=["retrieval_augmented_generation.md"],
    ),
    EvalCase(
        question="What is in-context learning in large language models?",
        expected_keywords=["few-shot", "prompt", "examples"],
        expected_sources=["large_language_models.md"],
    ),
    EvalCase(
        question="What is the difference between threading and multiprocessing in Python?",
        expected_keywords=["GIL", "Global Interpreter Lock", "process"],
        expected_sources=["python_concurrency_guide.md"],
    ),
    EvalCase(
        question="How does FastAPI handle request validation?",
        expected_keywords=["Pydantic", "type hints", "validation"],
        expected_sources=["fastapi_overview.md"],
    ),
    # ── Project corpus ────────────────────────────────────────────────────
    EvalCase(
        question="How does the hook system work in the agent pipeline?",
        expected_keywords=["before_stream", "after_stream", "AgentHook", "system prompt"],
        expected_sources=["base_agent.py", "CLAUDE.md"],
    ),
    EvalCase(
        question="What are the states in the task state machine and how do transitions work?",
        expected_keywords=["planning", "execution", "validation", "idle", "done"],
        expected_sources=["task_state.py", "CLAUDE.md"],
    ),
    EvalCase(
        question="What schedule formats does the background scheduler support?",
        expected_keywords=["once", "every", "daily"],
        expected_sources=["scheduler_store.py"],
    ),
    EvalCase(
        question="How is MCP tool execution integrated into the agent stream loop?",
        expected_keywords=["MCPManager", "tool", "prefix", "server_id"],
        expected_sources=["CLAUDE.md", "base_agent.py"],
    ),
]
