import asyncio
from typing import Optional


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
