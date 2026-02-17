#!/usr/bin/env python3
import asyncio
import aiohttp
from dotenv import load_dotenv
import os

load_dotenv()

async def test_api():
    api_key = os.getenv('DEEPSEEK_API_KEY')
    api_url = 'https://api.deepseek.com/v1/chat/completions'
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'model': 'deepseek-chat',
        'messages': [{'role': 'user', 'content': 'Hello, please respond with just: API test successful'}],
        'max_tokens': 50
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as response:
                print(f'Status: {response.status}')
                if response.status == 200:
                    data = await response.json()
                    print(f'Response: {data["choices"][0]["message"]["content"]}')
                else:
                    text = await response.text()
                    print(f'Error: {text}')
    except Exception as e:
        print(f'Exception: {e}')

if __name__ == '__main__':
    asyncio.run(test_api())
