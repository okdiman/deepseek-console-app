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
    provider: str
    api_key: str
    api_url: str
    models_url: str
    model: str
    max_tokens: int
    read_timeout_seconds: int
    price_per_1k_prompt_usd: float
    price_per_1k_completion_usd: float
    persist_context: bool
    context_path: str
    context_max_messages: int
    optional_params: OptionalRequestParams = field(
        default_factory=OptionalRequestParams
    )


def load_config() -> ClientConfig:
    load_dotenv()

    provider = os.getenv("PROVIDER", "deepseek").strip().lower()
    if provider not in ["deepseek", "groq"]:
        print("Error: PROVIDER must be 'deepseek' or 'groq'!")
        sys.exit(1)

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            print("Error: GROQ_API_KEY not found!")
            sys.exit(1)

        read_timeout = int(os.getenv("GROQ_API_TIMEOUT_SECONDS", "60"))
        max_tokens = int(os.getenv("GROQ_API_MAX_TOKENS", "4000"))
        model = os.getenv("GROQ_API_MODEL", "moonshotai/kimi-k2-instruct")
        api_url = os.getenv(
            "GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"
        )
        models_url = os.getenv(
            "GROQ_MODELS_URL", "https://api.groq.com/openai/v1/models"
        )
        price_prompt = float(os.getenv("GROQ_PRICE_PER_1K_PROMPT_USD", "0.0"))
        price_completion = float(os.getenv("GROQ_PRICE_PER_1K_COMPLETION_USD", "0.0"))
    else:
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
        models_url = os.getenv("DEEPSEEK_MODELS_URL", "")
        price_prompt = float(os.getenv("DEEPSEEK_PRICE_PER_1K_PROMPT_USD", "0.00028"))
        price_completion = float(
            os.getenv("DEEPSEEK_PRICE_PER_1K_COMPLETION_USD", "0.00042")
        )

    defaults = OptionalRequestParams()
    optional_params = defaults

    persist_context_raw = os.getenv("DEEPSEEK_PERSIST_CONTEXT", "true").strip().lower()
    persist_context = persist_context_raw not in {"0", "false", "no", "off"}
    context_path = os.getenv(
        "DEEPSEEK_CONTEXT_PATH",
        os.path.expanduser("~/.deepseek_console_app/context.json"),
    )
    context_max_messages = int(os.getenv("DEEPSEEK_CONTEXT_MAX_MESSAGES", "40"))

    print(f"ℹ️  provider: {provider}")
    print(f"ℹ️  model: {model}")
    print(f"ℹ️  temperature: {optional_params.temperature}")

    return ClientConfig(
        provider=provider,
        api_key=api_key,
        api_url=api_url,
        models_url=models_url,
        model=model,
        max_tokens=max_tokens,
        read_timeout_seconds=read_timeout,
        price_per_1k_prompt_usd=price_prompt,
        price_per_1k_completion_usd=price_completion,
        persist_context=persist_context,
        context_path=context_path,
        context_max_messages=context_max_messages,
        optional_params=optional_params,
    )
