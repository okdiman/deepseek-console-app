# RAG — How It Works

This document describes the full Retrieval-Augmented Generation (RAG) pipeline in this project: from indexing documents to injecting context into every LLM request.

---

## Overview

RAG prevents the model from hallucinating by grounding every answer in documents retrieved from a local index. Before each LLM call, the agent searches the index, finds the most relevant chunks, assesses confidence in those results, and injects them into the system prompt with instructions on how to cite and what to say if context is too weak.

```
User query
    │
    ▼
[RagHook.before_stream]
    │
    ├─ 1. Query enrichment (goal prefix)
    ├─ 2. Query rewriting (optional, LLM)
    ├─ 3. Embed query → Ollama
    ├─ 4. Fetch candidates from SQLite index
    ├─ 5. Rerank / filter
    ├─ 6. Assess confidence (empty / weak / uncertain / confident)
    └─ 7. Format citation block → append to system prompt
                │
                ▼
         LLM answers with citations [1], [2], ...
```

---

## Package Structure

```
deepseek_chat/core/rag/
├── config.py          — RagConfig dataclass + load_rag_config()
├── corpus.py          — CORPUS_FILES list (what gets indexed)
├── chunkers.py        — FixedSizeChunker, StructureChunker
├── embedder.py        — OllamaEmbeddingClient
├── store.py           — SQLite store: upsert, search_by_embedding, get_stats
├── reranker.py        — ThresholdFilter, HeuristicReranker, rerank_and_filter()
├── query_rewriter.py  — QueryRewriter (LLM expand + heuristic clean)
├── citations.py       — assess_confidence(), format_citation_block()
└── pipeline.py        — run_pipeline(strategy) — offline indexing orchestrator
```

The hook that ties it all together at runtime:
```
deepseek_chat/agents/hooks/rag_hook.py  — RagHook (before_stream)
```

---

## Step 1 — Corpus

`corpus.py` declares `CORPUS_FILES`: 25 documents (markdown articles + project source files + internal docs).

| Category | Files |
|----------|-------|
| External articles | PEP 8, RAG overview, Transformer architecture, LLMs, Python concurrency, FastAPI |
| Project docs | README.md, CLAUDE.md |
| Internal `_HOW_IT_WORKS.md` | agents, core, core/memory, core/mcp, core/rag, mcp_servers, mcp_servers/scheduler |
| Project source | config.py, session.py, memory.py, task_state.py, base_agent.py, strategies.py, routes.py, streaming.py, scheduler_store.py, mcp_manager.py |

Documents are downloaded once via `scripts/download_corpus.py` and stored in `docs/corpus/`.

---

## Step 2 — Chunking

`chunkers.py` provides two strategies for splitting documents into searchable pieces:

### FixedSizeChunker
- Sliding window over **tiktoken tokens** (cl100k_base encoding)
- Default: **400 tokens per chunk**, **50 token overlap** between adjacent chunks
- Produces IDs like `pep8_style_guide_md_fixed_0`, `..._fixed_1`, ...
- Used for all document types as baseline; StructureChunker falls back to it for unknown formats

### StructureChunker
- **Markdown** (`.md`): splits on `##` and `###` ATX headings; each section becomes one chunk
- **Python** (`.py`): splits on top-level `class` and `function` definitions via AST; large classes are split method-by-method
- Sections exceeding `max_tokens=800` are sub-chunked with FixedSizeChunker while preserving the section name
- Produces IDs like `transformer_architecture_md_structure_3`

Each `Chunk` carries:
- `chunk_id` — unique string ID
- `source` — relative file path
- `title` — human-readable document name
- `section` — heading text or `ClassName.method` (empty for fixed chunks)
- `strategy` — `"fixed"` or `"structure"`
- `text` — chunk content

**Which strategy to use?** Run indexing with `--strategy both` to index all documents with both strategies and let retrieval pick the best match per search.

---

## Step 3 — Embedding

`embedder.py` wraps the Ollama embedding API.

- Model: **nomic-embed-text** (768-dimensional vectors)
- Endpoint: `POST http://localhost:11434/api/embed`
- Batching: chunks are embedded in configurable batch sizes
- `health_check()` pings Ollama before the first use; returns `False` if unreachable

Embeddings are stored alongside chunk text in SQLite so re-embedding is only needed on corpus changes.

---

## Step 4 — Storage (SQLite Index)

`store.py` manages a SQLite database at `experiments/rag_compare/data/doc_index.db`.

Schema (conceptually):
```sql
chunks(chunk_id, source, title, section, strategy, index, text, embedding_blob)
```

Key functions:
- `upsert_chunk(db_path, chunk)` — insert or replace a chunk with its embedding
- `search_by_embedding(vec, top_k, strategy, db_path)` — cosine similarity search filtered by strategy
- `get_stats(db_path)` — returns `{"total": N, "fixed": N, "structure": N}`

Cosine similarity is computed in Python over all stored vectors (no FAISS/ANN — suitable for corpora up to ~10k chunks).

---

## Step 5 — Indexing Pipeline (offline)

`pipeline.py` orchestrates corpus indexing. Run via:

```bash
python3 experiments/rag_compare/cli.py index                 # default strategy
python3 experiments/rag_compare/cli.py index --strategy both # index with both chunkers
```

For each `CorpusFile`:
1. Read document text
2. Chunk with the selected strategy
3. Embed all chunks in batches
4. Upsert into SQLite

This is a one-time (or on-change) operation. The index persists between app restarts.

---

## Step 6 — Runtime: RagHook

`RagHook` is an `AgentHook` whose `before_stream` method runs before every LLM call. It is registered in the agent's hook list and receives the current user input and system prompt.

### Readiness check (lazy, once per process)

On the first call, `_check_ready()` verifies:
1. `RAG_ENABLED=true` (env)
2. Index is non-empty (`get_stats().total > 0`)
3. Ollama is reachable (`embedder.health_check()`)

If any check fails, the hook silently returns the unchanged system prompt. If Ollama goes down later, `_ready` is reset to `None` so the check runs again next time.

### Pipeline inside before_stream

**Step 6a — Query enrichment**

Short follow-up questions (≤5 words) are enriched with the current `DialogueTask` goal:

```
"зачем sqrt(d_k)?"
→ "понять механизм внимания: зачем sqrt(d_k)?"
```

This improves retrieval for short contextual questions that lack enough keywords on their own. Long queries (>12 words) already carry enough context and are left unchanged.

**Language guard:** Enrichment is skipped when the goal and the query are in different scripts (e.g. Cyrillic goal + Latin query). Mixing scripts in the embedding query degrades retrieval quality, so in that case the raw user query is used as-is.

**Step 6b — Query rewriting (optional)**

If `RAG_QUERY_REWRITE_ENABLED=true`, `QueryRewriter.rewrite()` makes a short LLM call to expand the query with technical synonyms while preserving all original words. Falls back to the original on error or if the expanded query loses too many original keywords (overlap < 50%).

Alternatively, `QueryRewriter.clean()` strips conversational filler ("can you tell me", "what is", etc.) without an LLM call.

**Step 6c — Embed**

The (possibly enriched/rewritten) query is embedded via Ollama → 768-dim vector.

**Step 6d — Fetch candidates**

`search_by_embedding()` retrieves `RAG_PRE_RERANK_TOP_K` (default: 10) candidates from SQLite. These are more than the final `RAG_TOP_K` (default: 3) to give the reranker enough to work with.

**Step 6e — Rerank / filter**

`rerank_and_filter()` applies the configured strategy:

| `RAG_RERANKER_TYPE` | Behavior |
|---------------------|----------|
| `threshold` | Drop chunks with cosine score < `RAG_RERANKER_THRESHOLD` (default: 0.30) |
| `heuristic` | Boost score by keyword overlap (up to +30%), then apply threshold |
| `none` | Pass-through, no filtering |

After filtering, the top `RAG_TOP_K` chunks are kept. The `FilterResult` also records `pre_filter_count` and `post_filter_count` for debugging.

The final chunks are saved to `self.last_chunks` for display in CLI tools.

---

## Step 7 — Citation Block and Anti-Hallucination

`citations.py` formats the retrieved chunks and selects a behavioral instruction for the LLM based on retrieval confidence.

### Confidence assessment

`assess_confidence()` looks at the **maximum cosine score** among the final chunks:

| Level | Condition | LLM instruction | MCP tools offered? |
|-------|-----------|-----------------|-------------------|
| `empty` | No chunks passed the filter | "Say I don't know. Do not answer from general knowledge." | Yes |
| `weak` | `max_score < RAG_IDK_THRESHOLD` (default: 0.45) | "Say I don't know. Mention what weak context was found." | Yes |
| `uncertain` | `max_score < RAG_WEAK_CONTEXT_THRESHOLD` (default: 0.55) | "Answer from context only. Cite sources. Add confidence caveat." | Yes |
| `confident` | `max_score ≥ 0.55` | "Answer from context only. Cite every claim with [N]. Add Sources block." | **No** — `suppress_tools=True` |

When `suppress_tools=True`, `BaseAgent` does not pass MCP tools to the LLM for that request. This gives the local index priority: external tools (deepwiki, search, etc.) are only offered when RAG could not find a confident answer locally.

### Citation block format

For non-empty contexts, the block injected into the system prompt looks like:

```
---
RETRIEVED CONTEXT (from local document index):

[1] Transformer (Deep Learning Architecture) | docs/corpus/transformer_architecture.md § Scaled dot-product attention | score=0.741 | id=transformer_architecture_md_structure_5
    "The attention function maps a query and a set of key-value pairs..."

[2] ...

INSTRUCTION (HIGH CONFIDENCE):
Answer based ONLY on the context provided above. You MUST:
  1. Cite every factual claim with [N] (e.g. "According to [1]...").
  2. Include at least one direct quote per cited source.
  3. End with a "Sources:" section listing all cited chunks by ID.
  4. Do NOT add information not present in the retrieved context.
---
```

When `RAG_CITATIONS_ENABLED=false`, a simplified block without citation instructions is used.

---

## Configuration Reference

All settings are env vars (copy `.env.example` to `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_ENABLED` | `true` | Master switch |
| `RAG_TOP_K` | `3` | Final number of chunks injected into prompt |
| `RAG_SEARCH_STRATEGY` | `structure` | Which index to search: `fixed`, `structure` |
| `RAG_PRE_RERANK_TOP_K` | `10` | Candidate pool size before filtering (must be ≥ RAG_TOP_K) |
| `RAG_RERANKER_TYPE` | `threshold` | `none` / `threshold` / `heuristic` |
| `RAG_RERANKER_THRESHOLD` | `0.30` | Min cosine score to keep a chunk |
| `RAG_QUERY_REWRITE_ENABLED` | `false` | LLM-based query expansion |
| `RAG_CITATIONS_ENABLED` | `true` | Numbered citations + anti-hallucination instructions |
| `RAG_IDK_THRESHOLD` | `0.45` | Below this → "I don't know" |
| `RAG_WEAK_CONTEXT_THRESHOLD` | `0.55` | Below this → answer with caveat |
| `RAG_FIXED_CHUNK_SIZE` | `400` | Tokens per chunk (FixedSizeChunker) |
| `RAG_FIXED_CHUNK_OVERLAP` | `50` | Overlap tokens between chunks |
| `RAG_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `RAG_OLLAMA_MODEL` | `nomic-embed-text` | Embedding model |
| `RAG_EMBEDDING_DIM` | `768` | Vector dimension |
| `RAG_DB_PATH` | `experiments/rag_compare/data/doc_index.db` | SQLite index path |

---

## Integration with DialogueTask

`RagHook` optionally reads `DialogueTask` (conversation memory) to enrich short follow-up queries with the user's current goal. This is a one-way dependency: RAG → DialogueTask. DialogueTask itself lives in `deepseek_chat/core/dialogue_task.py` and is not part of the RAG package.

The enrichment is intentionally lightweight — it only fires for short queries (≤12 words) and fails silently if DialogueTask is unavailable.

---

## Graceful Degradation

The entire RAG pipeline degrades gracefully at every failure point:

| Failure | Behavior |
|---------|----------|
| `RAG_ENABLED=false` | Hook returns immediately, no retrieval |
| Ollama not running | `_ready=False`, hook passes system prompt unchanged |
| Index empty | `_ready=False`, hook passes system prompt unchanged |
| Embedding fails | Exception caught, `_ready=None` (retry next turn), system prompt unchanged |
| No chunks pass filter | `empty` confidence → IDK instruction injected |
| Query rewrite fails | Falls back to original query |

The LLM always gets a coherent system prompt regardless of RAG availability.

---

## Quick Start

```bash
# 1. Start Ollama with the embedding model
ollama pull nomic-embed-text
ollama serve

# 2. Download corpus documents (run once)
python3 scripts/download_corpus.py

# 3. Index with both chunking strategies
python3 experiments/rag_compare/cli.py index --strategy both

# 4. Verify index stats
python3 experiments/rag_compare/cli.py stats

# 5. Test retrieval
python3 experiments/rag_compare/cli.py search --query "how does attention work?"

# 6. Run RAG mini-chat
python3 experiments/rag_compare/rag_chat.py
```
