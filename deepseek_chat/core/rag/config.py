import os
from dataclasses import dataclass

from dotenv import load_dotenv

from ..paths import DATA_DIR

_DEFAULT_DB = str(DATA_DIR / "rag_index.db")


@dataclass(frozen=True)
class RagConfig:
    # Chunking
    fixed_chunk_size: int       # tokens per chunk (FixedSizeChunker)
    fixed_chunk_overlap: int    # overlap tokens between adjacent chunks

    # Ollama embeddings
    ollama_url: str             # e.g. http://localhost:11434
    ollama_model: str           # e.g. qwen3-embedding:0.6b
    embedding_dim: int          # vector dimension (1024 for qwen3-embedding:0.6b)

    # Storage
    db_path: str                # path to SQLite index file

    # Reranking / filtering
    pre_rerank_top_k: int       # candidates fetched before filtering (should be > RAG_TOP_K)
    reranker_type: str          # "none" | "threshold" | "heuristic"
    reranker_threshold: float   # minimum cosine similarity score to keep a chunk

    # Query rewriting
    query_rewrite_enabled: bool  # rewrite query via LLM before embedding

    # Citations & anti-hallucination (Day 24)
    citations_enabled: bool = True    # inject numbered citation format into system prompt
    idk_threshold: float = 0.45       # max_score below this → "I don't know" response
    weak_context_threshold: float = 0.55  # max_score below this → uncertain response with caveat


def load_rag_config() -> RagConfig:
    load_dotenv()
    return RagConfig(
        fixed_chunk_size=int(os.getenv("RAG_FIXED_CHUNK_SIZE", "400")),
        fixed_chunk_overlap=int(os.getenv("RAG_FIXED_CHUNK_OVERLAP", "50")),
        ollama_url=os.getenv("RAG_OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.getenv("RAG_OLLAMA_MODEL", "qwen3-embedding:0.6b"),
        embedding_dim=int(os.getenv("RAG_EMBEDDING_DIM", "1024")),
        db_path=os.getenv("RAG_DB_PATH", _DEFAULT_DB),
        pre_rerank_top_k=int(os.getenv("RAG_PRE_RERANK_TOP_K", "10")),
        reranker_type=os.getenv("RAG_RERANKER_TYPE", "threshold"),
        reranker_threshold=float(os.getenv("RAG_RERANKER_THRESHOLD", "0.30")),
        query_rewrite_enabled=os.getenv("RAG_QUERY_REWRITE_ENABLED", "false").strip().lower()
        not in {"0", "false", "no", "off"},
        citations_enabled=os.getenv("RAG_CITATIONS_ENABLED", "true").strip().lower()
        not in {"0", "false", "no", "off"},
        idk_threshold=float(os.getenv("RAG_IDK_THRESHOLD", "0.45")),
        weak_context_threshold=float(os.getenv("RAG_WEAK_CONTEXT_THRESHOLD", "0.55")),
    )
