from typing import List

import aiohttp

from .client import DeepSeekClient
from .session import ChatSession
from .stream_printer import StreamPrinter


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
        print("- /temps [temps] [question] - Compare temperatures (default 0,0.7,1.2)")
        print("- /provider - Show current provider and model")
        print("- /models - List available models for current provider")
        print("- /quit or /exit - Exit application")
        print("=" * 60)

    def _parse_temperatures(self, value: str) -> List[float]:
        parts = [p.strip() for p in value.split(",") if p.strip()]
        return [float(p) for p in parts]

    async def _handle_temps_command(self, user_input: str) -> None:
        parts = user_input.split(maxsplit=2)
        temps_str = "0,0.7,1.2"
        query = ""
        if len(parts) >= 2:
            temps_str = parts[1]
        if len(parts) == 3:
            query = parts[2]
        if not query:
            query = input("Prompt to compare: ").strip()
            if not query:
                return
        try:
            temperatures = self._parse_temperatures(temps_str)
        except ValueError:
            print(
                "❌ Invalid temperatures. Use comma-separated numbers, e.g. 0,0.7,1.2"
            )
            return

        messages = self._session.messages() + [{"role": "user", "content": query}]
        for t in temperatures:
            print("=" * 12, f"temperature={t}", "=" * 12)
            print("🤖 AI: ", end="", flush=True)
            printer = StreamPrinter(stall_seconds=3)
            response_parts: List[str] = []

            printer.start()
            try:
                async for chunk in self._client.stream_message(messages, temperature=t):
                    printer.on_chunk(chunk)
                    response_parts.append(chunk)
            finally:
                printer.stop()
                await printer.wait_closed()

            print()
            metrics = self._client.last_metrics()
            if metrics:
                duration_ms = metrics.duration_seconds * 1000.0
                usage_parts = []
                if metrics.prompt_tokens is not None:
                    usage_parts.append(f"prompt={metrics.prompt_tokens}")
                if metrics.completion_tokens is not None:
                    usage_parts.append(f"completion={metrics.completion_tokens}")
                if metrics.total_tokens is not None:
                    usage_parts.append(f"total={metrics.total_tokens}")
                usage_text = ", ".join(usage_parts) if usage_parts else "n/a"
                cost_text = (
                    f"${metrics.cost_usd:.6f}"
                    if metrics.cost_usd is not None
                    else "n/a"
                )
                print(
                    f"⏱️  Time: {duration_ms:.0f} ms | Tokens: {usage_text} | Cost: {cost_text}"
                )
            print()

    def _handle_provider_command(self) -> None:
        config = self._client._config
        print(f"ℹ️  provider: {config.provider}")
        print(f"ℹ️  model: {config.model}")

    async def _handle_models_command(self) -> None:
        config = self._client._config
        if not config.models_url:
            print("ℹ️  models endpoint is not configured for this provider.")
            return

        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(sock_read=config.read_timeout_seconds)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                config.models_url, headers=headers, timeout=timeout
            ) as response:
                if response.status != 200:
                    body_text = await response.text()
                    print(
                        f"❌ Models request failed: HTTP {response.status} | Body: {body_text}"
                    )
                    return
                payload = await response.json()

        data = payload.get("data", [])
        model_ids = sorted([m.get("id") for m in data if m.get("id")])

        if not model_ids:
            print("ℹ️  No models returned.")
            return

        print(f"✅ Available models ({len(model_ids)}):")
        for model_id in model_ids:
            print(f"- {model_id}")

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

                if user_input.lower() in ["/provider", "provider"]:
                    self._handle_provider_command()
                    continue

                if user_input.lower() in ["/models", "models"]:
                    await self._handle_models_command()
                    continue

                if user_input.lower().startswith("/temps"):
                    await self._handle_temps_command(user_input)
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

                metrics = self._client.last_metrics()
                if metrics:
                    duration_ms = metrics.duration_seconds * 1000.0
                    usage_parts = []
                    if metrics.prompt_tokens is not None:
                        usage_parts.append(f"prompt={metrics.prompt_tokens}")
                    if metrics.completion_tokens is not None:
                        usage_parts.append(f"completion={metrics.completion_tokens}")
                    if metrics.total_tokens is not None:
                        usage_parts.append(f"total={metrics.total_tokens}")
                    usage_text = ", ".join(usage_parts) if usage_parts else "n/a"
                    cost_text = (
                        f"${metrics.cost_usd:.6f}"
                        if metrics.cost_usd is not None
                        else "n/a"
                    )
                    print(
                        f"⏱️  Time: {duration_ms:.0f} ms | Tokens: {usage_text} | Cost: {cost_text}"
                    )

            except EOFError:
                print("👋 Goodbye!")
                break
            except KeyboardInterrupt:
                print("👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
