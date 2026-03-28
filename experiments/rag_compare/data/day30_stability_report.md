# Day 30 — Stability Report: Local LLM as a Private Service

**Date:** 2026-03-28
**Model:** `qwen2.5:7b` via Ollama
**Service:** FastAPI + uvicorn on `127.0.0.1:8000`
**Provider:** ollama (fully local, no cloud API)

---

## Setup

| Component | Details |
|-----------|---------|
| Web server | FastAPI + uvicorn |
| LLM | Ollama `qwen2.5:7b` (local) |
| Auth | `APIKeyMiddleware` (disabled in this test) |
| Rate limit | `slowapi`, 60 req/min/IP |
| Max input | `MAX_INPUT_CHARS=0` (unlimited) |
| MCP servers | local_demo, scheduler, pipeline, deepwiki — все запущены |

### MCP fix
До запуска тестов обнаружилась проблема: MCP серверы падали с `ModuleNotFoundError: No module named 'mcp'`,
потому что команда указывала на системный `python3`, у которого нет venv-пакетов.
Исправлено: в `data/mcp_servers.json` команда изменена с `python3` → `venv/bin/python3`.
После исправления все серверы стартуют без ошибок.

---

## Test Results

### Series 1 — Sequential (concurrency=1, requests=5)

| # | Question | TTFT (s) | Total (s) |
|---|----------|----------|-----------|
| 1 | Name three programming languages. | 4.81 | 6.26 |
| 2 | What is 2+2? | 10.49 | 11.44 |
| 3 | What is Python? | 15.67 | 17.41 |
| 4 | How many days are in a week? | 21.65 | 22.56 |
| 5 | What color is the sky? | 26.80 | 28.61 |

| Metric | Value |
|--------|-------|
| Success rate | **100%** (5/5) |
| TTFT avg / p50 | 15.89s / 15.67s |
| Total avg / p50 | 17.26s / 17.41s |
| Wall time | 28.61s |
| Throughput | **0.17 req/s** |

> TTFT растёт линейно — каждый следующий запрос ждёт окончания предыдущего,
> т.к. Ollama обрабатывает один поток за раз.

---

### Series 2 — Low concurrency (concurrency=3, requests=9)

| # | Question | TTFT (s) | Total (s) |
|---|----------|----------|-----------|
| 1 | Define REST API in one sentence. | 4.32 | 6.82 |
| 2 | Name three programming languages. | 5.24 | 7.31 |
| 3 | What is 2+2? | 6.04 | 7.66 |
| 4 | What does CPU stand for? | 14.11 | 17.62 |
| 5 | What is Python? | 11.85 | 31.82 |
| 6 | What is HTTP? | 15.22 | 32.30 |
| 7 | How many days are in a week? | 36.49 | 40.57 |
| 8 | Name one sorting algorithm. | 37.76 | 41.02 |
| 9 | What color is the sky? | 38.81 | 41.54 |

| Metric | Value |
|--------|-------|
| Success rate | **100%** (9/9) |
| TTFT avg / p50 | 18.87s / 14.11s |
| Total avg / p50 | 25.18s / 31.82s |
| Wall time | 41.54s |
| Throughput | **0.22 req/s** |

> Первые 3 запроса уходят практически сразу (TTFT ~4–6s).
> Вторая и третья волна по 3 запроса ждут в очереди Ollama —
> отсюда TTFT 11–38s. Все 9 запросов завершились успешно.

---

### Series 3 — Medium concurrency (concurrency=5, requests=10)

| # | Question | TTFT (s) | Total (s) |
|---|----------|----------|-----------|
| 1 | What is 2+2? | 4.33 | 9.57 |
| 2 | Define REST API in one sentence. | 4.88 | 9.94 |
| 3 | Name three programming languages. | 5.55 | 10.43 |
| 4 | What does CPU stand for? | 6.31 | 10.81 |
| 5 | What is Python? | 7.39 | 11.25 |
| 6 | What is a variable in programming? | 15.44 | 22.21 |
| 7 | What is HTTP? | 17.09 | 22.63 |
| 8 | How many days are in a week? | 18.59 | 22.94 |
| 9 | Name one sorting algorithm. | 19.11 | 23.29 |
| 10 | What color is the sky? | 19.68 | 23.85 |

| Metric | Value |
|--------|-------|
| Success rate | **100%** (10/10) |
| TTFT avg / p50 | 11.84s / 11.41s |
| Total avg / p50 | 16.69s / 16.73s |
| Wall time | 23.85s |
| Throughput | **0.42 req/s** |

> При concurrency=5 первые 5 запросов стартуют одновременно и получают первый токен за 4–7s.
> Вторая пятёрка ждёт ~15–19s — Ollama последовательно переключается между потоками.
> Wall time 23.85s против 28.61s при concurrency=1 — параллелизм даёт реальный выигрыш
> в общей пропускной способности.

---

## Сводная таблица

| Concurrency | Requests | Success | TTFT avg | Total avg | Wall time | Throughput |
|-------------|----------|---------|----------|-----------|-----------|------------|
| 1 | 5 | 100% | 15.89s | 17.26s | 28.61s | 0.17 req/s |
| 3 | 9 | 100% | 18.87s | 25.18s | 41.54s | 0.22 req/s |
| 5 | 10 | 100% | 11.84s | 16.69s | 23.85s | 0.42 req/s |

---

## Анализ

### Стабильность
Сервис показал **100% успешных запросов** во всех трёх сериях (24 запроса суммарно).
Ни одного таймаута, ни одной HTTP-ошибки. FastAPI корректно обрабатывает параллельные SSE-соединения,
очередь к Ollama выстраивается естественно через asyncio.

### Узкое место — Ollama
Ollama обрабатывает один запрос к модели за раз (нет параллельного inference по умолчанию).
При concurrency > 1 запросы выстраиваются в очередь: первый токен приходит быстро для первой волны,
но следующие запросы ждут. Это видно по TTFT: при concurrency=5 первые 5 запросов получают TTFT ~4–7s,
вторые 5 — ~15–19s.

### Throughput vs. latency
| Режим | Характеристика |
|-------|---------------|
| concurrency=1 | Самая низкая latency для отдельного пользователя, самый низкий throughput |
| concurrency=3 | Умеренный прирост throughput (+29%), latency растёт при второй волне |
| concurrency=5 | Лучший throughput (+147% vs c=1), wall time ниже, latency p50 стабильна |

Оптимальный режим для одиночного пользователя — **concurrency=1** (минимальная задержка).
Для балансировки нескольких пользователей — **concurrency=3–5** при понимании, что последующие
запросы ждут дольше.

### Ограничения сервиса

| Параметр | Результат |
|----------|-----------|
| Rate limiting | Работает (60 req/min/IP, настраивается через `RATE_LIMIT_PER_MINUTE`) |
| Auth (API key) | Работает: без ключа → 401, с правильным ключом → 200, `/health` всегда доступен |
| Max input | Настраивается через `MAX_INPUT_CHARS` (0 = без ограничения) |
| Network binding | `SERVICE_HOST=0.0.0.0` открывает сервис для LAN-доступа |

### Рекомендации для production
1. **Выставить `SERVICE_HOST=0.0.0.0`** и закрыть за nginx с TLS для доступа из сети
2. **Установить `SERVICE_API_KEY`** — без него сервис открыт всем в сети
3. **`RATE_LIMIT_PER_MINUTE=10–20`** — разумно для локальной модели, чтобы не перегружать GPU/CPU
4. **`MAX_INPUT_CHARS=8000`** — защита от огромных промптов, которые блокируют Ollama надолго
5. **`OLLAMA_HOST=0.0.0.0:11434`** — если нужен прямой доступ к Ollama API (минуя наш сервис)
