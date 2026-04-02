"""WebSocket endpoint — one per session.

Handles the WebSocket lifecycle: creates EventBus + FlowRunner on connect,
forwards events to the client, and routes client messages to the runner.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.backend.elicitation import AutoElicitationHandler, WebElicitationHandler
from web.backend.event_bus import Event, EventBus
from web.backend.flow_runner import FlowRunner

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_FLOWS = {"regular", "intention_discovery", "autonomous"}

FLOW_META = {
    "regular": {
        "name": "Regular Agent",
        "description": "Agent runs freely; middleware elicits permission inline when needed.",
    },
    "intention_discovery": {
        "name": "Intention Discovery",
        "description": "Plan permissions → discover resources → authorize → execute.",
    },
    "autonomous": {
        "name": "Autonomous Agent",
        "description": "Plan permissions → discover resources → auto-grant → execute.",
    },
}


@router.get("/api/flows")
async def list_flows() -> list[dict[str, Any]]:
    return [{"id": k, **v} for k, v in FLOW_META.items()]


@router.websocket("/ws/{flow_type}")
async def websocket_endpoint(websocket: WebSocket, flow_type: str) -> None:
    if flow_type not in VALID_FLOWS:
        await websocket.close(code=4000, reason=f"Invalid flow type: {flow_type}")
        return

    await websocket.accept()
    logger.info("WebSocket accepted for flow=%s", flow_type)

    event_bus = EventBus()
    # Keep a reference to running task so it doesn't get GC'd
    running_task: asyncio.Task[None] | None = None

    async def send_event(event: Event) -> None:
        try:
            await websocket.send_json(event.to_dict())
        except WebSocketDisconnect:
            import sys
            print(f"[WS] DISCONNECTED while sending {event.type}", file=sys.stderr, flush=True)
        except RuntimeError as exc:
            import sys
            print(f"[WS] RuntimeError sending {event.type}: {exc}", file=sys.stderr, flush=True)

    event_bus.subscribe(send_event)

    elicitation_handler: WebElicitationHandler | AutoElicitationHandler
    if flow_type == "autonomous":
        elicitation_handler = AutoElicitationHandler(event_bus)
    else:
        elicitation_handler = WebElicitationHandler(event_bus)

    runner = FlowRunner(flow_type, event_bus, elicitation_handler)

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "start":
                prompt = data.get("prompt", "")
                if prompt:
                    # Cancel previous task if still running
                    if running_task and not running_task.done():
                        running_task.cancel()
                    running_task = asyncio.create_task(runner.run(prompt))

            elif action == "elicitation_response":
                elicitation_id = data.get("id", "")
                value = data.get("value", "")
                if isinstance(elicitation_handler, WebElicitationHandler):
                    elicitation_handler.respond(elicitation_id, value)

    except WebSocketDisconnect:
        pass
    except json.JSONDecodeError:
        pass
    finally:
        if running_task and not running_task.done():
            running_task.cancel()
        event_bus.unsubscribe(send_event)
