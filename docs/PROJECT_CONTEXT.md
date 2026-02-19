# Project Context — DeepSeek Console App (Quick Reference)

Architecture guidelines: `docs/ARCHITECTURE.md`

## What it is
Console app for streaming chat with DeepSeek Chat Completions API.

## Run
- `python3 main.py`  
- `python3 -m deepseek_console_app.main`  
- Clean run: `chmod +x scripts/run_clean.sh && ./scripts/run_clean.sh`

## Key Files
- `deepseek_console_app/main.py` — app bootstrap
- `deepseek_console_app/config.py` — config + optional params (code-only)
- `deepseek_console_app/client.py` — streaming HTTP client
- `deepseek_console_app/console_app.py` — CLI loop
- `deepseek_console_app/session.py` — message history
- `deepseek_console_app/stream_printer.py` — stall indicator

## Config (env)
- `DEEPSEEK_API_KEY` (required)
- `DEEPSEEK_API_TIMEOUT_SECONDS` (default 60)
- `DEEPSEEK_API_MAX_TOKENS` (default 4000)
- `DEEPSEEK_API_MODEL` (default `deepseek-chat`)
- `DEEPSEEK_API_URL` (default `https://api.deepseek.com/v1/chat/completions`)

## OptionalRequestParams (code-only)
Edit defaults in `deepseek_console_app/config.py`:
`temperature`, `frequency_penalty`, `presence_penalty`, `response_format`, `stop`, `thinking`

## Notes
- Streaming parses `data:` chunks.
- If behavior seems stale, run clean script (removes `__pycache__`).