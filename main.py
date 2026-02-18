#!/usr/bin/env python3
import asyncio

from deepseek_console_app.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Goodbye!")
