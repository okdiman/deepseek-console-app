import json
from typing import AsyncGenerator, Dict, List

import aiohttp

from .config import ClientConfig


class DeepSeekClient:
    """HTTP client for DeepSeek Chat Completions (streaming)."""

    def __init__(self, config: ClientConfig) -> None:
        self._config = config

    async def stream_message(
        self, messages: List[Dict[str, str]]
    ) -> AsyncGenerator[str, None]:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        params = self._config.optional_params

        payload = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": self._config.max_tokens,
            "stream": True,
            # Optional params (safe defaults; change to experiment)
            "frequency_penalty": params.frequency_penalty,
            "presence_penalty": params.presence_penalty,
            "response_format": params.response_format,
            "stop": params.stop,
            "thinking": params.thinking,
        }

        timeout = aiohttp.ClientTimeout(sock_read=self._config.read_timeout_seconds)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._config.api_url, headers=headers, json=payload, timeout=timeout
            ) as response:
                if response.status != 200:
                    body_text = await response.text()
                    raise RuntimeError(f"HTTP {response.status} | Body: {body_text}")

                async for raw_line in response.content:
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
                        yield content
