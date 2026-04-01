# DeepSeek Console App — Support FAQ

Frequently asked questions for users of the DeepSeek Console App (also known as the AI Chat Platform).

---

## Authentication & API Keys

### Q: I get a 401 Unauthorized error. What should I do?

A 401 error means your API key is missing, expired, or invalid. Steps to resolve:

1. Check that your `.env` file contains the correct key for your active provider:
   - DeepSeek: `DEEPSEEK_API_KEY=sk-...`
   - Groq: `GROQ_API_KEY=gsk_...`
   - Ollama: no key required
2. Ensure you copied the full key without extra spaces or line breaks.
3. If the key was recently rotated, regenerate it in your provider's dashboard and update `.env`.
4. Restart the app after updating `.env` — keys are loaded at startup.

### Q: My API key stopped working overnight. Why?

API keys can be revoked by the provider (DeepSeek, Groq) due to:
- Billing issues (overdue payment, plan expiry)
- Suspicious activity or policy violation
- Manual rotation in the provider dashboard

Check the provider's dashboard for key status, then update `.env` with a new key.

### Q: Can I use the app without an API key?

Yes — switch to the Ollama provider (`PROVIDER=ollama` in `.env`). Ollama runs models locally and requires no API key. You need Ollama installed and a model pulled (e.g. `ollama pull qwen2.5:7b`).

---

## Configuration & Providers

### Q: How do I switch from DeepSeek to Ollama (local LLM)?

Set the following in your `.env` file:

```dotenv
PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

Then restart the app. No API key is needed for Ollama. Make sure Ollama is running (`ollama serve`).

### Q: How do I switch providers at runtime without restarting?

Use the UI toggle buttons (DeepSeek ↔ Ollama) in the chat input bar, or call the API:

```
POST /config/provider
{"provider": "ollama"}
```

### Q: How do I configure Groq?

```dotenv
PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_API_MODEL=moonshotai/kimi-k2-instruct
```

### Q: My context (chat history) disappears after restart.

Make sure `DEEPSEEK_PERSIST_CONTEXT=true` is set in `.env`. History is saved to `~/.deepseek_chat/context.json` (console) or the path set in `DEEPSEEK_WEB_CONTEXT_PATH` (web).

Common causes of history loss:
- `DEEPSEEK_PERSIST_CONTEXT` is not set or set to `false`
- The context file path is different between runs
- The `/clear` command was used, which wipes the history file

---

## RAG (Retrieval-Augmented Generation)

### Q: The RAG search returns no results after re-indexing.

Possible causes:
1. **Ollama is not running** — RAG embedding requires a local Ollama instance. Start it with `ollama serve`.
2. **Wrong model** — the embedding model must be available in Ollama. Pull it: `ollama pull nomic-embed-text`.
3. **Empty corpus** — download corpus documents first: `python3 scripts/download_corpus.py`.
4. **Stale index** — delete `data/rag_index.db` and re-run `python3 experiments/rag_compare/cli.py index`.

### Q: How do I enable or disable RAG?

Set `RAG_ENABLED=true` or `RAG_ENABLED=false` in `.env`. RAG is used by PythonAgent and DevHelpAgent. GeneralAgent does not use RAG.

### Q: How many results does RAG return?

Controlled by `RAG_TOP_K` (default: 3). Increase it for more context, decrease for faster responses. The pre-rerank pool size is `RAG_PRE_RERANK_TOP_K` (default: 10).

---

## Scheduler

### Q: My scheduled tasks are not executing.

1. **Scheduler runner not started** — the scheduler runner starts automatically with the web app (`python3 -m deepseek_chat.web.app`). It does NOT run in the console CLI.
2. **Task is paused** — check task status: use the `list_scheduled_tasks` MCP tool or inspect `~/.deepseek_chat/scheduler.db`.
3. **Next run time is in the future** — tasks with `once` schedule run at the specified time. Check `next_run_at` in the database.
4. **BackgroundAgent error** — check app logs for errors from the scheduler runner.

### Q: What schedule formats are supported?

- `once` — run once at a specified datetime
- `every_Nm` — repeat every N minutes (e.g. `every_30m`)
- `every_Nh` — repeat every N hours (e.g. `every_2h`)
- `daily_HH:MM` — run daily at a specific time (e.g. `daily_09:00`)

---

## MCP Servers

### Q: The filesystem / MCP server fails to start ("connection refused").

MCP servers run as subprocesses. Common causes:
1. **Python path issue** — MCP servers need `deepseek_chat` importable. The app sets `PYTHONPATH` automatically for builtin servers. If running manually, set `PYTHONPATH=<project_root>`.
2. **Port conflict** — MCP servers use stdio transport (not TCP), so port conflicts don't apply. If you see a port error, it's likely from a different process.
3. **Crash on startup** — run the server manually to see the error: `python3 mcp_servers/filesystem_server.py`. Check for missing dependencies.
4. **Auto-restart limit** — servers auto-restart up to 5 times. After that, they stay stopped. Restart the app to reset.

### Q: How do I add a custom MCP server?

Use the MCP management UI or the API endpoint `POST /mcp/servers`. Provide:
- `id`: unique identifier
- `name`: display name
- `command`: executable (e.g. `python3`)
- `args`: list of arguments (e.g. `["path/to/server.py"]`)

### Q: What MCP tools are available?

Built-in tools by server:
- **Filesystem**: `read_file`, `list_directory`, `search_in_files`, `propose_write`, `propose_edit`, `propose_delete`, `run_tests`
- **Git**: `get_current_branch`, `get_recent_commits`, `list_changed_files`, `get_file_diff`, `get_project_structure`
- **Scheduler**: `create_scheduled_task`, `list_scheduled_tasks`, `pause_task`, `resume_task`, `delete_task`
- **CRM**: `get_ticket`, `get_user`, `list_open_tickets`, `search_tickets`, `update_ticket_status`

---

## Billing & Plans

### Q: My account was suspended. What should I do?

Account suspension can occur due to:
- Overdue payment or expired credit card
- Violation of terms of service
- Unusual activity detected by the system

Contact support at support@example.com with your account email. Provide your user ID if available.

### Q: I'm on the Enterprise plan but getting rate limit errors (429).

Enterprise plans have higher rate limits but they are not unlimited. If you hit 429:
1. Check `RATE_LIMIT_PER_MINUTE` in your `.env` — this is the *local* rate limiter (per IP).
2. For provider-level rate limits (DeepSeek, Groq), contact the provider.
3. If rate limits seem incorrect for your plan, contact support with your account details.

### Q: What's the difference between plans?

| Feature | Free | Pro | Enterprise |
|---------|------|-----|-----------|
| API calls/day | 100 | 10,000 | Unlimited |
| Models | Basic | All | All + priority |
| Support | Community | Email | Dedicated |
| Rate limit (req/min) | 10 | 60 | 300 |

---

## General Troubleshooting

### Q: The app won't start. What do I check?

1. Verify `.env` exists and contains valid configuration (copy `.env.example` if missing).
2. Check Python version: requires Python 3.10+.
3. Install dependencies: `pip install -r requirements.txt`.
4. Run with clean cache: `./scripts/run_clean.sh`.

### Q: How do I clear all chat history and start fresh?

Type `/clear` in the chat. This removes conversation history and working memory. User profile, invariants, and long-term memory are preserved.

### Q: Where are the log files?

Logs are written to stdout/stderr. To capture them: `python3 -m deepseek_chat.web.app 2>&1 | tee app.log`.
