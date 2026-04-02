"""Shared boilerplate for connecting to remote MCP servers.

Provides config loading, HTTP client creation, and remote tool invocation.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.client.transports.sse import SSETransport

from utils import extract_text

REMOTE_TOOL_TIMEOUT_SECONDS = float(
    os.environ.get("MCP_REMOTE_TOOL_TIMEOUT_SECONDS", "90")
)


def load_config(config_file: str) -> dict[str, Any]:
    """Load server configuration from a JSON file."""
    if os.path.exists(config_file):
        try:
            with open(config_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def get_server(config_file: str, name: str) -> dict[str, str] | None:
    """Get a single server's config (url + token) from the config file."""
    config = load_config(config_file)
    servers = config.get("servers", {})
    entry = servers.get(name)
    if not entry:
        return None
    url = entry.get("url")
    token = entry.get("token")
    if not token:
        token = os.environ.get(f"{name.upper()}_MCP_API_KEY")
    if not url or not token:
        return None
    return {"url": url, "token": token}



def _make_httpx_factory() -> Any | None:
    """Avoid having issues with the corporate VPN by 
    using an httpx client factory that respects MCP_SSL_VERIFY."""
    import httpx

    verify_env = os.environ.get("MCP_SSL_VERIFY", "").strip().lower()
    ca_bundle = os.environ.get("MCP_SSL_CA_BUNDLE", "").strip()

    if ca_bundle:
        ssl_verify: bool | str = ca_bundle
    elif verify_env in {"0", "false", "no", "off"}:
        ssl_verify = False
    else:
        return None  # use default

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["verify"] = ssl_verify
        return httpx.AsyncClient(**kwargs)

    return factory


def create_remote_client(url: str, token: str) -> Client:
    """Create a remote MCP client with SSE-friendly idle timeouts."""
    httpx_factory = _make_httpx_factory()
    extra: dict[str, Any] = {}
    if httpx_factory:
        extra["httpx_client_factory"] = httpx_factory

    transport: SSETransport | StreamableHttpTransport
    if url.rstrip("/").endswith("/sse"):
        transport = SSETransport(
            url,
            auth=token,
            sse_read_timeout=24 * 60 * 60,
            **extra,
        )
    else:
        transport = StreamableHttpTransport(url, auth=token, **extra)
    return Client(transport)


async def call_remote(client: Client, tool_name: str, args: dict[str, Any]) -> str:
    """Call a tool on a remote MCP server and return the text result."""
    result = await client.call_tool(
        tool_name,
        args,
        timeout=REMOTE_TOOL_TIMEOUT_SECONDS,
    )
    return extract_text(result)
