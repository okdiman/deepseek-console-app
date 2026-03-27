# Day 29 — Local LLM Optimization Report

**Model:** `qwen2.5:7b`  
**RAG:** strategy=structure, top_k=3

## Summary

| Profile | KW Hit % | Src % | Avg (s) | Median (s) | tok/s | Timeouts |
|---------|----------|-------|---------|------------|-------|----------|
| `baseline` | 80% | 80% | 3.6 | 3.5 | n/a | 0 |
| `fast` | 63% | 80% | 1.7 | 1.8 | n/a | 0 |
| `quality` | 66% | 80% | 1.7 | 1.8 | n/a | 0 |
| `quality_large` | 66% | 80% | 1.8 | 1.8 | n/a | 0 |

## Profile Descriptions

- **`baseline`**: Default: temp=1.0, max_tokens=4000, num_ctx=default, generic prompt
- **`fast`**: Speed: temp=0.1, max_tokens=512, num_ctx=2048, task prompt
- **`quality`**: Balanced: temp=0.1, max_tokens=1024, num_ctx=4096, task prompt
- **`quality_large`**: Large ctx: temp=0.1, max_tokens=1024, num_ctx=8192, task prompt

## Per-question Results

### Profile: `baseline`

| # | Question | KW hits | Source | Time (s) | tok/s |
|---|----------|---------|--------|----------|-------|
| 1 | What is the PEP 8 recommendation for maximum line  | 3/3 | ✓ | 5.2 | n/a |
| 2 | How does scaled dot-product attention work in tran | 4/4 | ✓ | 2.7 | n/a |
| 3 | What are the main components of Retrieval-Augmente | 2/3 | ✗ | 2.9 | n/a |
| 4 | What is in-context learning in large language mode | 0/3 | ✓ | 2.8 | n/a |
| 5 | What is the difference between threading and multi | 3/3 | ✓ | 4.0 | n/a |
| 6 | How does FastAPI handle request validation? | 2/3 | ✓ | 4.5 | n/a |
| 7 | How does the hook system work in the agent pipelin | 4/4 | ✓ | 4.1 | n/a |
| 8 | What are the states in the task state machine and  | 5/5 | ✓ | 4.0 | n/a |
| 9 | What schedule formats does the background schedule | 3/3 | ✗ | 2.8 | n/a |
| 10 | How is MCP tool execution integrated into the agen | 2/4 | ✓ | 2.5 | n/a |

### Profile: `fast`

| # | Question | KW hits | Source | Time (s) | tok/s |
|---|----------|---------|--------|----------|-------|
| 1 | What is the PEP 8 recommendation for maximum line  | 2/3 | ✓ | 1.9 | n/a |
| 2 | How does scaled dot-product attention work in tran | 3/4 | ✓ | 1.8 | n/a |
| 3 | What are the main components of Retrieval-Augmente | 1/3 | ✗ | 2.0 | n/a |
| 4 | What is in-context learning in large language mode | 0/3 | ✓ | 1.0 | n/a |
| 5 | What is the difference between threading and multi | 0/3 | ✓ | 0.8 | n/a |
| 6 | How does FastAPI handle request validation? | 2/3 | ✓ | 1.8 | n/a |
| 7 | How does the hook system work in the agent pipelin | 3/4 | ✓ | 2.0 | n/a |
| 8 | What are the states in the task state machine and  | 5/5 | ✓ | 1.7 | n/a |
| 9 | What schedule formats does the background schedule | 3/3 | ✗ | 2.1 | n/a |
| 10 | How is MCP tool execution integrated into the agen | 3/4 | ✓ | 1.9 | n/a |

### Profile: `quality`

| # | Question | KW hits | Source | Time (s) | tok/s |
|---|----------|---------|--------|----------|-------|
| 1 | What is the PEP 8 recommendation for maximum line  | 2/3 | ✓ | 1.7 | n/a |
| 2 | How does scaled dot-product attention work in tran | 3/4 | ✓ | 1.8 | n/a |
| 3 | What are the main components of Retrieval-Augmente | 1/3 | ✗ | 2.0 | n/a |
| 4 | What is in-context learning in large language mode | 0/3 | ✓ | 1.0 | n/a |
| 5 | What is the difference between threading and multi | 0/3 | ✓ | 0.8 | n/a |
| 6 | How does FastAPI handle request validation? | 2/3 | ✓ | 1.7 | n/a |
| 7 | How does the hook system work in the agent pipelin | 4/4 | ✓ | 2.4 | n/a |
| 8 | What are the states in the task state machine and  | 5/5 | ✓ | 1.7 | n/a |
| 9 | What schedule formats does the background schedule | 3/3 | ✗ | 2.1 | n/a |
| 10 | How is MCP tool execution integrated into the agen | 3/4 | ✓ | 1.9 | n/a |

### Profile: `quality_large`

| # | Question | KW hits | Source | Time (s) | tok/s |
|---|----------|---------|--------|----------|-------|
| 1 | What is the PEP 8 recommendation for maximum line  | 2/3 | ✓ | 1.7 | n/a |
| 2 | How does scaled dot-product attention work in tran | 3/4 | ✓ | 1.8 | n/a |
| 3 | What are the main components of Retrieval-Augmente | 1/3 | ✗ | 1.9 | n/a |
| 4 | What is in-context learning in large language mode | 0/3 | ✓ | 1.0 | n/a |
| 5 | What is the difference between threading and multi | 0/3 | ✓ | 0.8 | n/a |
| 6 | How does FastAPI handle request validation? | 2/3 | ✓ | 1.7 | n/a |
| 7 | How does the hook system work in the agent pipelin | 4/4 | ✓ | 2.4 | n/a |
| 8 | What are the states in the task state machine and  | 5/5 | ✓ | 1.8 | n/a |
| 9 | What schedule formats does the background schedule | 3/3 | ✗ | 2.1 | n/a |
| 10 | How is MCP tool execution integrated into the agen | 3/4 | ✓ | 2.5 | n/a |
