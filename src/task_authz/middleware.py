"""OpenFGA-backed permission middleware for FastMCP.

Intercepts tool calls and enforces permission grants via OpenFGA.
Declarative namespace configs eliminate fuzzy resolution — the agent
resolves names upfront via always-callable discovery tools.

The check subject is always a task: check(task:T, can_call, tool:X).
One check resolves all three scopes (once/session/always) via the
relationship chain: task → session → agent_user.

Example:
    ```python
    @authz_namespace("slack", "list_slack_channels",
                     tool_resources={"slack_send_message": "channel_id"})
    def register_slack_tools(mcp): ...

    @authz_namespace("email", tool_resources={"send_email": "to"})
    def register_email_tools(mcp): ...

    perm = OpenFGAPermissionMiddleware()
    mcp = FastMCP("server", middleware=[perm])
    perm.setup(mcp, servers=[register_slack_tools, register_email_tools])
    ```
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from typing import Any

import mcp.types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware.middleware import (
    CallNext,
    Middleware,
    MiddlewareContext,
)
from fastmcp.tools.tool import ToolResult
from openfga_sdk import ClientConfiguration, OpenFgaClient
from openfga_sdk.client.models import (
    ClientCheckRequest,
    ClientTuple,
    ClientWriteRequest,
)

from task_authz.config import (
    _AUTHZ_ATTR,
    SCOPE_CHOICES,
    SCOPE_MAP,
    FGAConfig,
    ResourceType,
)
from task_authz.meta_tools import register_meta_tools
from task_authz.resolution import (
    _find_display_name,
    _get_task_id,
    _parse_standard_resources,
    _resolve_resource,
)
from utils import FGA_WRITE_OPTS, sanitize_fga_id

logger = logging.getLogger(__name__)


class OpenFGAPermissionMiddleware(Middleware):
    """Middleware that enforces per-tool permission grants via OpenFGA.

    Resource types can be provided either via the ``resource_types`` constructor
    parameter (useful in tests) or discovered automatically from functions
    decorated with :func:`authz_namespace` and passed to :meth:`setup`.

    Args:
        resource_types: Explicit resource type configs (mainly for tests).
        tool_config: Maps tool_name → None for tool-level (wildcard) checks.
        fga_config: OpenFGA connection settings.
        user_id: The human identity operating the agent.
    """

    def __init__(
        self,
        resource_types: list[ResourceType] | None = None,
        tool_config: dict[str, None] | None = None,
        fga_config: FGAConfig | None = None,
        user_id: str = "",
        agent_id: str = "",
    ):
        self._resource_types: list[ResourceType] = []
        self._tool_config = tool_config or {}
        self._fga_config = fga_config or FGAConfig()
        self._user_id = user_id or os.environ.get("FGA_USER_ID", "default")
        self._agent_id = agent_id or os.environ.get("FGA_AGENT_ID", "mcp_agent")
        self._agent_user_id = f"{self._user_id}__{self._agent_id}"

        # Derive tool_resource_map from resource type configs
        self._tool_resource_map: dict[str, tuple[str, str]] = {}

        # FGA client — initialized in setup/startup
        self._fga: OpenFgaClient | None = None

        # resource_type.name → {resource_id: display_name}, populated when list tools are called
        self._resource_registry: dict[str, dict[str, str]] = {}

        # Meta-tools bypass checks (discovery tools now require task-scoped grants)
        self._exempt_tools: set[str] = {
            "get_resource_metadata",
        }

        # id(session) → (agent_user_id, session_id, agent_id)
        self._session_info: dict[int, tuple[str, str, str]] = {}

        # Task IDs for which we've already written the membership tuple
        self._known_tasks: set[str] = set()

        # Discovery tools that require FGA checks (populated from resource types)
        self._list_tools: set[str] = set()

        # namespace name → resource_label (e.g. "slack" → "channel")
        self._resource_label_map: dict[str, str] = {}

        # Lock protecting mutable in-memory caches (_session_info,
        # _known_tasks, _resource_registry) against concurrent access.
        self._state_lock = asyncio.Lock()

        # Register any explicitly-provided resource types
        if resource_types:
            self._add_resource_types(resource_types)

    def _add_resource_types(self, resource_types: list[ResourceType]) -> None:
        """Register resource types and update derived maps."""
        for rt in resource_types:
            self._resource_types.append(rt)
            for tool_name, arg_name in rt.tool_resources.items():
                self._tool_resource_map[tool_name] = (rt.name, arg_name)
            if rt.list_tool:
                self._list_tools.add(rt.list_tool)
            self._resource_label_map[rt.name] = rt.resource_label

    async def clear_task_resources(self, task_id: str) -> None:
        """Remove task from known-tasks set so its registry can be refreshed.

        Called after task cleanup to prevent stale discovery data from
        leaking into subsequent tasks within the same session.
        """
        async with self._state_lock:
            self._known_tasks.discard(task_id)

    # -- lifecycle --

    def setup(
        self,
        mcp: Any,
        servers: list[Callable[..., Any]] | None = None,
    ) -> None:
        """Register meta-tools on the FastMCP server.

        Args:
            mcp: The FastMCP server instance.
            servers: Optional list of ``register_tools`` functions decorated
                with :func:`authz_namespace`. The middleware extracts resource
                type metadata from each annotation.
        """
        # Discover resource types from annotated register_tools functions
        if servers:
            discovered = [
                getattr(fn, _AUTHZ_ATTR)
                for fn in servers
                if hasattr(fn, _AUTHZ_ATTR)
            ]
            self._add_resource_types(discovered)

        register_meta_tools(mcp, self)

    async def startup(self) -> None:
        """Initialize FGA client and write public tool tuples."""
        if not self._fga_config.store_id:
            raise ValueError(
                "FGA store_id is required. Set FGA_STORE_ID env var or pass "
                "store_id in FGAConfig. Current FGA_STORE_ID is empty. "
                "See OPENFGA_MIDDLEWARE.md for setup."
            )
        config = ClientConfiguration(
            api_url=self._fga_config.api_url,
            store_id=self._fga_config.store_id,
        )
        self._fga = OpenFgaClient(config)

        # Write task:* can_call_agent_user for each exempt tool
        tuples = []
        for tool_name in self._exempt_tools:
            tuples.append(
                ClientTuple(
                    user="task:*",
                    relation="can_call_agent_user",
                    object=f"tool:{tool_name}",
                )
            )
        if tuples:
            await self._write_tuples(tuples)
            logger.info("Wrote %d public tool tuples", len(tuples))

    async def shutdown(self) -> None:
        """Close the FGA client."""
        if self._fga:
            await self._fga.close()
            self._fga = None

    # -- helpers --

    async def _write_tuples(self, tuples: list[ClientTuple]) -> None:
        """Write tuples to FGA, ignoring duplicates."""
        if not tuples or not self._fga:
            return
        await self._fga.write(
            ClientWriteRequest(writes=tuples),
            FGA_WRITE_OPTS,
        )


    async def _check(
        self, user: str, relation: str, obj: str,
        contextual_tuples: list[ClientTuple] | None = None,
    ) -> bool:
        """Run an FGA check.

        Raises on FGA connectivity/config errors so they surface clearly
        rather than being silently treated as "denied".
        """
        if not self._fga:
            return False
        resp = await self._fga.check(
            ClientCheckRequest(
                user=user,
                relation=relation,
                object=obj,
                contextual_tuples=contextual_tuples,
            )
        )
        return resp.allowed

    async def _batch_check(
        self,
        checks: list[tuple[str, str, str]],
        agent_user_id: str,
    ) -> dict[str, bool]:
        """Run multiple FGA checks in a single batch call.

        For tool_resource objects, a contextual parent_tool tuple is
        automatically included so wildcard tool-level grants propagate
        without persisting structural tuples.

        An ``agent_user_in_context`` contextual tuple is always included
        so the intersection check (base_can_call AND agent_user_in_context)
        passes. Without it, every check would be denied.

        Args:
            checks: List of (user, relation, object) tuples.
            agent_user_id: The agent_user running this task (required).

        Returns:
            Dict mapping fga_object → allowed.

        Raises:
            ValueError: If agent_user_id is empty.
        """
        if not agent_user_id:
            raise ValueError(
                "agent_user_id is required for FGA checks. "
                "The agent_user_in_context contextual tuple cannot be built "
                "without it — all checks would be denied."
            )
        if not self._fga or not checks:
            return {}
        from openfga_sdk.client.models import (
            ClientBatchCheckItem,
            ClientBatchCheckRequest,
        )

        # correlation_id must match ^[\w\d-]{1,36}$ — use index-based IDs
        # and map them back to fga objects
        id_to_obj: dict[str, str] = {}
        items = []
        for i, (user, relation, obj) in enumerate(checks):
            cid = str(i)
            id_to_obj[cid] = obj
            ctx_tuples: list[ClientTuple] = [
                ClientTuple(
                    user=f"agent_user:{agent_user_id}",
                    relation="agent_user_in_context",
                    object=obj,
                ),
            ]
            if obj.startswith("tool_resource:"):
                tool_name = obj[len("tool_resource:"):].split("/", 1)[0]
                ctx_tuples.append(ClientTuple(
                    user=f"tool:{tool_name}",
                    relation="parent_tool",
                    object=obj,
                ))
            items.append(
                ClientBatchCheckItem(
                    user=user, relation=relation, object=obj,
                    correlation_id=cid,
                    contextual_tuples=ctx_tuples,
                )
            )
        resp = await self._fga.batch_check(ClientBatchCheckRequest(checks=items))
        return {
            id_to_obj[r.correlation_id]: r.allowed
            for r in (resp.result or [])
            if r.error is None and r.correlation_id in id_to_obj
        }

    def _get_session_info(self, ctx: Any) -> tuple[str, str, str]:
        """Get (agent_user_id, session_id, agent_id) from cache."""
        sid = id(ctx.session)
        if sid in self._session_info:
            return self._session_info[sid]
        # Fallback: use config-driven identity
        session_id = ctx.session_id
        return self._agent_user_id, session_id, self._agent_id

    async def _ensure_task_membership(self, task_id: str, session_id: str) -> None:
        """Write task→session membership tuple if not already done."""
        async with self._state_lock:
            already_known = task_id in self._known_tasks
        if task_id and not already_known:
            await self._write_tuples(
                [
                    ClientTuple(
                        user=f"task:{task_id}",
                        relation="task",
                        object=f"session:{session_id}",
                    )
                ]
            )
            async with self._state_lock:
                self._known_tasks.add(task_id)

    def _build_fga_object(self, tool_name: str, args: dict[str, Any]) -> str | None:
        """Build the FGA object string for a tool call.

        Returns e.g. "tool_resource:slack_send_message/slack_C5XMACTML"
        or "tool:linear_list_projects" or None if not configured.
        """
        if tool_name in self._tool_resource_map:
            namespace, arg_name = self._tool_resource_map[tool_name]
            value = args.get(arg_name)
            if value:
                safe_value = sanitize_fga_id(str(value))
                resource_id = f"{namespace}_{safe_value}"
                return f"tool_resource:{tool_name}/{resource_id}"
            # No arg value → fall through to tool-level
            return f"tool:{tool_name}"

        if tool_name in self._tool_config:
            return f"tool:{tool_name}"

        if tool_name in self._list_tools:
            return f"tool:{tool_name}"

        return None  # Not configured → pass through

    async def _update_registry_if_list_tool(self, tool_name: str, result: ToolResult) -> None:
        """If tool_name is a list tool, parse the result and update the resource registry."""
        for rt in self._resource_types:
            if tool_name == rt.list_tool:
                text = ""
                if hasattr(result, "content"):
                    if isinstance(result.content, str):
                        text = result.content
                    elif isinstance(result.content, list):
                        for item in result.content:
                            if hasattr(item, "text"):
                                text += item.text
                elif isinstance(result, str):
                    text = result
                if text:
                    parsed = _parse_standard_resources(text)
                    async with self._state_lock:
                        self._resource_registry[rt.name] = parsed
                    logger.info(
                        "Updated %s registry: %d resources",
                        rt.name,
                        len(parsed),
                    )
                break

    def _contextual_parent_tool(self, tool_name: str, fga_object: str) -> list[ClientTuple] | None:
        """Build contextual parent_tool tuple for tool_resource checks."""
        if fga_object.startswith("tool_resource:"):
            return [ClientTuple(
                user=f"tool:{tool_name}",
                relation="parent_tool",
                object=fga_object,
            )]
        return None

    # -- hooks --

    async def on_initialize(
        self,
        context: MiddlewareContext[mt.InitializeRequest],
        call_next: CallNext[mt.InitializeRequest, mt.InitializeResult | None],
    ) -> mt.InitializeResult | None:
        """Called when MCP session starts. Write session setup tuples."""
        result = await call_next(context)

        ctx = context.fastmcp_context
        if ctx and ctx.session:
            session_id = ctx.session_id

            # Cache session info (identity is config-driven, not from clientInfo)
            async with self._state_lock:
                self._session_info[id(ctx.session)] = (
                    self._agent_user_id,
                    session_id,
                    self._agent_id,
                )

            # Write setup tuples
            await self._write_tuples(
                [
                    ClientTuple(
                        user=f"user:{self._user_id}",
                        relation="user",
                        object=f"agent_user:{self._agent_user_id}",
                    ),
                    ClientTuple(
                        user=f"agent:{self._agent_id}",
                        relation="agent",
                        object=f"agent_user:{self._agent_user_id}",
                    ),
                    ClientTuple(
                        user=f"session:{session_id}",
                        relation="session",
                        object=f"agent_user:{self._agent_user_id}",
                    ),
                ]
            )
            logger.info(
                "Session initialized: agent_user=%s session=%s",
                self._agent_user_id,
                session_id,
            )

        return result

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        args = context.message.arguments or {}
        ctx = context.fastmcp_context

        # 1. Exempt tools → pass through
        if tool_name in self._exempt_tools:
            return await call_next(context)

        if not ctx:
            return await call_next(context)

        # 2. Ensure task membership
        agent_user_id, session_id, _agent_id = self._get_session_info(ctx)
        task_id = _get_task_id(ctx)
        if not task_id:
            task_id = str(uuid.uuid4())
        await self._ensure_task_membership(task_id, session_id)

        auth_args = dict(args)
        resolved_display: str | None = None
        if tool_name in self._tool_resource_map:
            _ns_name, arg_name = self._tool_resource_map[tool_name]
            raw_resource = args.get(arg_name)
            if raw_resource:
                resolved_id, resolved_display, unresolved_message = (
                    _resolve_resource(
                        tool_name,
                        str(raw_resource),
                        self._tool_resource_map,
                        self._resource_registry,
                    )
                )
                if resolved_id is None:
                    raise ToolError(
                        unresolved_message
                        or "Permission denied: could not resolve resource."
                    )
                auth_args[arg_name] = resolved_id

        # 3. Build FGA object
        fga_object = self._build_fga_object(tool_name, auth_args)
        if fga_object is None:
            # Not configured → pass through unchecked
            return await call_next(context)

        # 4. Check permission (contextual parent_tool + agent_user_in_context)
        if not agent_user_id:
            raise ToolError(
                "Permission denied: agent_user_id is required for authorization checks."
            )
        contextual = self._contextual_parent_tool(tool_name, fga_object) or []
        contextual.append(
            ClientTuple(
                user=f"agent_user:{agent_user_id}",
                relation="agent_user_in_context",
                object=fga_object,
            )
        )
        allowed = await self._check(
            f"task:{task_id}", "can_call", fga_object, contextual,
        )
        if ctx:
            await ctx.info("fga_event", extra={
                "event_type": "fga_check",
                "user": f"task:{task_id}", "relation": "can_call",
                "object": fga_object, "allowed": allowed,
            })
        if allowed:
            result = await call_next(context)
            await self._update_registry_if_list_tool(tool_name, result)
            return result

        # 5. Denied → prompt user inline
        display = tool_name
        has_specific_resource = False
        if tool_name in self._tool_resource_map:
            ns_name, arg_name = self._tool_resource_map[tool_name]
            resource_val = auth_args.get(arg_name, "*")
            display_name = resolved_display or _find_display_name(
                ns_name, resource_val, self._resource_registry
            )
            display = f"{tool_name} on {display_name}"
            has_specific_resource = True

        # Build elicitation choices — add "Always, for every <label>" when applicable
        choices = list(SCOPE_CHOICES)
        if has_specific_resource and fga_object.startswith("tool_resource:"):
            ns_name = self._tool_resource_map[tool_name][0]
            label = self._resource_label_map.get(ns_name, "resource")
            choices.insert(-1, f"Always, for every {label}")

        elicit_result = await ctx.elicit(
            message=f"The agent wants to call {display}. Allow?",
            response_type=choices,  # type: ignore[arg-type]
        )
        if elicit_result.action != "accept":
            raise ToolError("Permission denied by user.")

        raw = elicit_result.data
        grant_object = fga_object
        if isinstance(raw, str) and raw.lower().startswith("always, for every"):
            # "Always, for every <label>" → tool-level always grant
            scope = "always"
            grant_object = f"tool:{tool_name}"
        else:
            scope = SCOPE_MAP.get(raw.lower(), "once") if isinstance(raw, str) else "once"
        if scope == "deny":
            raise ToolError("Permission denied by user.")

        grant_tuples = self._build_grant_tuples(
            scope, task_id, session_id, agent_user_id, grant_object, tool_name
        )
        await self._write_tuples(grant_tuples)
        if ctx:
            await ctx.info("fga_event", extra={
                "event_type": "fga_write",
                "tuples": [
                    {"user": t.user, "relation": t.relation, "object": t.object}
                    for t in grant_tuples
                ],
                "scope": scope,
            })
        result = await call_next(context)
        await self._update_registry_if_list_tool(tool_name, result)
        return result

    # -- grant tuple building --

    def _build_grant_tuples(
        self,
        scope: str,
        task_id: str,
        session_id: str,
        agent_user_id: str,
        fga_object: str,
        tool_name: str,
    ) -> list[ClientTuple]:
        """Build the grant tuples for a given scope."""
        tuples: list[ClientTuple] = []

        if scope == "once":
            tuples.append(
                ClientTuple(
                    user=f"task:{task_id}",
                    relation="can_call_task",
                    object=fga_object,
                )
            )
        elif scope == "session":
            tuples.append(
                ClientTuple(
                    user=f"session:{session_id}#task",
                    relation="can_call_session",
                    object=fga_object,
                )
            )
        elif scope == "always":
            tuples.append(
                ClientTuple(
                    user=f"agent_user:{agent_user_id}#task",
                    relation="can_call_agent_user",
                    object=fga_object,
                )
            )

        return tuples
