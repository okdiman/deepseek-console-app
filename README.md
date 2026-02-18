# 🚀 DeepSeek Console Application

Простое консольное приложение для общения с DeepSeek AI через API (со стримингом ответа).

## Быстрый старт

```/dev/null/shell#L1-6
git clone https://github.com/okdiman/deepseek-console-app.git
cd deepseek-console-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Открой `.env` и добавь ключ:

```/dev/null/dotenv#L1-1
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

Запуск:

```/dev/null/shell#L1-1
python3 main.py
```

## Конфигурация (опционально)

Через переменные окружения:

- `DEEPSEEK_API_KEY` — **обязательно**
- `DEEPSEEK_API_TIMEOUT_SECONDS` — таймаут чтения (по умолчанию 60)
- `DEEPSEEK_API_MAX_TOKENS` — лимит токенов (по умолчанию 4000)
- `DEEPSEEK_API_MODEL` — модель (по умолчанию `deepseek-chat`)
- `DEEPSEEK_API_URL` — URL API (по умолчанию `https://api.deepseek.com/v1/chat/completions`)

## Команды

- Любой текст — отправить запрос
- `/help` — показать справку
- `/quit` или `/exit` — выход

## Пример сессии (стриминг)

```/dev/null/console#L1-12
============================================================
🚀 DeepSeek Console Application
============================================================
Commands:
- Type any question to get AI response
- /help - Show this help
- /quit or /exit - Exit application
============================================================

Your message: Привет! Объясни, что такое блокчейн.
🤖 AI: Блокчейн — это распределённая база данных...
```

## Частые проблемы

- **Ошибка `DEEPSEEK_API_KEY not found`** — проверь `.env` и ключ.
- **Сетевые ошибки** — проверь интернет и валидность ключа.

---
MIT License