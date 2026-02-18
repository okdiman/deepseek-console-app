#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import AsyncGenerator, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ClientConfig:
    api_key: str
    api_url: str = "https://api.deepseek.com/v1/chat/completions"
    model: str = "deepseek-chat"
    max_tokens: int = 4000
    read_timeout_seconds: int = 60


class ChatSession:
    def __init__(self, max_messages: int = 40) -> None:
        self._messages: List[Dict[str, str]] = []
        self._max_messages = max_messages

    def add_user(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, content: str) -> None:
        self._messages.append({"role": "assistant", "content": content})
        self._trim()

    def messages(self) -> List[Dict[str, str]]:
        return list(self._messages)

    def _trim(self) -> None:
        if len(self._messages) > self._max_messages:
            self._messages = self._messages[-self._max_messages :]


class DeepSeekClient:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config

    async def stream_message(
        self, messages: List[Dict[str, str]]
    ) -> AsyncGenerator[str, None]:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": self._config.max_tokens,
            "stream": True,
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


class StreamPrinter:
    def __init__(self, stall_seconds: int = 3) -> None:
        self._stall_seconds = stall_seconds
        self._progress_task: Optional[asyncio.Task] = None
        self._last_token_time: float = 0.0
        self._last_progress_time: float = 0.0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._last_token_time = self._loop.time()
        self._last_progress_time = self._last_token_time
        self._progress_task = asyncio.create_task(self._progress_indicator())

    def stop(self) -> None:
        if not self._progress_task:
            return
        self._progress_task.cancel()

    async def wait_closed(self) -> None:
        if not self._progress_task:
            return
        try:
            await self._progress_task
        except asyncio.CancelledError:
            pass

    def on_chunk(self, chunk: str) -> None:
        if self._loop:
            self._last_token_time = self._loop.time()
        print(chunk, end="", flush=True)

    async def _progress_indicator(self) -> None:
        assert self._loop is not None
        while True:
            await asyncio.sleep(1)
            now = self._loop.time()
            if (
                now - self._last_token_time >= self._stall_seconds
                and now - self._last_progress_time >= self._stall_seconds
            ):
                print("...", end="", flush=True)
                self._last_progress_time = now


class ConsoleApp:
    def __init__(self, client: DeepSeekClient, session: ChatSession) -> None:
        self._client = client
        self._session = session

    def print_welcome(self) -> None:
        print("=" * 60)
        print("🚀 DeepSeek Console Application")
        print("=" * 60)
        print("Commands:")
        print("- Type any question to get AI response")
        print("- /help - Show this help")
        print("- /quit or /exit - Exit application")
        print("=" * 60)

    async def run(self) -> None:
        self.print_welcome()

        while True:
            try:
                user_input = input("Your message: ").strip()
                if not user_input:
                    continue

                if user_input.lower() in ["/quit", "/exit", "quit", "exit"]:
                    print("👋 Goodbye!")
                    break
                if user_input.lower() in ["/help", "help"]:
                    self.print_welcome()
                    continue

                self._session.add_user(user_input)

                print("🤖 AI: ", end="", flush=True)
                printer = StreamPrinter(stall_seconds=3)
                response_parts: List[str] = []

                printer.start()
                try:
                    async for chunk in self._client.stream_message(
                        self._session.messages()
                    ):
                        printer.on_chunk(chunk)
                        response_parts.append(chunk)
                finally:
                    printer.stop()
                    await printer.wait_closed()

                print()
                response = "".join(response_parts).strip()
                self._session.add_assistant(response)

            except EOFError:
                print("👋 Goodbye!")
                break
            except KeyboardInterrupt:
                print("👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")


def load_config() -> ClientConfig:
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

    return ClientConfig(
        api_key=api_key,
        api_url=api_url,
        model=model,
        max_tokens=max_tokens,
        read_timeout_seconds=read_timeout,
    )


async def main() -> None:
    config = load_config()
    client = DeepSeekClient(config)
    session = ChatSession(max_messages=40)
    app = ConsoleApp(client, session)
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Goodbye!")
        sys.exit(0)
