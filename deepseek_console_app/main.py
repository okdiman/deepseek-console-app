#!/usr/bin/env python3
import asyncio

from deepseek_console_app.android_agent import AndroidAgent
from deepseek_console_app.client import DeepSeekClient
from deepseek_console_app.config import load_config
from deepseek_console_app.console_app import ConsoleApp
from deepseek_console_app.session import ChatSession


async def main() -> None:
    config = load_config()
    client = DeepSeekClient(config)
    session = ChatSession(max_messages=config.context_max_messages)
    agent = AndroidAgent(client, session)
    app = ConsoleApp(client, session, agent)
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Goodbye!")
