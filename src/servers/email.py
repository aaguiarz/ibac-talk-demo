"""Email stub tool."""

from __future__ import annotations

import json

from fastmcp import Context, FastMCP

from task_authz import authz_namespace


@authz_namespace("email", tool_resources={"send_email": "to"}, resource_label="recipient")
def register_tools(mcp: FastMCP) -> None:
    """Register email tools on the FastMCP server."""

    @mcp.tool(name="send_email")
    async def send_email(
        ctx: Context,
        to: str,
        subject: str,
        text: str,
    ) -> str:
        """Send an email message to a recipient."""
        return json.dumps(
            {
                "status": "sent",
                "to": to,
                "subject": subject,
                "text": text,
            }
        )
