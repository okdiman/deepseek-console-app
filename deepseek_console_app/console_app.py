import aiohttp

from .android_agent import AndroidAgent
from .client import DeepSeekClient
from .session import ChatSession
from .stream_printer import StreamPrinter


class ConsoleApp:
    def __init__(
        self, client: DeepSeekClient, session: ChatSession, agent: AndroidAgent
    ) -> None:
        self._client = client
        self._session = session
        self._agent = agent
        self._session_cost_usd = 0.0

    def print_welcome(self) -> None:
        print("=" * 60)
        print("🚀 DeepSeek Console Application")
        print("=" * 60)
        print("Commands:")
        print("- Type any question to get AI response")
        print("- /help - Show this help")
        print("- /clear - Clear chat context")
        print("- /context - Show chat history size")
        print("- /provider - Show current provider and model")
        print("- /models - List available models for current provider")
        print("- /quit or /exit - Exit application")
        print("=" * 60)

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

        config = self._client._config
        if config.persist_context:
            self._session.load(config.context_path)

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

                if user_input.lower() in ["/clear", "clear"]:
                    self._session.clear()
                    self._session_cost_usd = 0.0
                    if config.persist_context:
                        self._session.save(
                            config.context_path, config.provider, config.model
                        )
                    print("🧹 Context cleared.")
                    continue

                if user_input.lower() in ["/context", "context"]:
                    message_count = len(self._session.messages())
                    print(f"📚 Context size: {message_count} messages.")
                    continue

                if user_input.lower() in ["/provider", "provider"]:
                    self._handle_provider_command()
                    continue

                if user_input.lower() in ["/models", "models"]:
                    await self._handle_models_command()
                    continue

                print("🤖 AI: ", end="", flush=True)
                printer = StreamPrinter(stall_seconds=3)

                printer.start()
                try:
                    async for chunk in self._agent.stream_reply(user_input):
                        printer.on_chunk(chunk)
                finally:
                    printer.stop()
                    await printer.wait_closed()

                print()

                if config.persist_context:
                    self._session.save(
                        config.context_path, config.provider, config.model
                    )

                token_stats = self._agent.last_token_stats()
                if token_stats:
                    req = token_stats.request
                    hist = token_stats.history
                    resp = token_stats.response
                    print(
                        "🧮 Tokens (local): "
                        f"request={req.tokens} ({req.method}), "
                        f"history={hist.tokens} ({hist.method}), "
                        f"response={resp.tokens} ({resp.method})"
                    )

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
                    if metrics.cost_usd is not None:
                        self._session_cost_usd += metrics.cost_usd
                    session_cost_text = f"${self._session_cost_usd:.6f}"
                    print(
                        f"⏱️  Time: {duration_ms:.0f} ms | Tokens: {usage_text} | Cost: {cost_text} | Session Cost: {session_cost_text}"
                    )

            except EOFError:
                print("👋 Goodbye!")
                break
            except KeyboardInterrupt:
                print("👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
