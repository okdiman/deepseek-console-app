from typing import List

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
