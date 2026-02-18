# 🚀 DeepSeek Console Application

A simple console app to chat with DeepSeek AI via the API (with streaming responses).

## Quick Start

```/dev/null/shell#L1-6
git clone https://github.com/okdiman/deepseek-console-app.git
cd deepseek-console-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and add your key:

```/dev/null/dotenv#L1-1
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

Run:

```/dev/null/shell#L1-1
python3 main.py
```

## Configuration (optional)

Via environment variables:

- `DEEPSEEK_API_KEY` — **required**
- `DEEPSEEK_API_TIMEOUT_SECONDS` — read timeout (default 60)
- `DEEPSEEK_API_MAX_TOKENS` — token limit (default 4000)
- `DEEPSEEK_API_MODEL` — model (default `deepseek-chat`)
- `DEEPSEEK_API_URL` — API URL (default `https://api.deepseek.com/v1/chat/completions`)

## Commands

- Any text — send a request
- `/help` — show help
- `/quit` or `/exit` — exit

## Session Example (streaming)

```/dev/null/console#L1-12
============================================================
🚀 DeepSeek Console Application
============================================================
Commands:
- Type any question to get AI response
- /help - Show this help
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