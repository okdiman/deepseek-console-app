#!/usr/bin/env python3

import os
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class OptionalRequestParams:
    frequency_penalty: float = 0.0  # [-2, 2] penalize repeated tokens
    presence_penalty: float = 0.0  # [-2, 2] encourage new topics
    temperature: float = 1.0  # 2[0, 2] randomness; higher = more creative
    response_format: dict[str, str] = field(
        default_factory=lambda: {"type": "text"}
    )  # or {"type": "json_object"} (must instruct JSON in messages)
    stop: object | None = None  # string or list of strings
    thinking: dict[str, str] = field(
        default_factory=lambda: {"type": "disabled"}
    )  # "enabled" or "disabled"


@dataclass(frozen=True)
class ClientConfig:
    api_key: str
    api_url: str = "https://api.deepseek.com/v1/chat/completions"
    model: str = "deepseek-chat"
    max_tokens: int = 4000
    read_timeout_seconds: int = 60
    price_per_1k_prompt_usd: float = 0.00028
    price_per_1k_completion_usd: float = 0.00042
    optional_params: OptionalRequestParams = field(
        default_factory=OptionalRequestParams
    )


def load_config() -> ClientConfig:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY not found!")
        sys.exit(1)

    read_timeout = int(os.getenv("DEEPSEEK_API_TIMEOUT_SECONDS", "60"))
    max_tokens = int(os.getenv("DEEPSEEK_API_MAX_TOKENS", "4000"))
    model = os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat")
    api_url = os.getenv(
        "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
    )
    price_prompt = float(os.getenv("DEEPSEEK_PRICE_PER_1K_PROMPT_USD", "0.00028"))
    price_completion = float(
        os.getenv("DEEPSEEK_PRICE_PER_1K_COMPLETION_USD", "0.00042")
    )

    defaults = OptionalRequestParams()
    optional_params = defaults

    print(f"ℹ️  temperature: {optional_params.temperature}")

    return ClientConfig(
        api_key=api_key,
        api_url=api_url,
        model=model,
        max_tokens=max_tokens,
        read_timeout_seconds=read_timeout,
        price_per_1k_prompt_usd=price_prompt,
        price_per_1k_completion_usd=price_completion,
        optional_params=optional_params,
    )
