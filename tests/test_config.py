"""Unit tests for task_authz.config — authz_namespace decorator."""

from __future__ import annotations

from task_authz.config import ResourceType, _AUTHZ_ATTR, authz_namespace


# ---------------------------------------------------------------------------
# authz_namespace decorator
# ---------------------------------------------------------------------------


def test_decorator_attaches_resource_type_metadata() -> None:
    @authz_namespace(
        "slack",
        "list_slack_channels",
        tool_resources={"slack_send_message": "channel_id"},
        resource_label="channel",
    )
    def register_tools() -> None:
        pass

    rt = getattr(register_tools, _AUTHZ_ATTR)
    assert isinstance(rt, ResourceType)
    assert rt.name == "slack"
    assert rt.list_tool == "list_slack_channels"
    assert rt.tool_resources == {"slack_send_message": "channel_id"}
    assert rt.resource_label == "channel"
    assert rt.search_param == "query"  # default


def test_decorator_returns_original_function() -> None:
    def my_func() -> str:
        return "hello"

    decorated = authz_namespace("ns")(my_func)
    assert decorated is my_func
    assert decorated() == "hello"


def test_decorator_defaults() -> None:
    @authz_namespace("email")
    def register_tools() -> None:
        pass

    rt = getattr(register_tools, _AUTHZ_ATTR)
    assert rt.name == "email"
    assert rt.list_tool == ""
    assert rt.search_param == "query"
    assert rt.tool_resources == {}
    assert rt.resource_label == "resource"


def test_decorator_custom_search_param() -> None:
    @authz_namespace("linear", "list_linear_projects", search_param="filter")
    def register_tools() -> None:
        pass

    rt = getattr(register_tools, _AUTHZ_ATTR)
    assert rt.search_param == "filter"


def test_decorator_none_tool_resources_becomes_empty_dict() -> None:
    @authz_namespace("ns", tool_resources=None)
    def register_tools() -> None:
        pass

    rt = getattr(register_tools, _AUTHZ_ATTR)
    assert rt.tool_resources == {}
