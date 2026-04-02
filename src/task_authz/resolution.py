"""Resource resolution: name→ID matching and discovery result parsing."""

from __future__ import annotations

import json
from difflib import get_close_matches
from typing import Any


def _get_task_id(ctx: Any) -> str:
    """Extract task_id from the FastMCP Context's request metadata."""
    rc = getattr(ctx, "request_context", None)
    if rc and hasattr(rc, "meta") and rc.meta:
        meta = rc.meta
        if hasattr(meta, "task_id"):
            return meta.task_id or ""
        if hasattr(meta, "model_extra") and meta.model_extra:
            return meta.model_extra.get("task_id", "")
    return ""


def _parse_standard_resources(text: str) -> dict[str, str]:
    """Parse standardized ``[{"id": "...", "name": "..."}]`` discovery output.

    Returns an empty dict if *text* is not valid JSON or not the expected
    structure, so callers never see an unhandled parse error.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, list):
        return {}
    return {
        item["id"]: item["name"]
        for item in data
        if isinstance(item, dict) and "id" in item and "name" in item
    }


def _find_display_name(
    namespace: str,
    resource_id: str,
    resource_registry: dict[str, dict[str, str]],
) -> str:
    """Return a human-readable display name for a canonical resource ID."""
    return resource_registry.get(namespace, {}).get(resource_id, resource_id)


def _suggest_resources(
    namespace: str,
    resource: str,
    resource_registry: dict[str, dict[str, str]],
    limit: int = 5,
) -> list[str]:
    """Suggest nearby display names for an unresolved resource."""
    registry = resource_registry.get(namespace, {})
    displays = [
        display for display in registry.values() if isinstance(display, str)
    ]
    if not resource or not displays:
        return []

    suggestions: list[str] = []
    lowered = resource.casefold()

    for display in displays:
        display_lower = display.casefold()
        if lowered in display_lower or display_lower in lowered:
            suggestions.append(display)
    for display in get_close_matches(resource, displays, n=limit, cutoff=0.4):
        if display not in suggestions:
            suggestions.append(display)
    return suggestions[:limit]


def _unresolved_resource_message(
    namespace: str,
    tool_name: str,
    resource: str,
    resource_registry: dict[str, dict[str, str]],
) -> str:
    """Build a user-facing message for unresolved resources."""
    suggestions = _suggest_resources(namespace, resource, resource_registry)
    if suggestions:
        return (
            f'Could not safely resolve "{resource}" for {tool_name}. '
            f"Similar {namespace} resources: {', '.join(suggestions)}. "
            "Please rewrite your prompt using the exact resource name."
        )
    return (
        f'Could not safely resolve "{resource}" for {tool_name}. '
        "Please rewrite your prompt using the exact resource name."
    )


def _resolve_resource(
    tool_name: str,
    resource: str,
    tool_resource_map: dict[str, tuple[str, str]],
    resource_registry: dict[str, dict[str, str]],
) -> tuple[str | None, str | None, str | None]:
    """Resolve a raw resource reference to a canonical resource ID.

    Resolution order:
    1. Exact canonical ID match
    2. Exact display-name match
    3. Case-insensitive display-name match
    4. Otherwise fail closed with suggestions
    """
    if tool_name not in tool_resource_map or not resource:
        return resource, resource, None

    namespace, _arg_name = tool_resource_map[tool_name]
    registry = resource_registry.get(namespace, {})
    if not registry:
        return resource, resource, None

    if resource in registry:
        return resource, registry[resource], None

    display_to_id = {
        display: resource_id for resource_id, display in registry.items()
    }
    if resource in display_to_id:
        resource_id = display_to_id[resource]
        return resource_id, registry[resource_id], None

    lowered = {
        display.casefold(): rid
        for rid, display in registry.items()
        if isinstance(display, str)
    }
    lowered_match = lowered.get(resource.casefold())
    if lowered_match:
        return lowered_match, registry[lowered_match], None

    # 4. Normalized match — strip common prefixes (#, @) from both sides
    def _normalize(s: str) -> str:
        return s.casefold().lstrip("#@")

    normalized = {
        _normalize(display): rid
        for rid, display in registry.items()
        if isinstance(display, str)
    }
    normalized_match = normalized.get(_normalize(resource))
    if normalized_match:
        return normalized_match, registry[normalized_match], None

    return (
        None,
        None,
        _unresolved_resource_message(namespace, tool_name, resource, resource_registry),
    )
