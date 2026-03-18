from dataclasses import dataclass
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_CORPUS_ROOT = _PROJECT_ROOT / "docs" / "corpus"


@dataclass(frozen=True)
class CorpusFile:
    path: Path
    doc_type: str   # "markdown" or "python"
    title: str


CORPUS_FILES: List[CorpusFile] = [
    # ── External articles (markdown) ──────────────────────────────────────
    CorpusFile(_CORPUS_ROOT / "pep8_style_guide.md",               "markdown", "PEP 8 – Style Guide for Python Code"),
    CorpusFile(_CORPUS_ROOT / "retrieval_augmented_generation.md", "markdown", "Information Retrieval"),
    CorpusFile(_CORPUS_ROOT / "transformer_architecture.md",       "markdown", "Transformer (Deep Learning Architecture)"),
    CorpusFile(_CORPUS_ROOT / "large_language_models.md",          "markdown", "Large Language Model"),
    CorpusFile(_CORPUS_ROOT / "python_concurrency_guide.md",       "markdown", "Concurrency in Computing"),
    CorpusFile(_CORPUS_ROOT / "fastapi_overview.md",               "markdown", "FastAPI Overview"),

    # ── Project documentation (markdown) ──────────────────────────────────
    CorpusFile(_PROJECT_ROOT / "README.md",  "markdown", "Project README"),
    CorpusFile(_PROJECT_ROOT / "CLAUDE.md",  "markdown", "CLAUDE Architecture Guide"),

    # ── Project source code (python) ──────────────────────────────────────
    CorpusFile(_PROJECT_ROOT / "deepseek_chat" / "core" / "config.py",           "python", "Core: config.py"),
    CorpusFile(_PROJECT_ROOT / "deepseek_chat" / "core" / "session.py",          "python", "Core: session.py"),
    CorpusFile(_PROJECT_ROOT / "deepseek_chat" / "core" / "memory.py",           "python", "Core: memory.py"),
    CorpusFile(_PROJECT_ROOT / "deepseek_chat" / "core" / "task_state.py",       "python", "Core: task_state.py"),
    CorpusFile(_PROJECT_ROOT / "deepseek_chat" / "agents" / "base_agent.py",     "python", "Agent: base_agent.py"),
    CorpusFile(_PROJECT_ROOT / "deepseek_chat" / "agents" / "strategies.py",     "python", "Agent: strategies.py"),
    CorpusFile(_PROJECT_ROOT / "deepseek_chat" / "web" / "routes.py",            "python", "Web: routes.py"),
    CorpusFile(_PROJECT_ROOT / "deepseek_chat" / "web" / "streaming.py",         "python", "Web: streaming.py"),
    CorpusFile(_PROJECT_ROOT / "mcp_servers" / "scheduler" / "scheduler_store.py", "python", "Scheduler: store.py"),
    CorpusFile(_PROJECT_ROOT / "deepseek_chat" / "core" / "mcp_manager.py",        "python", "Core: mcp_manager.py"),
]


def load_corpus_text(cf: CorpusFile) -> str:
    """Read corpus file text. Returns empty string on error."""
    try:
        return cf.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
