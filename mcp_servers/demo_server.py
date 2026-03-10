import asyncio
import urllib.request
import json
import re
from mcp.server.fastmcp import FastMCP

# Указываем имя нашего сервера
mcp = FastMCP("Hacker News Server")

def _clean_html(raw_html: str) -> str:
    """Очищает HTML-теги из текста комментариев HN."""
    if not raw_html:
        return ""
    # Простая очистка тегов, замена <p> на переносы строк
    text = re.sub(r'<p>', '\n\n', raw_html)
    text = re.sub(r'<[^>]+>', '', text)
    # Декодирование базовых HTML сущностей
    text = text.replace('&quot;', '"').replace('&#x27;', "'").replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
    return text

@mcp.tool()
def get_top_stories(limit: int = 5) -> str:
    """Получает список самых популярных статей прямо сейчас на Hacker News.
    Возвращает заголовки, ссылки, количество баллов (score) и ID статьи.
    limit: Количество статей для возврата (по умолчанию 5, максимум 20).
    """
    limit = min(max(1, limit), 20)
    try:
        # 1. Получаем список ID топовых статей
        req = urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json")
        with urllib.request.urlopen(req) as response:
            top_ids = json.loads(response.read().decode())
        
        if not top_ids:
            return "Не удалось получить список статей."
            
        # Берем только нужное количество
        target_ids = top_ids[:limit]
        
        stories = []
        # 2. Получаем детали каждой статьи
        for story_id in target_ids:
            try:
                story_req = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
                with urllib.request.urlopen(story_req) as story_resp:
                    story_data = json.loads(story_resp.read().decode())
                    if story_data and story_data.get("type") == "story":
                        title = story_data.get("title", "Без названия")
                        score = story_data.get("score", 0)
                        url = story_data.get("url", f"https://news.ycombinator.com/item?id={story_id}")
                        author = story_data.get("by", "Неизвестный")
                        
                        stories.append(f"- **{title}** (Score: {score}, Author: {author})\n  ID: `{story_id}`\n  Link: {url}")
            except Exception as e:
                stories.append(f"- Ошибка загрузки статьи {story_id}: {e}")
                
        return "Топ статей на Hacker News:\n\n" + "\n\n".join(stories)
        
    except Exception as e:
        return f"Ошибка при обращении к Hacker News API: {e}"

@mcp.tool()
def get_story_comments(story_id: int, limit: int = 5) -> str:
    """Получает топовые комментарии к конкретной статье на Hacker News.
    Используйте ID статьи, полученный из инструмента get_top_stories.
    story_id: ID статьи (напр., 40000000).
    limit: Количество комментариев (по умолчанию 5).
    """
    limit = min(max(1, limit), 10) # До 10 комментариев, чтобы не перегружать контекст
    try:
        story_req = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        with urllib.request.urlopen(story_req) as response:
            story_data = json.loads(response.read().decode())
            
        if not story_data:
            return f"Статья с ID {story_id} не найдена."
            
        kids = story_data.get("kids", [])
        if not kids:
            return f"К статье '{story_data.get('title', 'Unknown')}' пока нет комментариев."
            
        target_comment_ids = kids[:limit]
        comments_list = []
        
        for comment_id in target_comment_ids:
            try:
                comment_req = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{comment_id}.json")
                with urllib.request.urlopen(comment_req) as comment_resp:
                    comment_data = json.loads(comment_resp.read().decode())
                    
                    if comment_data and not comment_data.get("deleted") and not comment_data.get("dead"):
                        author = comment_data.get("by", "Неизвестный")
                        text_html = comment_data.get("text", "")
                        text_clean = _clean_html(text_html)
                        
                        comments_list.append(f"👤 **{author}**:\n{text_clean}")
            except Exception as e:
                comments_list.append(f"[Ошибка загрузки комментария {comment_id}]")
                
        title = story_data.get('title', 'Unknown')
        return f"Комментарии к статье '{title}' (ID: {story_id}):\n\n" + "\n\n---\n\n".join(comments_list)
        
    except Exception as e:
        return f"Ошибка при получении комментариев: {e}"

if __name__ == "__main__":
    mcp.run()
