"""
Indexing pipeline orchestrator.

Loads corpus → chunks → embeds (Ollama) → stores in SQLite.
"""

import time
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from .chunkers import Chunk, FixedSizeChunker, StructureChunker
from .config import RagConfig, load_rag_config
from .corpus import CORPUS_FILES, load_corpus_text
from .embedder import OllamaEmbeddingClient
from .store import clear_strategy, get_stats, init_db, upsert_chunks_bulk


@dataclass
class PipelineResult:
    strategy: str
    total_chunks: int
    total_files: int
    elapsed_seconds: float
    errors: List[str] = field(default_factory=list)


def run_pipeline(
    strategy: Literal["fixed", "structure", "both"] = "both",
    config: Optional[RagConfig] = None,
    verbose: bool = True,
) -> List[PipelineResult]:
    """Index all corpus files with the specified chunking strategy.

    Returns one PipelineResult per strategy run.
    """
    if config is None:
        config = load_rag_config()

    init_db(config.db_path)
    embedder = OllamaEmbeddingClient(config)

    strategies = ["fixed", "structure"] if strategy == "both" else [strategy]
    results: List[PipelineResult] = []

    for strat_name in strategies:
        if verbose:
            print(f"\n[{strat_name}] Starting indexing...")

        chunker: FixedSizeChunker | StructureChunker
        if strat_name == "fixed":
            chunker = FixedSizeChunker(
                chunk_size=config.fixed_chunk_size,
                overlap=config.fixed_chunk_overlap,
            )
        else:
            chunker = StructureChunker(max_tokens=config.fixed_chunk_size * 2)

        deleted = clear_strategy(strat_name, config.db_path)
        if verbose and deleted:
            print(f"[{strat_name}] Cleared {deleted} existing chunks")

        all_chunks: List[Chunk] = []
        errors: List[str] = []
        t0 = time.monotonic()

        for cf in CORPUS_FILES:
            text = load_corpus_text(cf)
            if not text:
                errors.append(f"{cf.path.name}: empty or unreadable")
                continue
            try:
                source = str(cf.path)
                chunks = chunker.chunk(text, source, cf.title)
                all_chunks.extend(chunks)
                if verbose:
                    print(f"  {cf.path.name}: {len(chunks)} chunks")
            except Exception as exc:
                errors.append(f"{cf.path.name}: {exc}")

        if not all_chunks:
            results.append(PipelineResult(
                strategy=strat_name,
                total_chunks=0,
                total_files=len(CORPUS_FILES),
                elapsed_seconds=time.monotonic() - t0,
                errors=errors,
            ))
            continue

        # Embed in batches
        texts = [c.text for c in all_chunks]
        all_embeddings: List[List[float]] = []

        if verbose:
            print(f"[{strat_name}] Embedding {len(texts)} chunks via Ollama...")

        batch_size = 32
        for i in range(0, len(texts), batch_size):
            batch = texts[i: i + batch_size]
            vecs = embedder.embed(batch)
            all_embeddings.extend(vecs)
            if verbose:
                done = min(i + batch_size, len(texts))
                print(f"  embedded {done}/{len(texts)}", end="\r", flush=True)

        if verbose:
            print()

        # Persist all chunks in a single transaction
        upsert_chunks_bulk(all_chunks, all_embeddings, config.db_path)

        elapsed = time.monotonic() - t0
        results.append(PipelineResult(
            strategy=strat_name,
            total_chunks=len(all_chunks),
            total_files=len(CORPUS_FILES),
            elapsed_seconds=elapsed,
            errors=errors,
        ))

        if verbose:
            print(
                f"[{strat_name}] Done: {len(all_chunks)} chunks "
                f"in {elapsed:.1f}s"
            )
            if errors:
                for e in errors:
                    print(f"  WARNING: {e}")

    return results
