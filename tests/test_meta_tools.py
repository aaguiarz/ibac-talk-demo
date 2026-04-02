"""Unit tests for task_authz.meta_tools — FGA object parsing."""

from __future__ import annotations

from task_authz.meta_tools import _parse_fga_object


# ---------------------------------------------------------------------------
# _parse_fga_object
# ---------------------------------------------------------------------------


def _tool_resource_map() -> dict[str, tuple[str, str]]:
    return {"slack_send_message": ("slack", "channel_id")}


def _registry() -> dict[str, dict[str, str]]:
    return {"slack": {"C123": "#general", "C456": "#random"}}


def test_parse_tool_resource_with_namespace_and_registry_display_name() -> None:
    tool, resource, display = _parse_fga_object(
        "tool_resource:slack_send_message/slack_C123",
        _tool_resource_map(),
        _registry(),
    )
    assert tool == "slack_send_message"
    assert resource == "slack_C123"
    assert display == "#general"


def test_parse_tool_resource_unknown_id_falls_back_to_resource_part() -> None:
    tool, resource, display = _parse_fga_object(
        "tool_resource:slack_send_message/slack_C999",
        _tool_resource_map(),
        _registry(),
    )
    assert tool == "slack_send_message"
    assert resource == "slack_C999"
    # C999 not in registry, _find_display_name returns the raw ID
    assert display == "C999"


def test_parse_tool_resource_no_namespace_prefix() -> None:
    """Resource part doesn't start with namespace_ prefix."""
    tool, resource, display = _parse_fga_object(
        "tool_resource:send_email/alice_example.com",
        {"send_email": ("email", "to")},
        {},
    )
    assert tool == "send_email"
    assert resource == "alice_example.com"
    # Starts with "email_"? No — starts with "alice_", so no stripping
    assert display == "alice_example.com"


def test_parse_tool_resource_with_email_namespace() -> None:
    tool, resource, display = _parse_fga_object(
        "tool_resource:send_email/email_alice_example.com",
        {"send_email": ("email", "to")},
        {},
    )
    assert tool == "send_email"
    assert resource == "email_alice_example.com"
    # Stripped namespace prefix → raw_id = "alice_example.com", not in registry
    assert display == "alice_example.com"


def test_parse_tool_resource_without_slash() -> None:
    tool, resource, display = _parse_fga_object(
        "tool_resource:slack_send_message",
        _tool_resource_map(),
        _registry(),
    )
    assert tool == "slack_send_message"
    assert resource == "*"
    assert display == "*"


def test_parse_tool_resource_tool_not_in_map() -> None:
    """Tool not in tool_resource_map — no namespace stripping."""
    tool, resource, display = _parse_fga_object(
        "tool_resource:unknown_tool/some_resource",
        _tool_resource_map(),
        _registry(),
    )
    assert tool == "unknown_tool"
    assert resource == "some_resource"
    assert display == "some_resource"


def test_parse_tool_level_object() -> None:
    tool, resource, display = _parse_fga_object(
        "tool:slack_send_message",
        _tool_resource_map(),
        _registry(),
    )
    assert tool == "slack_send_message"
    assert resource == "*"
    assert display == "*"


def test_parse_unknown_object_format() -> None:
    tool, resource, display = _parse_fga_object(
        "something_else",
        _tool_resource_map(),
        _registry(),
    )
    assert tool == "something_else"
    assert resource == ""
    assert display == ""
