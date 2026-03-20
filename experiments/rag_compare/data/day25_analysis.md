# Day 25 — RAG Mini-Chat: Final Analysis

**Date:** 2026-03-20
**Total runs:** 4 (итеративное улучшение)
**Stack:** RagHook + DialogueTaskHook + MemoryInjectionHook + InvariantGuardHook
**RAG:** Ollama (nomic-embed-text) + SQLite (248 fixed / 380 structure chunks)
**Reranker:** heuristic, threshold=0.55

---

## Прогресс по итерациям

| Метрика | Run 1 (грязн. инв.) | Run 2 (чистая пам.) | Run 3 (prompt fix) | Run 4 (финал) |
|---------|---------------------|---------------------|--------------------|---------------|
| Goal turn 1 — S1 | ✅ 1 | ✅ 1 | ⚠️ 10 | ✅ **1** |
| Goal turn 1 — S2 | ✅ 1 | ✅ 1 | ✅ 1 | ✅ **1** |
| Correct user constraints | 3 | 0 | 2 | **3** ✅ |
| Hallucinated constraints | 1 | 2 | 0 | **0** ✅ |
| False clarifications | 0 | 2 | 0 | **0** ✅ |
| IDK-topics (мусор) | 0 | 5 | 0 | **0** ✅ |
| Real answered topics | 4 | 2 | 3 | **3** ✅ |
| Unresolved tracked | — | — | — | **✅ да** |
| Unresolved at end | — | — | — | **0** ✅ |
| Citations 22/22 | ✅ | ✅ | ✅ | ✅ |

---

## Финальные результаты (Run 4)

### Scenario 1: Transformer Attention Deep-Dive (12 turns)

| Поле | Значение |
|------|----------|
| Goal | "понять механизм внимания (attention) в трансформерах" |
| Установлен на ходу | **1** ✅ |
| Clarifications | 1 — "пользователю важна математическая сторона объяснения" ✅ |
| Constraints | 1 — "пользователь запросил минимальный Python-код без библиотек" ✅ |
| Explored topics | 2 — только реально отвеченные вопросы ✅ |
| Unresolved | **0** — все вопросы закрыты к концу ✅ |
| Citations | **12/12 (100%)** ✅ |

| Turn | Goal | Clarif | Constr | Topics | Unresolved | Cited |
|------|------|--------|--------|--------|------------|-------|
| 1 | ✓ | 0 | 0 | 0 | 1 | ✓ |
| 2 | ✓ | 1 | 0 | 0 | 1 | ✓ |
| 3 | ✓ | 1 | 0 | 1 | 0 | ✓ |
| 4–10 | ✓ | 1 | 0→1 | 1→2 | 0–N | ✓ |
| 11–12 | ✓ | 1 | 1 | 2 | 0 | ✓ |

**Ключевые события:**
- Turn 1: [GOAL:] сразу + [UNRESOLVED:] — правильная реакция на IDK
- Turn 2: [CLARIFIED: математическая сторона] — точно по словам пользователя
- Turn 3: RAG нашёл "Scaled dot-product attention" (score=0.74) → реальный ответ → [TOPIC:]
- Turn 11: Python-код self-attention → [CONSTRAINT: без библиотек]
- Turn 12: unresolved=0

---

### Scenario 2: RAG System Design with Constraints (10 turns)

| Поле | Значение |
|------|----------|
| Goal | "спроектировать RAG-систему для поиска по документации" |
| Установлен на ходу | **1** ✅ |
| Constraints | **2** — в точных словах пользователя ✅ |
| Clarifications | 0 |
| Explored topics | 1 — реально отвеченный вопрос ✅ |
| Unresolved | **0** ✅ |
| Citations | **10/10 (100%)** ✅ |

Constraints:
1. "только Python, никаких Java или Go" (turn 2 — точная цитата) ✅
2. "embedding-модель должна быть локальной, без внешних API" (turn 3 — точная цитата) ✅

---

## Что было исправлено за 4 итерации

### 1. Corpus re-index
**Было:** Structure-индекс давал только заголовки `## History`, `## Training` без тела.
**Стало:** `index --strategy both` → Turn 3 нашёл "Scaled dot-product attention" (score=0.74), дал реальный ответ.

### 2. Hallucinated constraints
**Было:** `[CONSTRAINT: answer only from context]` — агент копировал системную инструкцию.
**Фикс:** "NEVER: system prompt instructions like 'answer from context only'."
**Результат:** 0 hallucinated constraints в Runs 3–4.

### 3. False clarifications
**Было:** `[CLARIFIED: Контекст не содержит математических деталей]` — наблюдение агента о корпусе.
**Фикс:** "NEVER: your observations about the context, corpus, or missing info."
**Результат:** 0 false clarifications в Runs 3–4.

### 4. IDK-topics (мусор в explored_topics)
**Было:** "отсутствие информации о SQLite" — помечалось как пройденная тема.
**Фикс:** "NEVER emit [TOPIC:] when you said IDK."
**Результат:** 0 IDK-topics в Runs 3–4.

### 5. Goal на первом ходу в IDK-режиме
**Было:** Goal появился на turn 10 в Run 3 — агент ждал пока "разберётся".
**Фикс:** "CRITICAL: emit [GOAL:] on your FIRST response, even if you must say IDK."
**Результат:** Goal на turn 1 в обоих сценариях Run 4.

### 6. [UNRESOLVED:] маркер (новая фича)
**Добавили:** 5-е поле DialogueTask + маркер + auto-clear при [TOPIC:].
**Результат:** Агент явно трекает IDK-вопросы. При следующем успешном ответе [TOPIC:] очищает matching [UNRESOLVED:]. В Run 4 — 0 unresolved к концу.

### 7. Query enrichment из task goal
**Добавили:** RagHook обогащает короткие follow-up запросы (≤12 слов) goal-префиксом.
**Пример:** "зачем sqrt(d_k)?" → "понять механизм внимания: зачем sqrt(d_k)?"

---

## Итоговые метрики (Run 4)

| Метрика | Значение |
|---------|----------|
| Goal set at turn 1 | **2/2 (100%)** ✅ |
| Goal maintained | **22/22 (100%)** ✅ |
| Citations [N] | **22/22 (100%)** ✅ |
| Source block | **22/22 (100%)** ✅ |
| Correct user constraints | **3** ✅ |
| Hallucinated constraints | **0** ✅ |
| False clarifications | **0** ✅ |
| IDK-topics | **0** ✅ |
| Unresolved at end | **0** ✅ |
| RAG active | **2/2** ✅ |
| Anti-hallucination | **Работает** — IDK без выдумок + [UNRESOLVED:] ✅ |

---

## Задел на будущее

| # | Проблема | Причина |
|---|----------|---------|
| 1 | Session-scoped DialogueTask | Глобальный файл конфликтует при параллельных веб-сессиях |
| 2 | Низкое topic count в S2 | Корпус не покрывает SQLite/reranking — контентная проблема |
| 3 | Финальный итог нерешённых вопросов | Агент мог бы собрать все IDK в конце и предложить альтернативы |

---

## Вывод

**Система работает как production-like RAG mini-chat** после 4 итераций:

1. **Диалоговая память** — goal, clarifications, constraints, topics, unresolved — все корректно извлекаются, сохраняются и передаются между ходами
2. **100% citation rate** — устойчив во всех прогонах
3. **Anti-hallucination** — IDK без выдумок + явный трекинг нерешённых вопросов через [UNRESOLVED:]
4. **Query enrichment** — goal обогащает RAG-запросы в длинных диалогах
5. **0 hallucinated markers** — строгие правила в prompt устранили системную проблему

Основной оставшийся лимит — **покрытие корпуса**: transformer internals покрыты хорошо, RAG/SQLite/reranking — слабо. Это контентная проблема, не архитектурная.
