#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional, Union

import aiohttp
from dotenv import load_dotenv

API_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"


def ensure_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print(
            "❌ DEEPSEEK_API_KEY not found in environment. Please set it in .env or your shell."
        )
        sys.exit(1)
    return api_key


def build_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def call_api(
    headers: Dict[str, str],
    messages: List[Dict[str, str]],
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Calls DeepSeek Chat Completions API and returns a rich result dict:
      {
        ok: bool,
        status: int,
        body: str,        # raw response text (always present)
        text: str,        # assistant content (when ok)
        usage: dict,      # token usage (when present)
        raw: dict         # parsed JSON (when ok)
      }
    """
    payload: Dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
    }
    payload.update(kwargs)

    result: Dict[str, Any] = {
        "ok": False,
        "status": 0,
        "body": "",
    }

    timeout = aiohttp.ClientTimeout(total=60)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(API_URL, headers=headers, json=payload) as resp:
                result["status"] = resp.status
                text = await resp.text()
                result["body"] = text

                if resp.status != 200:
                    return result

                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    result["body"] = f"JSON decode error: {e}\nRaw: {text[:500]}"
                    return result

                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    result["body"] = (
                        f"Malformed response: missing choices[0].message.content ({e}). Raw: {text[:500]}"
                    )
                    return result

                result.update(
                    {
                        "ok": True,
                        "text": content,
                        "usage": data.get("usage", {}),
                        "raw": data,
                    }
                )
                return result

    except asyncio.TimeoutError:
        result["body"] = "Request timeout (client-side)."
        return result
    except aiohttp.ClientError as e:
        result["body"] = f"Network error: {type(e).__name__}: {e}"
        return result
    except Exception as e:
        result["body"] = f"Unexpected error: {type(e).__name__}: {e}"
        return result


def usage_brief(usage: Optional[Dict[str, Any]]) -> str:
    if not usage:
        return "usage: n/a"
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    tt = usage.get("total_tokens")
    return f"usage: prompt={pt}, completion={ct}, total={tt}"


def print_block(title: str) -> None:
    print()
    print("=" * 12, title, "=" * 12)


async def main() -> None:
    api_key = ensure_api_key()
    headers = build_headers(api_key)

    # Query to compare
    query = "Объясни машинное обучение простыми словами"

    # 1) Baseline (no strict constraints)
    baseline_messages = [
        {"role": "user", "content": query},
    ]
    baseline = await call_api(
        headers,
        baseline_messages,
        temperature=0.7,
        max_tokens=800,  # allow a longer completion
    )

    # 2) Constrained (explicit format + length limit + stop)
    #    We ask for STRICT JSON without extra text. We add a stop sequence 'END'.
    system_format = (
        "Ты отвечаешь строго в формате JSON без лишнего текста. "
        'Структура: {"definition": string, "analogy": string}. '
        "Короткие формулировки: в каждом поле не более 2-3 коротких предложений. "
        "Не добавляй пояснений, префиксов и постфиксов. Никаких код-блоков. "
        "После JSON выведи маркер END."
    )
    constrained_messages = [
        {"role": "system", "content": system_format},
        {"role": "user", "content": query},
    ]
    constrained = await call_api(
        headers,
        constrained_messages,
        temperature=0.3,  # more deterministic
        max_tokens=120,  # constrain length
        stop=["END"],  # stop at END
    )

    # Print results
    print_block("Без ограничений")
    if not baseline.get("ok"):
        print(f"Ошибка: HTTP {baseline.get('status')}\n{baseline.get('body')}")
    else:
        b_text = baseline["text"].strip()
        print(b_text)
        print()
        print("Длина символов:", len(b_text))
        print(usage_brief(baseline.get("usage")))

    print_block("С ограничениями (JSON + max_tokens=120 + stop=END)")
    if not constrained.get("ok"):
        print(f"Ошибка: HTTP {constrained.get('status')}\n{constrained.get('body')}")
    else:
        c_text = constrained["text"].strip()
        print(c_text)
        print()
        print("Длина символов:", len(c_text))
        print(usage_brief(constrained.get("usage")))

        print("\nПроверка JSON формата ограниченного ответа:")
        try:
            parsed = json.loads(c_text)
            print("JSON валиден. Ключи:", list(parsed.keys()))
        except Exception as e:
            print("Не удалось распарсить JSON:", e)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Остановлено пользователем.")
