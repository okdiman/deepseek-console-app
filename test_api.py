#!/usr/bin/env python3
import asyncio
import os
import sys

import aiohttp
from dotenv import load_dotenv

load_dotenv()


async def test_api() -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("Error: DEEPSEEK_API_KEY not found!")
        sys.exit(1)

    api_url = os.getenv(
        "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
    )
    timeout_seconds = int(os.getenv("DEEPSEEK_API_TIMEOUT_SECONDS", "30"))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat"),
        "messages": [
            {
                "role": "user",
                "content": "Hello, please respond with just: API test successful",
            }
        ],
        "max_tokens": int(os.getenv("DEEPSEEK_API_MAX_TOKENS", "50")),
    }

    try:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(api_url, headers=headers, json=payload) as response:
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
