# Project Context — DeepSeek Console App (Quick Reference)

Architecture guidelines: `docs/ARCHITECTURE.md`

## What it is
Console app for streaming chat with DeepSeek Chat Completions API, using an Android-focused agent.

## Run
- `python3 main.py`  
- `python3 -m deepseek_console_app.main`  
- Clean run: `chmod +x scripts/run_clean.sh && ./scripts/run_clean.sh`

## Key Files
- `deepseek_console_app/main.py` — app bootstrap
- `deepseek_console_app/config.py` — config + optional params (code-only)
- `deepseek_console_app/client.py` — streaming HTTP client
- `deepseek_console_app/android_agent.py` — Android-focused agent + system prompt
- `deepseek_console_app/console_app.py` — CLI loop
- `deepseek_console_app/session.py` — message history
- `deepseek_console_app/stream_printer.py` — stall indicator
- `deepseek_console_app/comparing/model_compare.py` — сравнение ответов разных моделей

## Config (env)
Provider selection:
- `PROVIDER` (`deepseek` or `groq`, default `deepseek`)

DeepSeek:
- `DEEPSEEK_API_KEY` (required when provider is `deepseek`)
- `DEEPSEEK_API_TIMEOUT_SECONDS` (default 60)
- `DEEPSEEK_API_MAX_TOKENS` (default 4000)
- `DEEPSEEK_API_MODEL` (default `deepseek-chat`)
- `DEEPSEEK_API_URL` (default `https://api.deepseek.com/v1/chat/completions`)
- `DEEPSEEK_MODELS_URL` (optional; if set, used by `/models`)

Groq:
- `GROQ_API_KEY` (required when provider is `groq`)
- `GROQ_API_TIMEOUT_SECONDS` (default 60)
- `GROQ_API_MAX_TOKENS` (default 4000)
- `GROQ_API_MODEL` (default `moonshotai/kimi-k2-instruct`)
- `GROQ_API_URL` (default `https://api.groq.com/openai/v1/chat/completions`)
- `GROQ_MODELS_URL` (default `https://api.groq.com/openai/v1/models`)
- `GROQ_LLAMA3_1_8B_MODEL` (optional for `model_compare.py`, default `llama-3.1-8b-instant`)
- `GROQ_LLAMA3_1_70B_MODEL` (optional for `model_compare.py`, default `llama-3.1-70b-versatile`)
- `DEEPSEEK_CHAT_MODEL` (optional for `model_compare.py`, default `deepseek-chat`)

## OptionalRequestParams (code-only)
Edit defaults in `deepseek_console_app/config.py`:
`temperature`, `frequency_penalty`, `presence_penalty`, `response_format`, `stop`, `thinking`

## Notes
- Streaming parses `data:` chunks.
- `AndroidAgent` injects an Android-focused `system` prompt for senior Android guidance.
- `/provider` prints current provider and model.
- `/models` lists available models for the current provider (if models endpoint is configured).
- `/clear` clears chat context.
- `/context` shows chat history size.
- `python3 -m deepseek_console_app.comparing.model_compare --prompt "..."` — сравнивает Llama-3.1-8B (weak), Llama-3.1-70B (medium) и DeepSeek (API).
- If behavior seems stale, run clean script (removes `__pycache__`).
