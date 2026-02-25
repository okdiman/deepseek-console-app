#!/usr/bin/env python3
import asyncio

import aiohttp

from deepseek_console_app.core.config import load_config


async def test_api() -> None:
    config = load_config()

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": "Hello, please respond with just: API test successful",
            }
        ],
        "max_tokens": config.max_tokens,
    }

    try:
        timeout = aiohttp.ClientTimeout(sock_read=config.read_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                config.api_url, headers=headers, json=payload
            ) as response:
                print(f"Status: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    content = data["choices"][0]["message"]["content"]
                    print(f"Response: {content}")
                else:
                    text = await response.text()
                    print(f"Error: {text}")
    except Exception as e:
        print(f"Exception: {type(e).__name__}: {e!r}")


if __name__ == "__main__":
    asyncio.run(test_api())
