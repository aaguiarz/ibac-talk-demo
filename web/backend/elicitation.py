"""WebElicitationHandler — bridges MCP elicitation to WebSocket.

When the MCP middleware needs user input (scope picker), the handler
emits an elicitation event via EventBus and waits for the response
from the WebSocket client.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from web.backend.event_bus import EventBus


class WebElicitationHandler:
    """Bridges MCP server elicitation requests to the WebSocket client."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._pending: dict[str, asyncio.Future[str]] = {}

    async def handle(
        self, message: str, response_type: Any, params: Any, context: Any
    ) -> dict[str, Any]:
        """Called by MCP client when the server requests elicitation."""
        elicitation_id = str(uuid.uuid4())[:8]

        options: list[str] = []
        if isinstance(response_type, list):
            options = [str(o) for o in response_type]
        elif isinstance(response_type, type) and hasattr(
            response_type, "__dataclass_fields__"
        ):
            for field_name, field_info in response_type.__dataclass_fields__.items():
                field_type = field_info.type
                if hasattr(field_type, "__args__"):
                    options = [str(a) for a in field_type.__args__]
                    break

        await self._event_bus.emit(
            "elicitation",
            {
                "id": elicitation_id,
                "message": message,
                "options": options,
            },
        )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[elicitation_id] = future

        try:
            value = await asyncio.wait_for(future, timeout=300)
        except TimeoutError:
            return {"value": "Do not allow"}
        finally:
            self._pending.pop(elicitation_id, None)

        return {"value": value}

    def respond(self, elicitation_id: str, value: str) -> None:
        """Called when the WebSocket client sends an elicitation response."""
        future = self._pending.get(elicitation_id)
        if future and not future.done():
            future.set_result(value)


class AutoElicitationHandler:
    """Auto-mode handler that emits the event and returns immediately."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(
        self, message: str, response_type: Any, params: Any, context: Any
    ) -> None:
        """Abort — elicitation means the tool wasn't pre-authorized."""
        from authz_flow import UnauthorizedToolError

        await self._event_bus.emit(
            "elicitation",
            {
                "id": "auto",
                "message": message,
                "options": [],
                "auto_denied": True,
            },
        )
        raise UnauthorizedToolError(
            f"The agent tried to use a tool that was not pre-authorized.\n"
            f"  Server asked: {message}\n"
            f"  The agent was stopped before taking any unauthorized action."
        )
