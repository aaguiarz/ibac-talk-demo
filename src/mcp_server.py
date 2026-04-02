#!/usr/bin/env python3
"""Multi-MCP Authorization Proxy (OpenFGA-backed).

Connects to Slack and Linear MCP servers and re-exposes selected tools
through a single FastMCP server with OpenFGA-backed permission middleware.

Usage:
    python mcp_server.py
    python mcp_server.py --config my_servers.json

Environment variables:
    FGA_API_URL   — OpenFGA API URL (default: http://localhost:8080)
    FGA_STORE_ID  — OpenFGA store ID
    FGA_USER_ID   — Human user identity (default: "default")
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import Client, FastMCP

from mcp_remote import create_remote_client, get_server
from servers import SERVERS
from servers import email as email_server
from servers import linear as linear_server
from servers import slack as slack_server
from task_authz import OpenFGAPermissionMiddleware
from utils import load_env

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_env(os.path.join(PROJECT_ROOT, ".env"))

# Backward-compat re-export used by tests
from servers.slack import parse_slack_channels as _parse_slack_channels  # noqa: E402, F401


# ---------------------------------------------------------------------------
# Proxy builder
# ---------------------------------------------------------------------------


def _raise_connection_error(server_name: str, url: str, exc: Exception) -> None:
    """Raise a clear error when connecting to a remote MCP server fails."""
    import httpx

    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 401:
        raise RuntimeError(
            f"{server_name}: authentication failed (401 Unauthorized). "
            f"The OAuth token has likely expired.\n"
            f"Run 'make auth-{server_name}' to re-authenticate."
        ) from exc

    raise RuntimeError(
        f"{server_name}: failed to connect to {url} — {exc}\n"
        f"Check that the server URL and token in .mcp_credentials.json are correct."
    ) from exc


def create_multi_proxy(
    config_file: str | None = None,
) -> FastMCP:
    config_file = config_file or os.path.join(PROJECT_ROOT, ".mcp_credentials.json")

    # Verify required servers exist
    slack_cfg = get_server(config_file, "slack")
    linear_cfg = get_server(config_file, "linear")

    missing = []
    if not slack_cfg:
        missing.append("slack")
    if not linear_cfg:
        missing.append("linear")
    if missing:
        print(
            f"Error: Missing server config for: {', '.join(missing)}.\n"
            f"Run 'make auth-{missing[0]}' to authenticate, or add entries to .mcp_credentials.json.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if slack_cfg is None or linear_cfg is None:
        raise RuntimeError("Required MCP server configuration is missing.")

    # Create OpenFGA permission middleware
    perm = OpenFGAPermissionMiddleware()

    # Client containers — populated during lifespan, captured by tool closures
    slack_client: dict[str, Client] = {}
    linear_client: dict[str, Client] = {}

    @asynccontextmanager
    async def lifespan(_app: FastMCP) -> AsyncIterator[None]:
        sc = create_remote_client(slack_cfg["url"], slack_cfg["token"])
        lc = create_remote_client(linear_cfg["url"], linear_cfg["token"])
        slack_client["c"] = sc
        linear_client["c"] = lc

        try:
            await sc.__aenter__()
        except Exception as exc:
            _raise_connection_error("slack", slack_cfg["url"], exc)
        try:
            await lc.__aenter__()
        except Exception as exc:
            await sc.__aexit__(None, None, None)
            _raise_connection_error("linear", linear_cfg["url"], exc)

        await perm.startup()

        yield

        await perm.shutdown()
        await sc.__aexit__(None, None, None)
        await lc.__aexit__(None, None, None)

    mcp = FastMCP("mcp_server", middleware=[perm], lifespan=lifespan)
    perm.setup(mcp, servers=SERVERS)

    # Register server tools (closures capture client containers)
    slack_server.register_tools(mcp, slack_client)
    linear_server.register_tools(mcp, linear_client)
    email_server.register_tools(mcp)

    return mcp


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Project Summarizer MCP Server with Authorization Middleware"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to .mcp_credentials.json (default: ./.mcp_credentials.json)",
    )
    cli_args = parser.parse_args()

    mcp = create_multi_proxy(config_file=cli_args.config)
    mcp.run()
