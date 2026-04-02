"""Linear MCP server tools and discovery parser."""

from __future__ import annotations

import json
import re
from typing import Any

from fastmcp import Client, Context, FastMCP

from mcp_remote import call_remote
from task_authz import authz_namespace


def parse_linear_projects(text: str) -> list[dict[str, str]]:
    """Parse linear_list_projects result → standardized ``[{"id": ..., "name": ...}]``."""
    try:
        data = json.loads(text)
        projects = (
            data
            if isinstance(data, list)
            else data.get("projects", data.get("nodes", []))
        )
        result: list[dict[str, str]] = []
        for proj in projects:
            if isinstance(proj, dict) and "id" in proj and "name" in proj:
                result.append({"id": proj["id"], "name": proj["name"]})
        if result:
            return result
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    # Fallback: regex
    id_pattern = re.compile(
        r'["\']?id["\']?\s*[:=]\s*["\']([^"\']+)["\']', re.IGNORECASE
    )
    name_pattern = re.compile(
        r'["\']?name["\']?\s*[:=]\s*["\']([^"\']+)["\']', re.IGNORECASE
    )

    ids = id_pattern.findall(text)
    names = name_pattern.findall(text)

    return [{"id": pid, "name": pname} for pid, pname in zip(ids, names)]


@authz_namespace("linear", "list_linear_projects", tool_resources={"linear_get_project": "query"}, resource_label="project")
def register_tools(mcp: FastMCP, client_ref: dict[str, Client]) -> None:
    """Register Linear tools on the FastMCP server.

    Args:
        client_ref: Dict container with key ``"c"`` populated during lifespan.
    """

    @mcp.tool(name="list_linear_projects")
    async def list_linear_projects(
        ctx: Context,
        query: str = "",
        team: str = "",
        state: str = "",
        limit: int = 50,
    ) -> str:
        """List Linear projects. Returns standardized [{"id": ..., "name": ...}] JSON."""
        args: dict[str, Any] = {}
        if query:
            args["query"] = query
        if team:
            args["team"] = team
        if state:
            args["state"] = state
        if limit != 50:
            args["limit"] = limit
        raw = await call_remote(client_ref["c"], "list_projects", args)
        return json.dumps(parse_linear_projects(raw))

    @mcp.tool(name="linear_get_project")
    async def linear_get_project(
        ctx: Context,
        query: str,
        includeMilestones: bool = False,
        includeMembers: bool = False,
    ) -> str:
        """Get a Linear project by name, ID, or slug."""
        args: dict[str, Any] = {"query": query}
        if includeMilestones:
            args["includeMilestones"] = includeMilestones
        if includeMembers:
            args["includeMembers"] = includeMembers
        return await call_remote(client_ref["c"], "get_project", args)
