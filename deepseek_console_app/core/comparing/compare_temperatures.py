#!/usr/bin/env python3
import argparse
import asyncio
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, List, Optional

import aiohttp

from deepseek_console_app.core.config import ClientConfig, load_config


@dataclass
class RunResult:
    ok: bool
    status: int
    text: str
    usage: Dict[str, Any]
    duration_seconds: float
    error: str = ""


def build_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def parse_temperatures(value: str) -> List[float]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    temps: List[float] = []
    for p in parts:
        temps.append(float(p))
    return temps


def usage_brief(usage: Optional[Dict[str, Any]]) -> str:
    if not usage:
        return "usage: n/a"
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    tt = usage.get("total_tokens")
    return f"usage: prompt={pt}, completion={ct}, total={tt}"


def calc_cost_usd(
    usage: Optional[Dict[str, Any]], config: ClientConfig
) -> Optional[float]:
    if not usage:
        return None
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    if pt is None or ct is None:
        return None
    return (pt / 1000.0) * config.price_per_1k_prompt_usd + (
        ct / 1000.0
    ) * config.price_per_1k_completion_usd


async def stream_collect(
    config: ClientConfig,
    headers: Dict[str, str],
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> RunResult:
    payload: Dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        "temperature": temperature,
    }

    start_time = perf_counter()
    usage: Dict[str, Any] = {}
    parts: List[str] = []

    timeout = aiohttp.ClientTimeout(sock_read=config.read_timeout_seconds)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                config.api_url, headers=headers, json=payload
            ) as resp:
                status = resp.status
                if status != 200:
                    body = await resp.text()
                    return RunResult(
                        ok=False,
                        status=status,
                        text="",
                        usage={},
                        duration_seconds=perf_counter() - start_time,
                        error=body,
                    )

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
                    event_usage = event.get("usage")
                    if event_usage:
                        usage = event_usage
                    delta = event.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        print(content, end="", flush=True)
                        parts.append(content)

        duration = perf_counter() - start_time
        return RunResult(
            ok=True,
            status=200,
            text="".join(parts).strip(),
            usage=usage,
            duration_seconds=duration,
        )
    except asyncio.TimeoutError:
        return RunResult(
            ok=False,
            status=0,
            text="",
            usage={},
            duration_seconds=perf_counter() - start_time,
            error="Request timeout (client-side).",
        )
    except aiohttp.ClientError as e:
        return RunResult(
            ok=False,
            status=0,
            text="",
            usage={},
            duration_seconds=perf_counter() - start_time,
            error=f"Network error: {type(e).__name__}: {e}",
        )
    except Exception as e:
        return RunResult(
            ok=False,
            status=0,
            text="",
            usage={},
            duration_seconds=perf_counter() - start_time,
            error=f"Unexpected error: {type(e).__name__}: {e}",
        )


def print_block(title: str) -> None:
    print()
    print("=" * 12, title, "=" * 12)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare DeepSeek responses across multiple temperatures."
    )
    parser.add_argument(
        "--query",
        default="Объясни машинное обучение простыми словами",
        help="User query to send to the model",
    )
    parser.add_argument(
        "--temperatures",
        default="0,0.7,1.2",
        help="Comma-separated temperatures (e.g. 0,0.7,1.2)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=400,
        help="max_tokens for each response",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    config = load_config()
    headers = build_headers(config.api_key)

    temps = parse_temperatures(args.temperatures)
    messages = [{"role": "user", "content": args.query}]

    for t in temps:
        title = f"temperature={t}"
        print_block(title)
        result = await stream_collect(
            config=config,
            headers=headers,
            messages=messages,
            temperature=t,
            max_tokens=args.max_tokens,
        )

        if not result.ok:
            print(f"\n❌ Error: HTTP {result.status}\n{result.error}")
            continue

        print()
        print("Chars:", len(result.text))
        print(usage_brief(result.usage))
        cost = calc_cost_usd(result.usage, config)
        cost_text = f"${cost:.6f}" if cost is not None else "n/a"
        print(f"Time: {result.duration_seconds:.2f}s | Cost: {cost_text}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Остановлено пользователем.")
