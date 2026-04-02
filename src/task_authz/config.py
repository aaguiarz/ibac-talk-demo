"""Configuration dataclasses, constants, and the authz_namespace decorator."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Scope choices for elicitation
SCOPE_CHOICES = [
    "Allow once",
    "Allow for this session",
    "Always allow",
    "Do not allow",
]
SCOPE_MAP = {
    "allow once": "once",
    "allow for this session": "session",
    "always allow": "always",
    "do not allow": "deny",
}

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ResourceType:
    """A type of resource (e.g. Slack channels, Linear projects, email addresses).

    Defines how to discover resources of this type and how tools reference them.
    """

    name: str  # e.g. "slack"
    list_tool: str = ""  # e.g. "list_slack_channels" — always callable; empty for types without discovery
    search_param: str = "query"  # which param on list_tool takes the search term
    tool_resources: dict[str, str] = field(default_factory=dict)  # tool_name → arg_name for resource-level checks
    resource_label: str = "resource"  # human-readable label: "channel", "project", "recipient"


@dataclass
class FGAConfig:
    api_url: str = field(default_factory=lambda: os.environ.get("FGA_API_URL", "http://localhost:8080"))
    store_id: str = field(default_factory=lambda: os.environ.get("FGA_STORE_ID", ""))


_AUTHZ_ATTR = "_authz_namespace"


def authz_namespace(
    name: str,
    list_tool: str = "",
    *,
    search_param: str = "query",
    tool_resources: dict[str, str] | None = None,
    resource_label: str = "resource",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Annotate a ``register_tools`` function with authorization namespace metadata.

    The :class:`OpenFGAPermissionMiddleware` reads this annotation during
    :meth:`setup` to discover resource types automatically.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(
            fn,
            _AUTHZ_ATTR,
            ResourceType(
                name=name,
                list_tool=list_tool,
                search_param=search_param,
                tool_resources=tool_resources or {},
                resource_label=resource_label,
            ),
        )
        return fn

    return decorator
