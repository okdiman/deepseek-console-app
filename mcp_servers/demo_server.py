import asyncio
from mcp.server.fastmcp import FastMCP

# Указываем имя нашего сервера
mcp = FastMCP("Local Demo Server")

@mcp.tool()
def get_weather(city: str) -> str:
    """Определяет текущую погоду в указанном городе."""
    # Заглушка, в реальности здесь был бы запрос к API погоды
    weather_data = {
        "Москва": "Облачно, -2°C",
        "Лондон": "Дождь, +12°C",
        "Нью-Йорк": "Солнечно, +15°C",
        "Мадрид": "Солнечно, +20°C",
    }
    return weather_data.get(city, f"Погода для города {city} неизвестна")

@mcp.tool()
def echo(text: str) -> str:
    """Возвращает переданный текст без изменений (эхо)."""
    return f"Эхо-ответ: {text}"

if __name__ == "__main__":
    # По умолчанию FastMCP запускается в режиме stdio
    mcp.run()
