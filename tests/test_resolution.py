"""Unit tests for task_authz.resolution — resource parsing and resolution."""

from __future__ import annotations

from task_authz.resolution import (
    _find_display_name,
    _get_task_id,
    _parse_standard_resources,
    _resolve_resource,
    _suggest_resources,
    _unresolved_resource_message,
)


# ---------------------------------------------------------------------------
# _parse_standard_resources
# ---------------------------------------------------------------------------


def test_parse_standard_resources_valid_json_array() -> None:
    text = '[{"id": "C123", "name": "#general"}, {"id": "C456", "name": "#random"}]'
    result = _parse_standard_resources(text)
    assert result == {"C123": "#general", "C456": "#random"}


def test_parse_standard_resources_skips_items_missing_id() -> None:
    text = '[{"name": "no-id"}, {"id": "C1", "name": "ok"}]'
    result = _parse_standard_resources(text)
    assert result == {"C1": "ok"}


def test_parse_standard_resources_skips_non_dict_items() -> None:
    text = '["string-item", {"id": "C1", "name": "ok"}]'
    result = _parse_standard_resources(text)
    assert result == {"C1": "ok"}


def test_parse_standard_resources_returns_empty_on_invalid_json() -> None:
    result = _parse_standard_resources("not valid json {{{")
    assert result == {}


def test_parse_standard_resources_returns_empty_on_non_list_json() -> None:
    result = _parse_standard_resources('{"channels": []}')
    assert result == {}


def test_parse_standard_resources_returns_empty_on_empty_string() -> None:
    result = _parse_standard_resources("")
    assert result == {}


def test_parse_standard_resources_returns_empty_on_null_json() -> None:
    result = _parse_standard_resources("null")
    assert result == {}


# ---------------------------------------------------------------------------
# _get_task_id
# ---------------------------------------------------------------------------


def test_get_task_id_from_meta_task_id() -> None:
    class Meta:
        task_id = "task-123"

    class RC:
        meta = Meta()

    class Ctx:
        request_context = RC()

    assert _get_task_id(Ctx()) == "task-123"


def test_get_task_id_from_model_extra() -> None:
    class Meta:
        model_extra = {"task_id": "task-456"}

    class RC:
        meta = Meta()

    class Ctx:
        request_context = RC()

    assert _get_task_id(Ctx()) == "task-456"


def test_get_task_id_returns_empty_when_no_context() -> None:
    class Ctx:
        request_context = None

    assert _get_task_id(Ctx()) == ""


def test_get_task_id_returns_empty_when_no_meta() -> None:
    class RC:
        meta = None

    class Ctx:
        request_context = RC()

    assert _get_task_id(Ctx()) == ""


# ---------------------------------------------------------------------------
# _find_display_name
# ---------------------------------------------------------------------------


def test_find_display_name_found() -> None:
    registry = {"slack": {"C123": "#general"}}
    assert _find_display_name("slack", "C123", registry) == "#general"


def test_find_display_name_missing_namespace() -> None:
    registry = {"slack": {"C123": "#general"}}
    assert _find_display_name("linear", "C123", registry) == "C123"


def test_find_display_name_missing_id() -> None:
    registry = {"slack": {"C123": "#general"}}
    assert _find_display_name("slack", "C999", registry) == "C999"


# ---------------------------------------------------------------------------
# _suggest_resources
# ---------------------------------------------------------------------------


def test_suggest_resources_finds_substring_match() -> None:
    registry = {"slack": {"C1": "#general", "C2": "#random", "C3": "#general-dev"}}
    suggestions = _suggest_resources("slack", "general", registry)
    assert "#general" in suggestions
    assert "#general-dev" in suggestions


def test_suggest_resources_returns_empty_for_empty_registry() -> None:
    assert _suggest_resources("slack", "general", {}) == []


def test_suggest_resources_returns_empty_for_empty_resource() -> None:
    registry = {"slack": {"C1": "#general"}}
    assert _suggest_resources("slack", "", registry) == []


def test_suggest_resources_respects_limit() -> None:
    registry = {"ns": {f"id{i}": f"match-{i}" for i in range(20)}}
    suggestions = _suggest_resources("ns", "match", registry, limit=3)
    assert len(suggestions) <= 3


# ---------------------------------------------------------------------------
# _unresolved_resource_message
# ---------------------------------------------------------------------------


def test_unresolved_message_with_suggestions() -> None:
    registry = {"slack": {"C1": "#general"}}
    msg = _unresolved_resource_message("slack", "slack_send_message", "generl", registry)
    assert "Could not safely resolve" in msg
    assert "#general" in msg
    assert "rewrite your prompt" in msg


def test_unresolved_message_without_suggestions() -> None:
    msg = _unresolved_resource_message("slack", "slack_send_message", "xyz", {})
    assert "Could not safely resolve" in msg
    assert "rewrite your prompt" in msg


# ---------------------------------------------------------------------------
# _resolve_resource
# ---------------------------------------------------------------------------


def _make_tool_resource_map() -> dict[str, tuple[str, str]]:
    return {"slack_send_message": ("slack", "channel_id")}


def _make_registry() -> dict[str, dict[str, str]]:
    return {"slack": {"C123": "#general", "C456": "#random"}}


def test_resolve_exact_canonical_id() -> None:
    rid, display, err = _resolve_resource(
        "slack_send_message", "C123", _make_tool_resource_map(), _make_registry()
    )
    assert rid == "C123"
    assert display == "#general"
    assert err is None


def test_resolve_exact_display_name() -> None:
    rid, display, err = _resolve_resource(
        "slack_send_message", "#general", _make_tool_resource_map(), _make_registry()
    )
    assert rid == "C123"
    assert display == "#general"
    assert err is None


def test_resolve_case_insensitive_display_name() -> None:
    rid, display, err = _resolve_resource(
        "slack_send_message", "#GENERAL", _make_tool_resource_map(), _make_registry()
    )
    assert rid == "C123"
    assert display == "#general"
    assert err is None


def test_resolve_normalized_prefix_strip() -> None:
    rid, display, err = _resolve_resource(
        "slack_send_message", "general", _make_tool_resource_map(), _make_registry()
    )
    assert rid == "C123"
    assert display == "#general"
    assert err is None


def test_resolve_fails_closed_with_suggestions() -> None:
    rid, display, err = _resolve_resource(
        "slack_send_message", "genral", _make_tool_resource_map(), _make_registry()
    )
    assert rid is None
    assert display is None
    assert err is not None
    assert "Could not safely resolve" in err


def test_resolve_unknown_tool_passes_through() -> None:
    rid, display, err = _resolve_resource(
        "unknown_tool", "anything", _make_tool_resource_map(), _make_registry()
    )
    assert rid == "anything"
    assert display == "anything"
    assert err is None


def test_resolve_empty_resource_passes_through() -> None:
    rid, display, err = _resolve_resource(
        "slack_send_message", "", _make_tool_resource_map(), _make_registry()
    )
    assert rid == ""
    assert display == ""
    assert err is None


def test_resolve_empty_registry_passes_through() -> None:
    rid, display, err = _resolve_resource(
        "slack_send_message", "#general", _make_tool_resource_map(), {}
    )
    assert rid == "#general"
    assert display == "#general"
    assert err is None
