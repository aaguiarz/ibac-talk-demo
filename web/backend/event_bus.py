"""Async event pub/sub for observability events.

Each WebSocket session gets its own EventBus instance. The FlowRunner
emits events, and the WebSocket handler subscribes to forward them.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    """A single observability event."""

    type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data, "timestamp": self.timestamp}


Subscriber = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Simple async pub/sub for a single session."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

    def subscribe(self, callback: Subscriber) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Subscriber) -> None:
        self._subscribers = [s for s in self._subscribers if s is not callback]

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        event = Event(type=event_type, data=data or {})
        if event_type == "agent_text":
            import sys
            print(f"[EventBus] emit agent_text, subscribers={len(self._subscribers)}", file=sys.stderr, flush=True)
        for subscriber in self._subscribers:
            try:
                await subscriber(event)
                if event_type == "agent_text":
                    import sys
                    print("[EventBus] agent_text sent OK to subscriber", file=sys.stderr, flush=True)
            except Exception as exc:
                import sys
                print(f"[EventBus] ERROR sending {event_type}: {exc!r}", file=sys.stderr, flush=True)
