#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, TypedDict

import aiohttp
from dotenv import load_dotenv


class ApiResult(TypedDict, total=False):
    ok: bool
    status: int
    body: str
    text: str
    usage: Dict[str, Any]
    raw: Dict[str, Any]


@dataclass(frozen=True)
class ClientConfig:
    api_key: str
    api_url: str = "https://api.deepseek.com/v1/chat/completions"
    model: str = "deepseek-chat"
    timeout_seconds: int = 60


def load_config() -> ClientConfig:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print(
            "❌ DEEPSEEK_API_KEY not found in environment. Please set it in .env or your shell."
        )
        sys.exit(1)

    api_url = os.getenv(
        "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
    )
    model = os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat")
    timeout_seconds = int(os.getenv("DEEPSEEK_API_TIMEOUT_SECONDS", "60"))

    return ClientConfig(
        api_key=api_key,
        api_url=api_url,
        model=model,
        timeout_seconds=timeout_seconds,
    )


def build_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def call_api(
    config: ClientConfig,
    headers: Dict[str, str],
    messages: List[Dict[str, str]],
    **kwargs: Any,
) -> ApiResult:
    """
    Calls DeepSeek Chat Completions API and returns a structured result:
      {
        ok: bool,
        status: int,
        body: str,
        text: str,
        usage: dict,
        raw: dict
      }
    """
    payload: Dict[str, Any] = {
        "model": config.model,
        "messages": messages,
    }
    payload.update(kwargs)

    result: ApiResult = {"ok": False, "status": 0, "body": ""}

    timeout = aiohttp.ClientTimeout(sock_read=config.timeout_seconds)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                config.api_url, headers=headers, json=payload
            ) as resp:
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
                        "Malformed response: missing choices[0].message.content "
                        f"({e}). Raw: {text[:500]}"
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


async def stream_collect(
    config: ClientConfig,
    headers: Dict[str, str],
    messages: List[Dict[str, str]],
    on_chunk: Callable[[str], None],
    **kwargs: Any,
) -> ApiResult:
    payload: Dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": True,
    }
    payload.update(kwargs)

    result: ApiResult = {"ok": False, "status": 0, "body": ""}

    timeout = aiohttp.ClientTimeout(sock_read=config.timeout_seconds)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                config.api_url, headers=headers, json=payload
            ) as resp:
                result["status"] = resp.status
                if resp.status != 200:
                    result["body"] = await resp.text()
                    return result

                parts: List[str] = []
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[len("data: ") :]
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = event.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        on_chunk(content)
                        parts.append(content)

                result.update(
                    {
                        "ok": True,
                        "text": "".join(parts),
                        "usage": {},
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


async def print_streamed_result(
    title: str,
    config: ClientConfig,
    headers: Dict[str, str],
    messages: List[Dict[str, str]],
    **kwargs: Any,
) -> ApiResult:
    print_block(title)
    parts: List[str] = []

    def on_chunk(chunk: str) -> None:
        print(chunk, end="", flush=True)
        parts.append(chunk)

    result = await stream_collect(
        config,
        headers,
        messages,
        on_chunk,
        **kwargs,
    )

    if not result.get("ok"):
        print(f"Ошибка: HTTP {result.get('status')}\n{result.get('body')}")
        return result

    print()
    text = (result.get("text") or "").strip()
    result["text"] = text
    print("Длина символов:", len(text))
    print(usage_brief(result.get("usage")))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare DeepSeek responses with baseline and constrained prompts."
    )
    parser.add_argument(
        "--query",
        default="Объясни машинное обучение простыми словами",
        help="User query to send to the model",
    )
    parser.add_argument(
        "--baseline-temp",
        type=float,
        default=0.7,
        help="Temperature for baseline response",
    )
    parser.add_argument(
        "--baseline-max-tokens",
        type=int,
        default=800,
        help="max_tokens for baseline response",
    )
    parser.add_argument(
        "--constrained-temp",
        type=float,
        default=0.3,
        help="Temperature for constrained response",
    )
    parser.add_argument(
        "--constrained-max-tokens",
        type=int,
        default=120,
        help="max_tokens for constrained response",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    config = load_config()
    headers = build_headers(config.api_key)

    # 1) Baseline
    baseline_messages = [{"role": "user", "content": args.query}]
    baseline = await print_streamed_result(
        "Без ограничений",
        config,
        headers,
        baseline_messages,
        temperature=args.baseline_temp,
        max_tokens=args.baseline_max_tokens,
    )

    # 2) Constrained
    system_format = (
        "Ты отвечаешь строго в формате JSON без лишнего текста. "
        'Структура: {"definition": string, "analogy": string}. '
        "Короткие формулировки: в каждом поле не более 2-3 коротких предложений. "
        "Не добавляй пояснений, префиксов и постфиксов. Никаких код-блоков. "
        "После JSON выведи маркер END."
    )
    constrained_messages = [
        {"role": "system", "content": system_format},
        {"role": "user", "content": args.query},
    ]
    constrained = await print_streamed_result(
        "С ограничениями (JSON + stop=END)",
        config,
        headers,
        constrained_messages,
        temperature=args.constrained_temp,
        max_tokens=args.constrained_max_tokens,
        stop=["END"],
    )

    # Results are printed during streaming

    # Validate JSON
    if constrained.get("ok"):
        c_text = (constrained.get("text") or "").strip()
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
