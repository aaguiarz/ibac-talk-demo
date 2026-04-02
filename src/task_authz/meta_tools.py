"""Meta-tool registration for the authorization middleware.

Registers get_resource_metadata on a FastMCP server. The agent has
no write access to the FGA store.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from openfga_sdk import ReadRequestTupleKey
from openfga_sdk.exceptions import ApiException

from task_authz.resolution import _find_display_name, _get_task_id

if TYPE_CHECKING:
    from task_authz.middleware import OpenFGAPermissionMiddleware

logger = logging.getLogger(__name__)


def _parse_fga_object(
    fga_object: str,
    tool_resource_map: dict[str, tuple[str, str]],
    resource_registry: dict[str, dict[str, str]],
) -> tuple[str, str, str]:
    """Parse an FGA object into (tool_name, resource_id, display_name)."""
    if fga_object.startswith("tool_resource:"):
        rest = fga_object[len("tool_resource:"):]
        if "/" in rest:
            tool_name, resource_part = rest.split("/", 1)
            # Strip namespace prefix to recover the raw resource ID
            display = resource_part
            if tool_name in tool_resource_map:
                ns_name = tool_resource_map[tool_name][0]
                if resource_part.startswith(ns_name + "_"):
                    raw_id = resource_part[len(ns_name) + 1:]
                    display = _find_display_name(ns_name, raw_id, resource_registry)
            return tool_name, resource_part, display
        return rest, "*", "*"
    if fga_object.startswith("tool:"):
        return fga_object[len("tool:"):], "*", "*"
    return fga_object, "", ""


async def _read_grants(
    middleware: OpenFGAPermissionMiddleware,
    task_id: str,
    session_id: str,
    agent_user_id: str,
    scope_filter: str = "",
) -> list[dict[str, str]]:
    """Read all permission grants across scopes from FGA."""
    if not middleware._fga:
        return []

    queries: list[tuple[str, str, str]] = []
    if not scope_filter or scope_filter == "once":
        if task_id:
            queries.append(("once", f"task:{task_id}", "can_call_task"))
    if not scope_filter or scope_filter == "session":
        if session_id:
            queries.append(
                ("session", f"session:{session_id}#task", "can_call_session")
            )
    if not scope_filter or scope_filter == "always":
        if agent_user_id:
            queries.append(
                ("always", f"agent_user:{agent_user_id}#task", "can_call_agent_user")
            )

    # FGA read requires object type — query both tool and tool_resource
    object_types = ["tool:", "tool_resource:"]

    grants: list[dict[str, str]] = []
    for scope_name, user, relation in queries:
        for obj_type in object_types:
            try:
                response = await middleware._fga.read(
                    ReadRequestTupleKey(
                        user=user, relation=relation, object=obj_type
                    )
                )
                for t in response.tuples or []:
                    tool_name, resource, display = _parse_fga_object(
                        t.key.object,
                        middleware._tool_resource_map,
                        middleware._resource_registry,
                    )
                    grants.append(
                        {
                            "tool": tool_name,
                            "resource": display,
                            "scope": scope_name,
                            "fga_user": t.key.user,
                            "fga_relation": t.key.relation,
                            "fga_object": t.key.object,
                        }
                    )
            except (ApiException, ValueError, OSError) as e:
                logger.warning(
                    "Failed to read %s/%s grants: %s", scope_name, obj_type, e
                )

    return grants


def register_meta_tools(mcp: Any, middleware: OpenFGAPermissionMiddleware) -> None:
    """Register read-only authorization meta-tools on the FastMCP server."""
    _register_get_resource_metadata(mcp, middleware)


def _register_get_resource_metadata(mcp: Any, middleware: OpenFGAPermissionMiddleware) -> None:
    resource_types = middleware._resource_types

    @mcp.tool()
    async def get_resource_metadata() -> str:
        """List available resource types and their discovery tools."""
        return json.dumps([
            {"name": rt.name, "list_tool": rt.list_tool, "search_param": rt.search_param,
             "tool_resources": rt.tool_resources}
            for rt in resource_types
        ])


def _register_list_permissions(mcp: Any, middleware: OpenFGAPermissionMiddleware) -> None:
    from fastmcp import Context

    async def _list_permissions_impl(
        ctx: Context,
        scope: str = "",
    ) -> str:
        """List active permission grants for the current session.

        Optionally filter by scope: 'once', 'session', or 'always'.
        Returns session info and a JSON array of grants with tool, resource, and scope.
        """
        agent_user_id, session_id, _agent_id = middleware._get_session_info(ctx)
        task_id = _get_task_id(ctx)

        grants = await _read_grants(
            middleware, task_id, session_id, agent_user_id, scope
        )

        result = {
            "session_id": session_id,
            "task_id": task_id,
            "agent_user": agent_user_id,
            "permissions": [
                {"tool": g["tool"], "resource": g["resource"], "scope": g["scope"]}
                for g in grants
            ],
        }
        return json.dumps(result, indent=2)

    _list_permissions_impl.__globals__["Context"] = Context
    mcp.tool(name="list_permissions")(_list_permissions_impl)
