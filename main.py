#!/usr/bin/env python3
import os
import sys
import asyncio
import aiohttp
import json
from dotenv import load_dotenv

load_dotenv()

async def send_message_to_api(message):
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "❌ API key not found"
        
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": message}], "max_tokens": 4000}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    text = await response.text()
                    return f"❌ HTTP Error {response.status}: {text[:100]}"
                    
                data = await response.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ Error: {type(e).__name__}: {str(e)}"

async def main():
    print("=" * 60)
    print("🚀 DeepSeek Console Application")
    print("=" * 60)
    print("Commands: /help, /debug, /quit")
    print("=" * 60)
    
    while True:
        try:
            user_input = input("Your message: ").strip()
            
            if not user_input:
                continue
                
            if user_input == "/quit":
                print("👋 Goodbye!")
                break
            elif user_input == "/debug":
                print("🔍 Testing API...")
                result = await send_message_to_api("Test message")
                print(f"📋 Result: {result}")
            elif user_input == "/help":
                print("Commands: /help, /debug, /quit")
            else:
                print("🤖 AI: Processing...")
                response = await send_message_to_api(user_input)
                print(f"🤖 AI: {response}")
                
        except (EOFError, KeyboardInterrupt):
            print("👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())