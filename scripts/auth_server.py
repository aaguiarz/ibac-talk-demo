#!/usr/bin/env python3
"""Authenticate with a remote MCP server via OAuth and save the token.

Opens a browser for the OAuth flow, captures the access token, and writes
it to .mcp_credentials.json. Supports Linear, Slack, and Notion.

Usage:
    python scripts/auth_server.py linear
    python scripts/auth_server.py slack
    python scripts/auth_server.py notion
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Server presets: URL and any OAuth overrides needed
PRESETS: dict[str, dict[str, str | list[str] | dict[str, str]]] = {
    "linear": {
        "url": "https://mcp.linear.app/sse",
    },
    "slack": {
        "url": "https://mcp.slack.com/mcp",
    },
    "notion": {
        "url": "https://mcp.notion.com/mcp",
    },
}

CREDENTIALS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".mcp_credentials.json",
)


def _extract_token(client) -> str | None:  # noqa: ANN001
    """Extract the bearer token from a connected client."""
    transport = getattr(client, "transport", None)
    if transport is None:
        return None
    auth = getattr(transport, "auth", None)
    if auth is None:
        return None

    # OAuth: token is in auth.context.current_tokens.access_token
    ctx = getattr(auth, "context", None)
    if ctx is not None:
        tokens = getattr(ctx, "current_tokens", None)
        if tokens is not None:
            access_token = getattr(tokens, "access_token", None)
            if access_token:
                return access_token

    return None


async def authenticate(server_name: str) -> None:
    """Run the OAuth flow for a server and save the token."""
    from fastmcp import Client

    preset = PRESETS.get(server_name)
    if not preset:
        print(f"Error: Unknown server '{server_name}'. Available: {', '.join(PRESETS)}")
        sys.exit(1)

    url = str(preset["url"])
    print(f"Authenticating with {server_name} ({url})...")
    print("A browser window will open for authorization.\n")

    async with Client(url, auth="oauth") as client:
        # The connection triggers the OAuth flow — list_tools verifies it worked
        tools = await client.list_tools()
        token = _extract_token(client)

    if not token:
        print("Error: OAuth flow completed but no token was captured.")
        sys.exit(1)

    print(f"Authenticated successfully ({len(tools)} tools available).")

    # Read existing credentials
    config: dict = {}
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE) as f:
                config = json.load(f)
        except (json.JSONDecodeError, TypeError):
            config = {}

    # Update the server entry
    servers = config.setdefault("servers", {})
    servers[server_name] = {
        "url": url,
        "auth": "oauth",
        "token": token,
    }

    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(config, f, indent=2)

    print(f"Token saved to {os.path.relpath(CREDENTIALS_FILE)}")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(f"Usage: {sys.argv[0]} <server>")
        print(f"Available servers: {', '.join(PRESETS)}")
        sys.exit(0 if "--help" in sys.argv else 1)

    asyncio.run(authenticate(sys.argv[1]))


if __name__ == "__main__":
    main()
