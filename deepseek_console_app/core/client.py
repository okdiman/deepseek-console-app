import json
from dataclasses import dataclass
from time import perf_counter
from typing import AsyncGenerator, Dict, List, Optional

import aiohttp

from .config import ClientConfig


@dataclass(frozen=True)
class StreamMetrics:
    duration_seconds: float
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    cost_usd: Optional[float]


class DeepSeekClient:
    """HTTP client for DeepSeek or Groq Chat Completions (streaming)."""

    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._last_metrics: Optional[StreamMetrics] = None

    def last_metrics(self) -> Optional[StreamMetrics]:
        return self._last_metrics

    async def stream_message(
        self, messages: List[Dict[str, str]], temperature: Optional[float] = None
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
            "temperature": temperature
            if temperature is not None
            else params.temperature,
            "response_format": params.response_format,
            "stop": params.stop,
        }
        if self._config.provider == "deepseek":
            payload.update(
                {
                    "frequency_penalty": params.frequency_penalty,
                    "presence_penalty": params.presence_penalty,
                    "thinking": params.thinking,
                }
            )

        start_time = perf_counter()
        usage: Optional[dict] = None
        timeout = aiohttp.ClientTimeout(sock_read=self._config.read_timeout_seconds)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._config.api_url, headers=headers, json=payload, timeout=timeout
                ) as response:
                    if response.status != 200:
                        body_text = await response.text()
                        lowered = body_text.lower()
                        if (
                            "context_length" in lowered
                            or ("context" in lowered and "length" in lowered)
                            or ("context" in lowered and "window" in lowered)
                            or ("tokens" in lowered and "limit" in lowered)
                        ):
                            raise RuntimeError(
                                f"Context length exceeded | HTTP {response.status} | Body: {body_text}"
                            )
                        raise RuntimeError(
                            f"HTTP {response.status} | Body: {body_text}"
                        )

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
                        event_usage = event.get("usage")
                        if event_usage:
                            usage = event_usage
                        delta = event.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
        finally:
            duration = perf_counter() - start_time
            prompt_tokens = usage.get("prompt_tokens") if usage else None
            completion_tokens = usage.get("completion_tokens") if usage else None
            total_tokens = usage.get("total_tokens") if usage else None
            cost: Optional[float] = None
            if prompt_tokens is not None and completion_tokens is not None:
                cost = (
                    prompt_tokens / 1000.0
                ) * self._config.price_per_1k_prompt_usd + (
                    completion_tokens / 1000.0
                ) * self._config.price_per_1k_completion_usd
            self._last_metrics = StreamMetrics(
                duration_seconds=duration,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
            )
