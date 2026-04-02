#!/usr/bin/env python3
"""Simple MCP server for testing the proxy. No auth, no permissions."""

from __future__ import annotations

from fastmcp import FastMCP

mcp = FastMCP("test_remote")

ITEMS = {
    "item_a": "Content of item A — the first item in the collection.",
    "item_b": "Content of item B — the second item with more details.",
    "item_c": "Content of item C — the third and final item.",
}

CHANNELS = ["#general", "#random", "#alerts"]


@mcp.tool()
async def list_items() -> list[str]:
    """List all available items."""
    return list(ITEMS.keys())


@mcp.tool()
async def read_item(name: str) -> str:
    """Read the content of a specific item."""
    if name not in ITEMS:
        return f"Error: item {name!r} not found. Available: {list(ITEMS.keys())}"
    return ITEMS[name]


@mcp.tool()
async def write_item(name: str, content: str) -> str:
    """Write content to an item."""
    ITEMS[name] = content
    return f"Written to {name}."


@mcp.tool()
async def list_channels() -> list[str]:
    """List available channels."""
    return CHANNELS


@mcp.tool()
async def send_message(channel: str, message: str) -> str:
    """Send a message to a channel."""
    if channel not in CHANNELS:
        return f"Error: channel {channel!r} not found. Available: {CHANNELS}"
    return f"Message sent to {channel}."


if __name__ == "__main__":
    mcp.run()
