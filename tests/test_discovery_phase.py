"""Unit tests for authz_flow.run_discovery_phase — discovery orchestration."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from authz_flow import (
    NamespaceInfo,
    PermissionPlan,
    run_discovery_phase,
)


def _make_call_tool_mock(results: dict[str, str]) -> AsyncMock:
    """Build a mock call_tool that returns text results keyed by tool name."""

    async def fake_call_tool(
        _client: Any, name: str, _args: dict[str, Any], _task_id: str = ""
    ) -> SimpleNamespace:
        text = results.get(name, "[]")
        return SimpleNamespace(content=[SimpleNamespace(text=text)])

    return AsyncMock(side_effect=fake_call_tool)


# ---------------------------------------------------------------------------
# Basic discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_populates_name_to_id() -> None:
    channels = json.dumps([
        {"id": "C123", "name": "#general"},
        {"id": "C456", "name": "#random"},
    ])
    mock_call = _make_call_tool_mock({"list_slack_channels": channels})

    plan = PermissionPlan(
        discovery=["list_slack_channels:*"],
        actions=["slack_send_message:#general"],
        discovery_map={"list_slack_channels": ["slack_send_message:#general"]},
    )
    namespaces = [
        NamespaceInfo(
            name="slack",
            list_tool="list_slack_channels",
            search_param="query",
            tool_resources={"slack_send_message": "channel_id"},
        ),
    ]

    with patch("authz_flow.call_tool", mock_call):
        name_to_id, normalized = await run_discovery_phase(
            AsyncMock(), plan, namespaces, "task-1"
        )

    assert name_to_id == {"#general": "C123", "#random": "C456"}
    assert normalized == {"#general": "C123", "#random": "C456"}


@pytest.mark.asyncio
async def test_discovery_case_normalizes_names() -> None:
    channels = json.dumps([{"id": "C1", "name": "MyChannel"}])
    mock_call = _make_call_tool_mock({"list_slack_channels": channels})

    plan = PermissionPlan(
        discovery=["list_slack_channels:*"],
        actions=["slack_send_message:MyChannel"],
        discovery_map={"list_slack_channels": ["slack_send_message:MyChannel"]},
    )
    namespaces = [
        NamespaceInfo(name="slack", list_tool="list_slack_channels"),
    ]

    with patch("authz_flow.call_tool", mock_call):
        name_to_id, normalized = await run_discovery_phase(
            AsyncMock(), plan, namespaces, "task-1"
        )

    assert "MyChannel" in name_to_id
    assert "mychannel" in normalized
    assert normalized["mychannel"] == "C1"


# ---------------------------------------------------------------------------
# Empty / no-op cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_discovery_map_returns_empty() -> None:
    plan = PermissionPlan(discovery=[], actions=[], discovery_map={})
    name_to_id, normalized = await run_discovery_phase(
        AsyncMock(), plan, [], "task-1"
    )
    assert name_to_id == {}
    assert normalized == {}


@pytest.mark.asyncio
async def test_discovery_tool_returns_empty_array() -> None:
    mock_call = _make_call_tool_mock({"list_slack_channels": "[]"})

    plan = PermissionPlan(
        discovery=["list_slack_channels:*"],
        actions=["slack_send_message:#general"],
        discovery_map={"list_slack_channels": ["slack_send_message:#general"]},
    )
    namespaces = [
        NamespaceInfo(name="slack", list_tool="list_slack_channels"),
    ]

    with patch("authz_flow.call_tool", mock_call):
        name_to_id, normalized = await run_discovery_phase(
            AsyncMock(), plan, namespaces, "task-1"
        )

    assert name_to_id == {}
    assert normalized == {}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_tool_returns_invalid_json() -> None:
    mock_call = _make_call_tool_mock({"list_slack_channels": "not json"})

    plan = PermissionPlan(
        discovery=["list_slack_channels:*"],
        actions=["slack_send_message:#general"],
        discovery_map={"list_slack_channels": ["slack_send_message:#general"]},
    )
    namespaces = [
        NamespaceInfo(name="slack", list_tool="list_slack_channels"),
    ]

    with patch("authz_flow.call_tool", mock_call):
        name_to_id, normalized = await run_discovery_phase(
            AsyncMock(), plan, namespaces, "task-1"
        )

    # Invalid JSON → no resources parsed, but no crash
    assert name_to_id == {}
    assert normalized == {}


@pytest.mark.asyncio
async def test_discovery_tool_raises_error_continues() -> None:
    """A failing discovery tool doesn't crash the whole phase."""
    from fastmcp.exceptions import ToolError

    call_count = 0

    async def failing_then_ok(
        _client: Any, name: str, _args: dict[str, Any], _task_id: str = ""
    ) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        if name == "list_slack_channels":
            raise ToolError("Connection refused")
        return SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps([{"id": "P1", "name": "Website"}]))]
        )

    plan = PermissionPlan(
        discovery=["list_slack_channels:*", "list_linear_projects:*"],
        actions=["slack_send_message:#general", "linear_get_project:Website"],
        discovery_map={
            "list_slack_channels": ["slack_send_message:#general"],
            "list_linear_projects": ["linear_get_project:Website"],
        },
    )
    namespaces = [
        NamespaceInfo(name="slack", list_tool="list_slack_channels"),
        NamespaceInfo(name="linear", list_tool="list_linear_projects"),
    ]

    with patch("authz_flow.call_tool", AsyncMock(side_effect=failing_then_ok)):
        name_to_id, normalized = await run_discovery_phase(
            AsyncMock(), plan, namespaces, "task-1"
        )

    # Slack failed, but Linear succeeded
    assert "Website" in name_to_id
    assert "#general" not in name_to_id
    assert call_count == 2


# ---------------------------------------------------------------------------
# Observer integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_emits_observer_events() -> None:
    channels = json.dumps([{"id": "C1", "name": "#general"}])
    mock_call = _make_call_tool_mock({"list_slack_channels": channels})

    events: list[tuple[str, dict[str, Any]]] = []

    class TrackingObserver:
        async def on_event(self, event_type: str, data: dict[str, Any]) -> None:
            events.append((event_type, data))

    plan = PermissionPlan(
        discovery=["list_slack_channels:*"],
        actions=["slack_send_message:#general"],
        discovery_map={"list_slack_channels": ["slack_send_message:#general"]},
    )
    namespaces = [
        NamespaceInfo(name="slack", list_tool="list_slack_channels"),
    ]

    with patch("authz_flow.call_tool", mock_call):
        await run_discovery_phase(
            AsyncMock(), plan, namespaces, "task-1", observer=TrackingObserver()
        )

    event_types = [e[0] for e in events]
    assert "tool_call_start" in event_types
    assert "tool_call_end" in event_types
    assert "discovery_result" in event_types


# ---------------------------------------------------------------------------
# Multiple discovery tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_discovery_tools_merge_results() -> None:
    results = {
        "list_slack_channels": json.dumps([{"id": "C1", "name": "#general"}]),
        "list_linear_projects": json.dumps([{"id": "P1", "name": "Website"}]),
    }
    mock_call = _make_call_tool_mock(results)

    plan = PermissionPlan(
        discovery=["list_slack_channels:*", "list_linear_projects:*"],
        actions=["slack_send_message:#general", "linear_get_project:Website"],
        discovery_map={
            "list_slack_channels": ["slack_send_message:#general"],
            "list_linear_projects": ["linear_get_project:Website"],
        },
    )
    namespaces = [
        NamespaceInfo(name="slack", list_tool="list_slack_channels"),
        NamespaceInfo(name="linear", list_tool="list_linear_projects"),
    ]

    with patch("authz_flow.call_tool", mock_call):
        name_to_id, normalized = await run_discovery_phase(
            AsyncMock(), plan, namespaces, "task-1"
        )

    assert name_to_id == {"#general": "C1", "Website": "P1"}
    assert "website" in normalized


# ---------------------------------------------------------------------------
# Search param extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_uses_custom_search_param() -> None:
    """The discovery call uses the namespace's search_param, not hardcoded 'query'."""
    captured_args: list[dict[str, Any]] = []

    async def capture_call(
        _client: Any, name: str, args: dict[str, Any], _task_id: str = ""
    ) -> SimpleNamespace:
        captured_args.append(args)
        return SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps([{"id": "P1", "name": "Web"}]))]
        )

    plan = PermissionPlan(
        discovery=["list_linear_projects:*"],
        actions=["linear_get_project:Web"],
        discovery_map={"list_linear_projects": ["linear_get_project:Web"]},
    )
    namespaces = [
        NamespaceInfo(
            name="linear",
            list_tool="list_linear_projects",
            search_param="filter",
        ),
    ]

    with patch("authz_flow.call_tool", AsyncMock(side_effect=capture_call)):
        await run_discovery_phase(AsyncMock(), plan, namespaces, "task-1")

    assert "filter" in captured_args[0]
    assert captured_args[0]["filter"] == "Web"
