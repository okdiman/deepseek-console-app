# День 28 — Local LLM vs Cloud LLM в RAG-пайплайне

## Настройка эксперимента

| Параметр | Значение |
|---|---|
| **LOCAL** | Ollama · `qwen2.5:7b` · запуск на MacBook (CPU/GPU-unified) |
| **CLOUD** | DeepSeek · `deepseek-chat` · API |
| **Retrieval** | Одинаковый для обоих — Ollama embeddings + SQLite индекс (structure-стратегия) |
| **RAG параметры** | top_k=3, pre_rerank=10, threshold=0.30 |
| **Eval set** | 10 вопросов: 6 по внешнему корпусу (PEP8, трансформеры, RAG, LLM, Python, FastAPI) + 4 по проекту |
| **Метрики** | keyword hit rate, source accuracy, avg/median elapsed, timeouts |

Retrieval полностью локальный у обоих: embeddings — через локальный Ollama, поиск — через локальный SQLite.
Единственное отличие — модель-генератор.

---

## Результаты

### По вопросам

| # | Вопрос | LOCAL | CLOUD | Победитель |
|---|---|---|---|---|
| 1 | PEP 8 максимальная длина строки | 100% | 100% | TIE |
| 2 | Scaled dot-product attention в трансформерах | 75% | 75% | TIE |
| 3 | Основные компоненты RAG | **67%** | 0% | LOCAL |
| 4 | In-context learning в LLM | 0% | **67%** | CLOUD |
| 5 | Threading vs multiprocessing в Python | 33% | 33% | TIE |
| 6 | FastAPI request validation | 67% | **100%** | CLOUD |
| 7 | Hook system в agent pipeline | 100% | 100% | TIE |
| 8 | Task state machine: состояния и переходы | 100% | 100% | TIE |
| 9 | Форматы расписаний в scheduler | 100% | 100% | TIE |
| 10 | MCP tool execution в agent stream | 75% | **100%** | CLOUD |

### Сводная таблица

| Метрика | LOCAL (qwen2.5:7b) | CLOUD (deepseek-chat) | Победитель |
|---|---|---|---|
| **Keyword hit rate** | 26/35 · **74%** | 28/35 · **80%** | CLOUD |
| **Source accuracy** | 8/10 · **80%** | 8/10 · **80%** | TIE |
| **Avg response time** | **4.0s** | 4.7s | LOCAL |
| **Median response time** | **3.9s** | 5.1s | LOCAL |
| **Timeouts** | 0 | 0 | TIE |

---

## Анализ

### Качество

DeepSeek выигрывает по keyword hit rate — 80% против 74% (+6 п.п.). Разница небольшая, но устойчивая: CLOUD побеждает в 3 из 10 вопросов, LOCAL — в 1.

По **source accuracy** — полный паритет: оба извлекают правильные источники в 8/10 случаях. Это ожидаемо: retrieval у них идентичный.

Особенности:
- **LOCAL выиграл Q3 (RAG-компоненты)**: qwen2.5:7b точнее использовал `retriever` и `generator` из контекста, тогда как DeepSeek ответил структурированно, но пропустил слово `knowledge`.
- **CLOUD выиграл Q4 (in-context learning)**: DeepSeek правильно использовал термины `few-shot` и `examples`. Qwen не нашёл их в ответе, хотя контекст был одинаковым — проблема инструкционного следования.
- **CLOUD выиграл Q6 (FastAPI)** и **Q10 (MCP)**: DeepSeek лучше справляется с вопросами про проектный код — точнее воспроизводит технические термины (`server_id`, `prefix`, `Pydantic`).

### Скорость

Неожиданный результат: **LOCAL быстрее облака** — median 3.9s vs 5.1s DeepSeek.

Причины:
1. Нет network round-trip (особенно заметно при median — стабильная низкая латентность)
2. qwen2.5:7b — значительно меньшая модель, генерирует быстрее токен за токеном
3. DeepSeek иногда даёт более развёрнутые ответы — это видно в превью

### Стабильность

Оба провайдера отработали 10/10 вопросов без единого таймаута. Полный паритет.

---

## Выводы

| | |
|---|---|
| **Лучше по качеству** | DeepSeek (облако) — небольшое преимущество на технических формулировках |
| **Лучше по скорости** | Ollama (локально) — быстрее в среднем на 0.7–1.2s |
| **Стабильность** | Одинаковая — оба надёжны |
| **Стоимость** | Ollama = $0, DeepSeek = ~$0.00014/вопрос (микроскопически) |

**Практический вывод**: для production-RAG с требованием privacy или offline-доступа — qwen2.5:7b отличный выбор: 74% качества при нулевой стоимости и более низкой латентности. Если нужна максимальная точность технических ответов — DeepSeek даёт +6 п.п. при минимальной стоимости.

---

## Команда воспроизведения

```bash
# Убедиться что Ollama запущен
ollama serve

# Запустить сравнение (сохранить JSON)
venv/bin/python3 experiments/rag_compare/cli.py local-vs-cloud --save

# Сырые данные
experiments/rag_compare/data/local_vs_cloud_report.json
```
