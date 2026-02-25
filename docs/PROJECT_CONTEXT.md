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

Context persistence:
- `DEEPSEEK_PERSIST_CONTEXT` (default `true`)
- `DEEPSEEK_CONTEXT_PATH` (default `~/.deepseek_console_app/context.json`)
- `DEEPSEEK_CONTEXT_MAX_MESSAGES` (default 40)

## OptionalRequestParams (code-only)
Edit defaults in `deepseek_console_app/config.py`:
`temperature`, `frequency_penalty`, `presence_penalty`, `response_format`, `stop`, `thinking`

## Notes
- Streaming parses `data:` chunks.
- `AndroidAgent` injects an Android-focused `system` prompt for senior Android guidance.
- Local token counting is shown in the CLI: request, full history, and response (uses `tiktoken` if available, otherwise a heuristic).
- API usage tokens (prompt/completion/total) are shown when provided by the provider.
- If context length is exceeded, the client raises a clear `Context length exceeded` error.
- `/provider` prints current provider and model.
- `/models` lists available models for the current provider (if models endpoint is configured).
- `/clear` clears chat context (and overwrites persisted context if enabled).
- `/context` shows chat history size.
- Persisted context loads on startup when `DEEPSEEK_PERSIST_CONTEXT=true`.
- `python3 -m deepseek_console_app.comparing.model_compare --prompt "..."` — сравнивает Llama-3.1-8B (weak), Llama-3.1-70B (medium) и DeepSeek (API).
- If behavior seems stale, run clean script (removes `__pycache__`).


## Maintenance Rule
After any code changes, verify `PROJECT_CONTEXT.md` and update it if needed.

## Persisted Context File (format)
Default path: `~/.deepseek_console_app/context.json`
Structure:
{
  "format_version": 1,
  "provider": "deepseek",
  "model": "deepseek-chat",
  "updated_at": "2025-01-01T12:00:00Z",
  "messages": [
    {"role": "user", "content": "Привет"},
    {"role": "assistant", "content": "Привет! Чем помочь?"}
  ]
}

## Quick Verification
1. Run the app, send a couple of messages.
2. Exit and restart the app — context should be restored.
3. Run `/clear` and restart — context should be empty.
