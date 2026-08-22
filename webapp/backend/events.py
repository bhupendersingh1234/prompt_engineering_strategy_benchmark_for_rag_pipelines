"""
A tiny in-process pub/sub bus that bridges the synchronous background
pipeline thread (job.py, which makes blocking OpenAI calls via LangChain)
to the async WebSocket clients in main.py.

`emit()` is called from the worker thread. `asyncio.run_coroutine_threadsafe`
is the standard-library-documented way to safely hand work from a non-event-
loop thread back onto a running asyncio loop, which is why the bus stashes a
reference to that loop at FastAPI startup (`bind_loop`).
"""
import asyncio
from collections import deque


class EventBus:
    def __init__(self, history_size: int = 500):
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.history: deque = deque(maxlen=history_size)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)

    async def _publish(self, event: dict) -> None:
        self.history.append(event)
        for q in list(self._clients):
            q.put_nowait(event)

    def emit(self, event: dict) -> None:
        """Thread-safe. Call from any thread, including the background job thread."""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._publish(event), self._loop)


bus = EventBus()
