"""Slack MCP server tools and discovery parser."""

from __future__ import annotations

import json
import re
from typing import Any

from fastmcp import Client, Context, FastMCP

from mcp_remote import call_remote
from task_authz import authz_namespace


def parse_slack_channels(text: str) -> list[dict[str, str]]:
    """Parse slack_search_channels result → standardized ``[{"id": ..., "name": ...}]``."""
    try:
        data = json.loads(text)
        channels = (
            data
            if isinstance(data, list)
            else data.get("channels", data.get("results", data.get("items", [])))
        )
        result: list[dict[str, str]] = []
        for channel in channels:
            if not isinstance(channel, dict):
                continue
            channel_id = channel.get("id")
            name = channel.get("name")
            if isinstance(channel_id, str) and isinstance(name, str):
                display_name = name if name.startswith("#") else f"#{name}"
                result.append({"id": channel_id, "name": display_name})
        if result:
            return result
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    name_pattern = re.compile(r"[Nn]ame:\s*#?([\w-]+)")
    id_pattern = re.compile(r"\\?/archives\\?/([A-Z0-9]+)")

    names = name_pattern.findall(text)
    ids = id_pattern.findall(text)

    return [{"id": cid, "name": f"#{cname}"} for cid, cname in zip(ids, names)]


@authz_namespace("slack", "list_slack_channels", tool_resources={"slack_send_message": "channel_id"}, resource_label="channel")
def register_tools(mcp: FastMCP, client_ref: dict[str, Client]) -> None:
    """Register Slack tools on the FastMCP server.

    Args:
        client_ref: Dict container with key ``"c"`` populated during lifespan.
    """

    @mcp.tool(name="slack_send_message")
    async def slack_send_message(
        ctx: Context,
        channel_id: str,
        message: str,
        thread_ts: str = "",
        reply_broadcast: bool = False,
    ) -> str:
        """Sends a message to a Slack channel or user. To DM a user, use their user_id as channel_id."""
        args: dict[str, Any] = {"channel_id": channel_id, "message": message}
        if thread_ts:
            args["thread_ts"] = thread_ts
        if reply_broadcast:
            args["reply_broadcast"] = reply_broadcast
        return await call_remote(client_ref["c"], "slack_send_message", args)

    @mcp.tool(name="list_slack_channels")
    async def list_slack_channels(
        ctx: Context,
        query: str,
        channel_types: str = "public_channel,private_channel",
        limit: int = 20,
        include_archived: bool = False,
    ) -> str:
        """Search for Slack channels by name or description. Returns standardized [{"id": ..., "name": ...}] JSON."""
        args: dict[str, Any] = {"query": query}
        if channel_types:
            args["channel_types"] = channel_types
        if limit != 20:
            args["limit"] = limit
        if include_archived:
            args["include_archived"] = include_archived
        raw = await call_remote(client_ref["c"], "slack_search_channels", args)
        return json.dumps(parse_slack_channels(raw))
