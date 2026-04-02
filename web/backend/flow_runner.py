"""FlowRunner — wraps authz_flow logic per flow type, injecting event emission.

Each WebSocket session creates its own FlowRunner. The runner imports
functions directly from src/authz_flow.py and wraps them with observability events.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from anthropic import AsyncAnthropic
from fastmcp import Client
from openfga_sdk import OpenFgaClient
from openfga_sdk.client.models import ClientTuple
from openfga_sdk.exceptions import FgaValidationException, ValidationException

from authz_flow import (
    PermissionDeniedError,
    ResolutionError,
    cleanup_fga_after_task,
    get_server_script,
    init_fga_client,
    run_agent_loop,
    run_authz_pipeline,
)
from web.backend.elicitation import AutoElicitationHandler, WebElicitationHandler
from web.backend.event_bus import EventBus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Web-specific callback implementations
# ---------------------------------------------------------------------------


class EventBusObserver:
    """Implements FlowObserver by forwarding events to the EventBus."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus

    async def on_event(self, event_type: str, data: dict[str, Any]) -> None:
        await self._bus.emit(event_type, data)


class WebAgentLoopCallbacks:
    """Implements AgentLoopCallbacks by emitting events via the EventBus."""

    def __init__(self, event_bus: EventBus, flow_type: str) -> None:
        self._bus = event_bus
        self._flow_type = flow_type

    async def on_text(self, text: str, done: bool) -> None:
        await self._bus.emit("agent_text", {"text": text, "done": done})

    async def on_tool_start(self, call_id: str, tool: str, args: dict[str, Any]) -> None:
        await self._bus.emit("tool_call_start", {
            "id": call_id,
            "tool": tool,
            "args": args,
        })

    async def on_tool_end(self, call_id: str, tool: str, result: str | None, error: str | None) -> None:
        await self._bus.emit("tool_call_end", {
            "id": call_id,
            "tool": tool,
            "result": result[:500] if result else result,
            "error": error,
        })

    async def on_unauthorized(self, tool: str, error: str) -> None:
        await self._bus.emit("tool_call_end", {
            "id": f"unauthorized_{tool}",
            "tool": tool,
            "result": None,
            "error": error,
        })
        await self._bus.emit("agent_text", {
            "text": f"\nUnauthorized tool call blocked: {tool}\n{error}",
            "done": True,
        })

    async def on_turn_complete(self) -> None:
        await self._bus.emit("agent_turn_complete", {})


# ---------------------------------------------------------------------------
# FlowRunner
# ---------------------------------------------------------------------------


class WebPermissionApprover:
    """Asks the user to approve planned permissions via WebSocket elicitation."""

    def __init__(self, elicitation_handler: WebElicitationHandler) -> None:
        self._handler = elicitation_handler

    async def approve(self, permissions: list[str], phase: str) -> bool:
        lines = [f"The agent needs these permissions ({phase}):\n"]
        for perm in permissions:
            tool_name, resource = perm.split(":", 1) if ":" in perm else (perm, "*")
            if resource == "*":
                lines.append(f"  - {tool_name}")
            else:
                lines.append(f"  - {tool_name} on {resource}")
        message = "\n".join(lines)
        result = await self._handler.handle(
            message, ["Approve", "Deny"], None, None,
        )
        value = result.get("value", "Deny") if isinstance(result, dict) else "Deny"
        return value == "Approve"


class FlowRunner:
    """Runs one of the three authorization flows with event emission."""

    def __init__(
        self,
        flow_type: str,
        event_bus: EventBus,
        elicitation_handler: WebElicitationHandler | AutoElicitationHandler,
    ) -> None:
        self.flow_type = flow_type
        self.event_bus = event_bus
        self.elicitation_handler = elicitation_handler
        self._fga_client: OpenFgaClient | None = None
        self._anthropic: AsyncAnthropic | None = None

    def _get_anthropic_client(self) -> AsyncAnthropic:
        if self._anthropic is None:
            self._anthropic = AsyncAnthropic(
                base_url="https://api.anthropic.com",
                max_retries=3,
            )
        return self._anthropic

    async def run(self, prompt: str) -> None:
        """Run the selected flow end-to-end."""
        task_id = str(uuid.uuid4())
        fga_tuples: list[ClientTuple] = []

        await self.event_bus.emit("task_created", {"task_id": task_id})
        await self.event_bus.emit("flow_status", {"phase": "connecting"})

        server_script = get_server_script()

        # Suppress library noise but allow info-level for fga_event messages
        os.environ["FASTMCP_LOG_LEVEL"] = "ERROR"
        os.environ["FASTMCP_SHOW_SERVER_BANNER"] = "false"

        async def _handle_server_log(params: Any) -> None:
            """Capture structured fga_event log messages from the middleware."""
            data = params.data if hasattr(params, "data") else None
            if data is None:
                return
            extra = getattr(data, "extra", None)
            if isinstance(data, dict):
                extra = data.get("extra")
            if not isinstance(extra, dict):
                return
            event_type = extra.get("event_type")
            if event_type in ("fga_write", "fga_check", "fga_batch_check", "fga_delete"):
                await self.event_bus.emit(event_type, {
                    k: v for k, v in extra.items() if k != "event_type"
                })

        mcp_client = Client(
            server_script,
            elicitation_handler=self.elicitation_handler.handle,
            log_handler=_handle_server_log,
        )

        try:
            async with mcp_client:
                await self.event_bus.emit("mcp_connection", {
                    "server": server_script,
                    "status": "connected",
                })

                tools = await mcp_client.list_tools()
                await self.event_bus.emit("mcp_tools_listed", {
                    "tools": [t.name for t in tools],
                    "count": len(tools),
                })

                internal_tools = {
                    "register_resource_alias",
                    "get_resource_metadata",
                }
                agent_tools = [t for t in tools if t.name not in internal_tools]
                planner_tools = agent_tools

                await self.event_bus.emit("flow_status", {"phase": "connecting"})

                if self.flow_type == "regular":
                    await self._run_regular_flow(
                        mcp_client, agent_tools, prompt, task_id,
                    )
                elif self.flow_type in ("intention_discovery", "autonomous"):
                    fga_tuples = await self._run_pipeline_flow(
                        mcp_client, planner_tools, agent_tools, prompt, task_id,
                    )
        except Exception as exc:
            await self.event_bus.emit("flow_status", {"phase": "error", "error": str(exc)})
            await self.event_bus.emit("agent_text", {"text": f"\nError: {exc}", "done": True})
            return
        finally:
            await self.event_bus.emit("flow_status", {"phase": "complete"})
            try:
                await cleanup_fga_after_task(self._fga_client, task_id, fga_tuples)
            except (ValidationException, FgaValidationException, RuntimeError, OSError) as exc:
                logger.warning("Cleanup failed: %r", exc)
            await self.event_bus.emit("task_cleanup", {"task_id": task_id, "tuples_deleted": len(fga_tuples)})
            if self._fga_client:
                await self._fga_client.close()
                self._fga_client = None

    # ------------------------------------------------------------------
    # Flow: Regular Agent (middleware handles elicitation inline)
    # ------------------------------------------------------------------

    async def _run_regular_flow(
        self,
        mcp_client: Client,
        agent_tools: list[Any],
        prompt: str,
        task_id: str,
    ) -> None:
        await self.event_bus.emit("flow_status", {"phase": "executing"})
        callbacks = WebAgentLoopCallbacks(self.event_bus, self.flow_type)
        await run_agent_loop(
            mcp_client, prompt, agent_tools, task_id,
            self._get_anthropic_client(), callbacks,
            autonomous=False, streaming=True,
        )

    # ------------------------------------------------------------------
    # Flow: Pipeline (intention_discovery + autonomous share this)
    # ------------------------------------------------------------------

    async def _run_pipeline_flow(
        self,
        mcp_client: Client,
        planner_tools: list[Any],
        agent_tools: list[Any],
        prompt: str,
        task_id: str,
    ) -> list[ClientTuple]:
        autonomous = self.flow_type == "autonomous"
        observer = EventBusObserver(self.event_bus)
        callbacks = WebAgentLoopCallbacks(self.event_bus, self.flow_type)

        self._fga_client = init_fga_client()
        if not self._fga_client:
            await self.event_bus.emit("agent_text", {
                "text": "Error: OpenFGA not configured. Set FGA_STORE_ID in .env and ensure OpenFGA is running.",
                "done": True,
            })
            return []

        # Non-autonomous pipeline flows get an approver for user confirmation
        approver = None
        if not autonomous and isinstance(self.elicitation_handler, WebElicitationHandler):
            approver = WebPermissionApprover(self.elicitation_handler)

        try:
            fga_tuples = await run_authz_pipeline(
                mcp_client, planner_tools, agent_tools, prompt, task_id,
                self._get_anthropic_client(), callbacks,
                autonomous=autonomous,
                fga_client=self._fga_client,
                observer=observer,
                streaming=True,
                approver=approver,
            )
        except PermissionDeniedError:
            await self.event_bus.emit("agent_text", {"text": "Permissions denied.", "done": True})
            return []
        except ResolutionError as exc:
            await self.event_bus.emit("agent_text", {
                "text": f"Could not resolve: {', '.join(exc.unresolved)}",
                "done": True,
            })
            return []

        return fga_tuples
