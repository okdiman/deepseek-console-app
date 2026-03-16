import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_DEFAULT_DB = str(_PROJECT_ROOT / "experiments" / "rag_compare" / "data" / "doc_index.db")


@dataclass(frozen=True)
class RagConfig:
    # Chunking
    fixed_chunk_size: int       # tokens per chunk (FixedSizeChunker)
    fixed_chunk_overlap: int    # overlap tokens between adjacent chunks

    # Ollama embeddings
    ollama_url: str             # e.g. http://localhost:11434
    ollama_model: str           # e.g. nomic-embed-text
    embedding_dim: int          # vector dimension (768 for nomic-embed-text)

    # Storage
    db_path: str                # path to SQLite index file


def load_rag_config() -> RagConfig:
    load_dotenv()
    return RagConfig(
        fixed_chunk_size=int(os.getenv("RAG_FIXED_CHUNK_SIZE", "400")),
        fixed_chunk_overlap=int(os.getenv("RAG_FIXED_CHUNK_OVERLAP", "50")),
        ollama_url=os.getenv("RAG_OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.getenv("RAG_OLLAMA_MODEL", "nomic-embed-text"),
        embedding_dim=int(os.getenv("RAG_EMBEDDING_DIM", "768")),
        db_path=os.getenv("RAG_DB_PATH", _DEFAULT_DB),
    )
