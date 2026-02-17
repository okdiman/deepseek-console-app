#!/usr/bin/env python3
import os
import sys
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

class DeepSeekClient:
    def __init__(self):
        self.api_key = os.getenv('DEEPSEEK_API_KEY')
        self.api_url = 'https://api.deepseek.com/v1/chat/completions'
        
        if not self.api_key:
            print('Error: DEEPSEEK_API_KEY not found!')
            sys.exit(1)
    
    async def send_message(self, message: str) -> str:
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'model': 'deepseek-chat',
            'messages': [{'role': 'user', 'content': message}],
            'max_tokens': 4000
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=headers, json=payload, timeout=timeout) as response:
                    if response.status != 200:
                        return f'Error: HTTP {response.status}'
                    
                    data = await response.json()
                    return data['choices'][0]['message']['content']
                    
        except Exception as e:
            return f'Error: {str(e)}'

class ConsoleApp:
    def __init__(self):
        self.client = DeepSeekClient()
    
    def print_welcome(self):
        print('=' * 60)
        print('🚀 DeepSeek Console Application')
        print('=' * 60)
        print('Commands:')
        print('- Type any question to get AI response')
        print('- /help - Show this help')
        print('- /quit or /exit - Exit application')
        print('=' * 60)
    
    async def run(self):
        self.print_welcome()
        
        while True:
            try:
                user_input = input('Your message: ').strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() in ['/quit', '/exit', 'quit', 'exit']:
                    print('👋 Goodbye!')
                    break
                elif user_input.lower() in ['/help', 'help']:
                    self.print_welcome()
                    continue
                
                print('🤖 AI: Processing...')
                response = await self.client.send_message(user_input)
                print(f'🤖 AI: {response}')
                    
            except EOFError:
                print('👋 Goodbye!')
                break
            except KeyboardInterrupt:
                print('👋 Goodbye!')
                break
            except Exception as e:
                print(f'❌ Error: {e}')

async def main():
    app = ConsoleApp()
    await app.run()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('👋 Goodbye!')
        sys.exit(0)
