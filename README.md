# 🚀 DeepSeek Chat

A simple console app to chat with DeepSeek AI via the API (with streaming responses).

## Quick Start

```/dev/null/shell#L1-6
git clone https://github.com/okdiman/deepseek-chat.git
cd deepseek-chat
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Project structure (main code is now in packages):
```/dev/null/tree#L1-17
deepseek-chat/
  deepseek_chat/
    agents/
      __init__.py
      android_agent.py
      general_agent.py
    core/
      client.py
      config.py
      session.py
      stream_printer.py
      token_counter.py
      comparing/
    console/
      app.py
      main.py
    web/
      app.py
```

Open `.env` and add your key(s) and provider:

```/dev/null/dotenv#L1-4
PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

Run:

```/dev/null/shell#L1-5
# console
python3 -m deepseek_chat.console.main
# web UI
python3 -m deepseek_chat.web.app
```

Clean run (removes `__pycache__` and disables bytecode caching):

```/dev/null/shell#L1-2
chmod +x scripts/run_clean.sh
./scripts/run_clean.sh
```

Project context (quick onboarding): `docs/PROJECT_CONTEXT.md`

## Configuration (optional)

Via environment variables:

- `PROVIDER` — `deepseek` or `groq` (default `deepseek`)

DeepSeek:
- `DEEPSEEK_API_KEY` — **required** when `PROVIDER=deepseek`
- `DEEPSEEK_API_TIMEOUT_SECONDS` — read timeout (default 60)
- `DEEPSEEK_API_MAX_TOKENS` — token limit (default 4000)
- `DEEPSEEK_API_MODEL` — model (default `deepseek-chat`)
- `DEEPSEEK_API_URL` — API URL (default `https://api.deepseek.com/v1/chat/completions`)
- `DEEPSEEK_MODELS_URL` — models endpoint for `/models` (optional)
- `DEEPSEEK_WEB_CONTEXT_PATH` — optional override for web UI context path

Context Compression:
- `DEEPSEEK_COMPRESSION_ENABLED` — enable/disable context compression (default `true`)
- `DEEPSEEK_COMPRESSION_THRESHOLD` — messages before triggering compression (default `10`)
- `DEEPSEEK_COMPRESSION_KEEP` — newest messages to keep raw after compression (default `4`)

Groq:
- `GROQ_API_KEY` — **required** when `PROVIDER=groq`
- `GROQ_API_TIMEOUT_SECONDS` — read timeout (default 60)
- `GROQ_API_MAX_TOKENS` — token limit (default 4000)
- `GROQ_API_MODEL` — model (default `moonshotai/kimi-k2-instruct`)
- `GROQ_API_URL` — API URL (default `https://api.groq.com/openai/v1/chat/completions`)
- `GROQ_MODELS_URL` — models endpoint for `/models` (default `https://api.groq.com/openai/v1/models`)

## OptionalRequestParams

Optional request parameters live in `deepseek_chat/core/config.py` inside the `OptionalRequestParams` dataclass.  
These are wired into the request payload in `deepseek_chat/core/client.py`.

You can tweak:

- `temperature` (float, typically 0..2) — controls randomness/creativity of output.
- `frequency_penalty` (float, -2..2) — penalize repeated tokens.
- `presence_penalty` (float, -2..2) — encourage new topics.
- `response_format` (`{"type": "text"}` or `{"type": "json_object"}`) — force JSON output if set to `json_object` (remember to instruct JSON in messages).
- `stop` (string or list of strings) — stop sequences for generation.
- `thinking` (`{"type": "enabled"}` or `{"type": "disabled"}`) — enable/disable reasoning mode.

Edit the defaults directly in `OptionalRequestParams` to experiment with behavior.

## Web UI

Run:

```/dev/null/shell#L1-1
python3 -m deepseek_chat.web.app
```

Notes:
- Streams via SSE at `/stream`
- Agent selector; responses show the active agent name
- Stats panel shows local tokens, API usage, cost, and session cost (auto-hides when empty)

## Commands

- Any text — send a request
- /help — show help
- /temps [temps] [question] — compare temperatures (default 0,0.7,1.2)
- /provider — show current provider and model
- /models — list available models for current provider
- /quit or /exit — exit

## Model Comparison

Run:

```/dev/null/shell#L1-1
python3 -m deepseek_chat.core.comparing.model_compare --prompt "..."
```


## Session Example (streaming)

```/dev/null/console#L1-14
============================================================
🚀 DeepSeek Chat
============================================================
Commands:
- Type any question to get AI response
- /help - Show this help
- /temps [temps] [question] - Compare temperatures (default 0,0.7,1.2)
- /provider - Show current provider and model
- /models - List available models for current provider
- /quit or /exit - Exit application
============================================================

Your message: Hi! Explain what blockchain is.
🤖 AI: Blockchain is a distributed database...
```

## Common Issues

- **Error `DEEPSEEK_API_KEY not found`** — check `.env` and the key.
- **Network errors** — check your internet connection and key validity.

---
MIT License