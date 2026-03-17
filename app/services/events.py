"""In-memory SSE pub/sub for live UI updates."""
import asyncio
import json
import logging
from collections import defaultdict

logger = logging.getLogger("seaclip.events")


class EventBus:
    def __init__(self):
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._queues[channel].append(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue):
        if q in self._queues[channel]:
            self._queues[channel].remove(q)

    async def publish(self, channel: str, event_type: str, data: dict | str = ""):
        payload = data if isinstance(data, str) else json.dumps(data)
        dead = []
        for q in self._queues[channel]:
            try:
                q.put_nowait({"event": event_type, "data": payload})
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._queues[channel].remove(q)


event_bus = EventBus()
