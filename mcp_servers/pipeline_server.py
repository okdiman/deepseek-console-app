"""
Pipeline MCP Server — Day 19: MCP Tool Composition

Tools:
  search(query)      → fetches raw data from Hacker News
  summarize(text)    → summarizes via direct AI API call
  save_to_file(...)  → persists result to ~/.deepseek_chat/pipeline_results/
  list_results()     → lists saved files
  read_result(name)  → reads a saved file
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Pipeline Server")

RESULTS_DIR = Path(os.getenv("DEEPSEEK_DATA_DIR", "data")) / "pipeline_results"


def _ensure_results_dir() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _clean_html(raw: str) -> str:
    """Strip HTML tags and decode basic entities."""
    text = re.sub(r"<p>", "\n\n", raw or "")
    text = re.sub(r"<[^>]+>", "", text)
    return (
        text.replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&amp;", "&")
    )


# ── Step 1: Search ────────────────────────────────────────

@mcp.tool()
def search(query: str = "", limit: int = 5) -> str:
    """Шаг 1 пайплайна: получает данные из Hacker News.

    Возвращает список топовых статей с заголовками, ссылками и очками.
    query: Фильтр по ключевому слову в заголовке (необязательно).
    limit: Количество статей (1–20, по умолчанию 5).
    """
    limit = min(max(1, limit), 20)
    try:
        req = urllib.request.Request(
            "https://hacker-news.firebaseio.com/v0/topstories.json"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            top_ids: list[int] = json.loads(resp.read().decode())

        stories = []
        checked = 0
        for story_id in top_ids:
            if len(stories) >= limit:
                break
            if checked > limit * 4:
                break
            checked += 1
            try:
                s_req = urllib.request.Request(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                )
                with urllib.request.urlopen(s_req, timeout=5) as s_resp:
                    s = json.loads(s_resp.read().decode())
                    if not s or s.get("type") != "story":
                        continue
                    title = s.get("title", "")
                    if query:
                        terms = query.lower().split()
                        if not any(t in title.lower() for t in terms):
                            continue
                    score = s.get("score", 0)
                    url = s.get("url", f"https://news.ycombinator.com/item?id={story_id}")
                    author = s.get("by", "?")
                    stories.append(
                        f"[{score}] {title}\n  Author: {author} | URL: {url} | ID: {story_id}"
                    )
            except Exception:
                continue

        if not stories:
            return f"Ничего не найдено по запросу '{query}'" if query else "Статьи не найдены"

        header = f"Результаты поиска HN" + (f" по '{query}'" if query else "") + f" ({len(stories)} статей):"
        return header + "\n\n" + "\n\n".join(stories)

    except Exception as e:
        return f"Ошибка поиска: {e}"


# ── Step 2: Summarize ─────────────────────────────────────

def _load_api_config() -> tuple[str, str, str]:
    """Returns (api_key, api_url, model) from environment."""
    from dotenv import load_dotenv
    load_dotenv()
    provider = os.getenv("PROVIDER", "deepseek").strip().lower()
    if provider == "groq":
        return (
            os.getenv("GROQ_API_KEY", ""),
            os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"),
            os.getenv("GROQ_API_MODEL", "moonshotai/kimi-k2-instruct"),
        )
    return (
        os.getenv("DEEPSEEK_API_KEY", ""),
        os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"),
        os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat"),
    )


@mcp.tool()
def summarize(text: str, max_words: int = 150) -> str:
    """Шаг 2 пайплайна: суммаризирует текст через прямой вызов AI API.

    text: Исходный текст для суммаризации.
    max_words: Примерный лимит слов в итоговом резюме (по умолчанию 150).
    """
    if not text or not text.strip():
        return "Пустой текст — суммаризировать нечего."

    api_key, api_url, model = _load_api_config()
    if not api_key:
        return "Ошибка: API ключ не найден в переменных окружения."

    prompt = (
        f"Суммаризируй следующий текст на русском языке. "
        f"Выдели ключевые темы и самое важное. "
        f"Целевой объём: не более {max_words} слов. "
        f"Без вступлений типа 'Вот краткое резюме' — сразу по делу.\n\n"
        f"Текст:\n{text[:6000]}"
    )

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Ошибка суммаризации: {e}"


# ── Step 3: Save to file ──────────────────────────────────

@mcp.tool()
def save_to_file(content: str, filename: str = "") -> str:
    """Шаг 3 пайплайна: сохраняет результат в файл.

    Файлы сохраняются в ~/.deepseek_chat/pipeline_results/.
    content: Текст для сохранения.
    filename: Имя файла (необязательно; по умолчанию генерируется по timestamp).
    """
    _ensure_results_dir()

    if not filename:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"pipeline_{ts}.txt"

    # Sanitize filename
    safe_name = re.sub(r"[^\w\-.]", "_", filename)
    if not safe_name.endswith(".txt") and "." not in safe_name:
        safe_name += ".txt"

    file_path = RESULTS_DIR / safe_name
    try:
        file_path.write_text(content, encoding="utf-8")
        return f"Файл сохранён: {file_path}\n{len(content)} символов."
    except Exception as e:
        return f"Ошибка записи файла: {e}"


# ── Read results ──────────────────────────────────────────

@mcp.tool()
def list_results() -> str:
    """Возвращает список файлов, сохранённых пайплайном в ~/.deepseek_chat/pipeline_results/."""
    if not RESULTS_DIR.exists():
        return "Папка с результатами пуста или не существует."
    files = sorted(RESULTS_DIR.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return "Сохранённых файлов нет."
    lines = [f"{i+1}. {f.name}  ({f.stat().st_size} байт)" for i, f in enumerate(files)]
    return f"Файлы в {RESULTS_DIR}:\n\n" + "\n".join(lines)


@mcp.tool()
def read_result(filename: str) -> str:
    """Читает сохранённый файл из ~/.deepseek_chat/pipeline_results/.

    filename: Имя файла (например, pipeline_AI_20240101_120000.txt).
    """
    safe_name = re.sub(r"[^\w\-.]", "_", filename)
    file_path = RESULTS_DIR / safe_name
    if not file_path.exists():
        available = [f.name for f in RESULTS_DIR.glob("*.txt")] if RESULTS_DIR.exists() else []
        hint = "\n\nДоступные файлы:\n" + "\n".join(available) if available else ""
        return f"Файл не найден: {safe_name}{hint}"
    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Ошибка чтения файла: {e}"




# ── Delete results ────────────────────────────────────────

@mcp.tool()
def delete_result(filename: str) -> str:
    """Удаляет один сохранённый файл из ~/.deepseek_chat/pipeline_results/.

    filename: Имя файла (например, pipeline_AI_20240101_120000.txt).
    """
    safe_name = re.sub(r"[^\w\-.]", "_", filename)
    file_path = RESULTS_DIR / safe_name
    if not file_path.exists():
        available = [f.name for f in RESULTS_DIR.glob("*.txt")] if RESULTS_DIR.exists() else []
        hint = "\n\nДоступные файлы:\n" + "\n".join(available) if available else ""
        return f"Файл не найден: {safe_name}{hint}"
    try:
        file_path.unlink()
        return f"Файл удалён: {safe_name}"
    except Exception as e:
        return f"Ошибка удаления файла: {e}"


@mcp.tool()
def delete_all_results() -> str:
    """Удаляет все сохранённые файлы из ~/.deepseek_chat/pipeline_results/."""
    if not RESULTS_DIR.exists():
        return "Папка с результатами не существует — удалять нечего."
    files = list(RESULTS_DIR.glob("*.txt"))
    if not files:
        return "Сохранённых файлов нет."
    errors = []
    for f in files:
        try:
            f.unlink()
        except Exception as e:
            errors.append(f"{f.name}: {e}")
    if errors:
        return f"Удалено {len(files) - len(errors)}/{len(files)} файлов. Ошибки:\n" + "\n".join(errors)
    return f"Удалено {len(files)} файлов."


if __name__ == "__main__":
    mcp.run()
