"""Unit tests for authz_flow functions that previously lacked coverage."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from authz_flow import (
    build_tool_to_namespace,
    compute_fga_tuples,
    delete_fga_grants,
    get_agent_user_id,
    NamespaceInfo,
    parse_permission_plan,
    permission_has_concrete_resource,
    cleanup_task_grants,
    PermissionPlan,
    get_model,
    get_server_script,
    get_tool_timeout_seconds,
    remap_action_permissions,
    requires_prompt_rewrite,
    suggest_resource_names,
    validate_permission_plan,
    write_fga_grants,
)


# ---------------------------------------------------------------------------
# get_agent_user_id
# ---------------------------------------------------------------------------


def test_get_agent_user_id_default() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("FGA_USER_ID", None)
        os.environ.pop("FGA_AGENT_ID", None)
        result = get_agent_user_id()
    assert result == "default__mcp_agent"


def test_get_agent_user_id_custom_values() -> None:
    with patch.dict(
        os.environ,
        {"FGA_USER_ID": "alice", "FGA_AGENT_ID": "my_agent"},
        clear=False,
    ):
        result = get_agent_user_id()
    assert result == "alice__my_agent"


def test_get_model_reads_environment_at_call_time() -> None:
    with patch.dict(os.environ, {"ANTHROPIC_MODEL": "claude-sonnet-late"}, clear=False):
        assert get_model() == "claude-sonnet-late"


def test_get_server_script_reads_environment_at_call_time() -> None:
    with patch.dict(os.environ, {"MCP_SERVER": "/tmp/custom_server.py"}, clear=False):
        assert get_server_script() == "/tmp/custom_server.py"


def test_get_tool_timeout_seconds_reads_environment_at_call_time() -> None:
    with patch.dict(os.environ, {"MCP_TOOL_TIMEOUT_SECONDS": "12.5"}, clear=False):
        assert get_tool_timeout_seconds() == 12.5


def test_get_tool_timeout_seconds_falls_back_for_invalid_value() -> None:
    with patch.dict(os.environ, {"MCP_TOOL_TIMEOUT_SECONDS": "not-a-float"}, clear=False):
        assert get_tool_timeout_seconds() == 90.0


def test_remap_action_permissions_maps_case_insensitive_display_name() -> None:
    mapped, unresolved = remap_action_permissions(
        ["linear_get_project:mcp dev talk"],
        {"MCP Dev Talk": "b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb"},
        {"mcp dev talk": "b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb"},
    )

    assert mapped == ["linear_get_project:b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb"]
    assert unresolved == []


def test_remap_action_permissions_preserves_known_canonical_id() -> None:
    mapped, unresolved = remap_action_permissions(
        ["linear_get_project:b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb"],
        {"MCP Dev Talk": "b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb"},
        {"mcp dev talk": "b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb"},
    )

    assert mapped == ["linear_get_project:b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb"]
    assert unresolved == []


def test_remap_action_permissions_rejects_unresolved_raw_text() -> None:
    mapped, unresolved = remap_action_permissions(
        ["linear_get_project:totally unknown project"],
        {"MCP Dev Talk": "b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb"},
        {"mcp dev talk": "b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb"},
    )

    assert mapped == []
    assert unresolved == ["linear_get_project:totally unknown project"]


def test_remap_action_permissions_mixed_results_exposes_unresolved_action() -> None:
    mapped, unresolved = remap_action_permissions(
        ["linear_get_project:Dev MCP Talk", "slack_send_message:#general"],
        {
            "MCP Dev Talk": "b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb",
            "#general": "C5XMACTML",
        },
        {
            "mcp dev talk": "b7dc1280-ab70-4c70-a4c1-8ddbf0527ffb",
            "#general": "C5XMACTML",
        },
    )

    assert mapped == ["slack_send_message:C5XMACTML"]
    assert unresolved == ["linear_get_project:Dev MCP Talk"]


def test_requires_prompt_rewrite_detects_resolution_failure_message() -> None:
    assert requires_prompt_rewrite(
        'Could not safely resolve "Dev MCP Talk" for linear_get_project. '
        "Similar linear resources: MCP Dev Talk. "
        "Please rewrite your prompt using the exact resource name."
    )


def test_suggest_resource_names_finds_close_match() -> None:
    suggestions = suggest_resource_names(
        "Dev MCP Talk",
        ["MCP Dev Talk", "#general", "#random"],
    )

    assert "MCP Dev Talk" in suggestions


def test_parse_permission_plan_valid_input() -> None:
    plan = parse_permission_plan(
        {
            "discovery": ["list_slack_channels:*"],
            "actions": ["slack_send_message:#general"],
            "discovery_map": {"list_slack_channels": ["slack_send_message:#general"]},
        }
    )
    assert plan.discovery == ["list_slack_channels:*"]
    assert plan.actions == ["slack_send_message:#general"]
    assert plan.discovery_map == {
        "list_slack_channels": ["slack_send_message:#general"]
    }


def test_parse_permission_plan_empty_input() -> None:
    plan = parse_permission_plan({})
    assert plan.discovery == []
    assert plan.actions == []
    assert plan.discovery_map == {}


def test_parse_permission_plan_coerces_bad_types() -> None:
    plan = parse_permission_plan(
        {
            "discovery": "not a list",
            "actions": 42,
            "discovery_map": "bad",
        }
    )
    assert plan.discovery == []
    assert plan.actions == []
    assert plan.discovery_map == {}


def test_parse_permission_plan_coerces_inner_values_to_strings() -> None:
    plan = parse_permission_plan(
        {
            "discovery": [123, True],
            "actions": [None],
            "discovery_map": {"tool": [456]},
        }
    )
    assert plan.discovery == ["123", "True"]
    assert plan.actions == ["None"]
    assert plan.discovery_map == {"tool": ["456"]}


def test_parse_permission_plan_with_denied_implicit() -> None:
    plan = parse_permission_plan(
        {
            "actions": ["slack_send_message:#general"],
            "denied_implicit": [
                {"tool": "send_email", "reason": "User asked to post to Slack, not send email"},
                {"tool": "linear_get_project", "reason": "No Linear data requested"},
            ],
        }
    )
    assert plan.actions == ["slack_send_message:#general"]
    assert len(plan.denied_implicit) == 2
    assert plan.denied_implicit[0] == {
        "tool": "send_email",
        "reason": "User asked to post to Slack, not send email",
    }
    assert plan.denied_implicit[1]["tool"] == "linear_get_project"


def test_parse_permission_plan_denied_implicit_coerces_bad_types() -> None:
    plan = parse_permission_plan(
        {
            "actions": [],
            "denied_implicit": "not a list",
        }
    )
    assert plan.denied_implicit == []


def test_parse_permission_plan_denied_implicit_skips_non_dict_items() -> None:
    plan = parse_permission_plan(
        {
            "actions": [],
            "denied_implicit": [
                {"tool": "send_email", "reason": "not needed"},
                "bad item",
                42,
            ],
        }
    )
    assert len(plan.denied_implicit) == 1
    assert plan.denied_implicit[0]["tool"] == "send_email"


def test_validate_drops_unknown_tools() -> None:
    plan = PermissionPlan(
        discovery=["list_slack_channels:*", "fake_tool:*"],
        actions=["slack_send_message:#general", "evil_tool:secret"],
        discovery_map={
            "list_slack_channels": [
                "slack_send_message:#general",
                "evil_tool:secret",
            ],
            "fake_tool": ["evil_tool:secret"],
        },
    )
    valid_tools = {"list_slack_channels", "slack_send_message"}
    result = validate_permission_plan(plan, valid_tools)

    assert result.discovery == ["list_slack_channels:*"]
    assert result.actions == ["slack_send_message:#general"]
    assert result.discovery_map == {
        "list_slack_channels": ["slack_send_message:#general"]
    }
    assert "fake_tool" not in result.discovery_map


def test_validate_keeps_all_valid_tools() -> None:
    plan = PermissionPlan(
        discovery=["list_linear_projects:*", "list_slack_channels:*"],
        actions=["linear_get_project:Dev Talk", "slack_send_message:#general"],
        discovery_map={
            "list_linear_projects": ["linear_get_project:Dev Talk"],
            "list_slack_channels": ["slack_send_message:#general"],
        },
    )
    valid_tools = {
        "list_linear_projects",
        "linear_get_project",
        "list_slack_channels",
        "slack_send_message",
    }
    result = validate_permission_plan(plan, valid_tools)

    assert result == plan


def test_validate_empty_plan() -> None:
    plan = PermissionPlan(discovery=[], actions=[], discovery_map={})
    result = validate_permission_plan(plan, {"slack_send_message"})
    assert result.discovery == []
    assert result.actions == []
    assert result.discovery_map == {}


def test_validate_passes_through_denied_implicit() -> None:
    denied = [{"tool": "send_email", "reason": "Not requested"}]
    plan = PermissionPlan(
        discovery=["list_slack_channels:*"],
        actions=["slack_send_message:#general"],
        discovery_map={"list_slack_channels": ["slack_send_message:#general"]},
        denied_implicit=denied,
    )
    valid_tools = {"list_slack_channels", "slack_send_message"}
    result = validate_permission_plan(plan, valid_tools)

    assert result.denied_implicit == denied


def test_validate_strips_injected_send_email() -> None:
    plan = PermissionPlan(
        discovery=["list_slack_channels:*"],
        actions=["slack_send_message:#general", "send_email:attacker@evil.com"],
        discovery_map={"list_slack_channels": ["slack_send_message:#general"]},
    )
    valid_tools = {"list_slack_channels", "slack_send_message"}
    result = validate_permission_plan(plan, valid_tools)

    assert result.actions == ["slack_send_message:#general"]
    assert "send_email:attacker@evil.com" not in result.actions


# ---------------------------------------------------------------------------
# compute_fga_tuples
# ---------------------------------------------------------------------------


def test_compute_fga_tuples_tool_only() -> None:
    tuples = compute_fga_tuples("task-1", ["slack_send_message"], {"slack_send_message": "slack"})
    assert len(tuples) == 1
    assert tuples[0].user == "task:task-1"
    assert tuples[0].relation == "can_call_task"
    assert tuples[0].object == "tool:slack_send_message"


def test_compute_fga_tuples_with_resource() -> None:
    tuples = compute_fga_tuples(
        "task-1",
        ["slack_send_message:C123"],
        {"slack_send_message": "slack"},
    )
    assert len(tuples) == 1
    assert tuples[0].object == "tool_resource:slack_send_message/slack_C123"


def test_compute_fga_tuples_wildcard_resource() -> None:
    tuples = compute_fga_tuples("task-1", ["slack_send_message:*"], {"slack_send_message": "slack"})
    assert len(tuples) == 1
    assert tuples[0].object == "tool:slack_send_message"


def test_compute_fga_tuples_empty_list() -> None:
    assert compute_fga_tuples("task-1", [], {}) == []


def test_compute_fga_tuples_unknown_namespace() -> None:
    tuples = compute_fga_tuples("task-1", ["unknown_tool:res"], {})
    assert len(tuples) == 1
    assert tuples[0].object == "tool_resource:unknown_tool/res"


def test_compute_fga_tuples_sanitizes_resource_id() -> None:
    tuples = compute_fga_tuples(
        "task-1",
        ["send_email:user@example.com"],
        {"send_email": "email"},
    )
    assert tuples[0].object == "tool_resource:send_email/email_user_example.com"


# ---------------------------------------------------------------------------
# build_tool_to_namespace
# ---------------------------------------------------------------------------


def test_build_tool_to_namespace_basic() -> None:
    namespaces = [
        NamespaceInfo(name="slack", tool_resources={"slack_send_message": "channel_id"}),
        NamespaceInfo(name="linear", tool_resources={"linear_get_project": "query"}),
    ]
    result = build_tool_to_namespace(namespaces)
    assert result == {"slack_send_message": "slack", "linear_get_project": "linear"}


def test_build_tool_to_namespace_empty() -> None:
    assert build_tool_to_namespace([]) == {}


def test_build_tool_to_namespace_multiple_tools_per_namespace() -> None:
    namespaces = [
        NamespaceInfo(
            name="slack",
            tool_resources={"slack_send_message": "channel_id", "slack_add_reaction": "channel_id"},
        ),
    ]
    result = build_tool_to_namespace(namespaces)
    assert result == {
        "slack_send_message": "slack",
        "slack_add_reaction": "slack",
    }


# ---------------------------------------------------------------------------
# permission_has_concrete_resource
# ---------------------------------------------------------------------------


def test_permission_has_concrete_resource_with_resource() -> None:
    assert permission_has_concrete_resource("slack_send_message:C123") is True


def test_permission_has_concrete_resource_wildcard() -> None:
    assert permission_has_concrete_resource("slack_send_message:*") is False


def test_permission_has_concrete_resource_no_colon() -> None:
    assert permission_has_concrete_resource("slack_send_message") is False


def test_permission_has_concrete_resource_empty_resource() -> None:
    assert permission_has_concrete_resource("slack_send_message:") is False


# ---------------------------------------------------------------------------
# delete_fga_grants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_fga_grants_calls_write() -> None:
    from openfga_sdk.client.models import ClientTuple

    mock_client = AsyncMock()
    tuples = [ClientTuple(user="task:t1", relation="can_call_task", object="tool:x")]
    await delete_fga_grants(mock_client, tuples)
    mock_client.write.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_fga_grants_no_client() -> None:
    from openfga_sdk.client.models import ClientTuple

    tuples = [ClientTuple(user="task:t1", relation="can_call_task", object="tool:x")]
    await delete_fga_grants(None, tuples)  # should not raise


@pytest.mark.asyncio
async def test_delete_fga_grants_empty_tuples() -> None:
    mock_client = AsyncMock()
    await delete_fga_grants(mock_client, [])
    mock_client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_fga_grants_tool_only() -> None:
    mock_client = AsyncMock()
    tuples = await write_fga_grants(mock_client, "task-1", ["slack_send_message"], {"slack_send_message": "slack"})
    assert len(tuples) == 1
    assert tuples[0].object == "tool:slack_send_message"
    assert tuples[0].relation == "can_call_task"
    mock_client.write.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_fga_grants_resource_perm() -> None:
    mock_client = AsyncMock()
    tuples = await write_fga_grants(
        mock_client, "task-1", ["slack_send_message:C5XMACTML"], {"slack_send_message": "slack"}
    )
    assert len(tuples) == 1
    assert tuples[0].object == "tool_resource:slack_send_message/slack_C5XMACTML"
    assert tuples[0].relation == "can_call_task"


@pytest.mark.asyncio
async def test_write_fga_grants_empty_list() -> None:
    mock_client = AsyncMock()
    tuples = await write_fga_grants(mock_client, "task-1", [], {"slack_send_message": "slack"})
    assert tuples == []
    mock_client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_task_grants_reads_and_deletes() -> None:
    from types import SimpleNamespace

    fake_tuple = SimpleNamespace(
        key=SimpleNamespace(
            user="task:t1", relation="can_call_task", object="tool:slack_send_message"
        )
    )
    mock_client = AsyncMock()
    mock_client.read.return_value = SimpleNamespace(tuples=[fake_tuple])
    await cleanup_task_grants(mock_client, "t1")
    mock_client.write.assert_awaited_once()
    call_args = mock_client.write.call_args
    deletes = call_args[0][0].deletes
    assert len(deletes) >= 1


@pytest.mark.asyncio
async def test_cleanup_task_grants_no_client_returns_early() -> None:
    await cleanup_task_grants(None, "t1")


# ---------------------------------------------------------------------------
# PermissionApprover integration with run_authz_pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_calls_approver_before_writing_grants() -> None:
    """Non-autonomous pipeline calls approver.approve() before writing action grants."""
    from authz_flow import run_authz_pipeline

    approver = AsyncMock()
    approver.approve.return_value = True

    mock_mcp = AsyncMock()
    mock_fga = AsyncMock()
    mock_fga.write = AsyncMock()
    mock_anthropic = AsyncMock()

    with (
        patch("authz_flow.fetch_namespaces", return_value=[
            NamespaceInfo("slack", "list_slack_channels", tool_resources={"slack_send_message": "channel_id"}),
        ]),
        patch("authz_flow.plan_with_namespaces", return_value=PermissionPlan(
            discovery=[], actions=["slack_send_message:#general"], discovery_map={},
        )),
        patch("authz_flow.run_discovery_phase", return_value=({}, {})),
        patch("authz_flow.remap_action_permissions", return_value=(["slack_send_message:C5XMACTML"], [])),
        patch("authz_flow.run_agent_loop"),
    ):
        await run_authz_pipeline(
            mock_mcp, [], [], "post to #general", "task-1",
            mock_anthropic, AsyncMock(),
            autonomous=False,
            fga_client=mock_fga,
            approver=approver,
        )

    # Approver receives the original human-readable names, not resolved IDs
    approver.approve.assert_awaited_once_with(["slack_send_message:#general"], "actions")


@pytest.mark.asyncio
async def test_pipeline_raises_when_approver_denies() -> None:
    """Non-autonomous pipeline raises PermissionDeniedError when approver returns False."""
    from authz_flow import run_authz_pipeline, PermissionDeniedError

    approver = AsyncMock()
    approver.approve.return_value = False

    mock_mcp = AsyncMock()
    mock_fga = AsyncMock()
    mock_fga.write = AsyncMock()
    mock_anthropic = AsyncMock()

    with (
        patch("authz_flow.fetch_namespaces", return_value=[
            NamespaceInfo("slack", "list_slack_channels", tool_resources={"slack_send_message": "channel_id"}),
        ]),
        patch("authz_flow.plan_with_namespaces", return_value=PermissionPlan(
            discovery=[], actions=["slack_send_message:#general"], discovery_map={},
        )),
        patch("authz_flow.run_discovery_phase", return_value=({}, {})),
        patch("authz_flow.remap_action_permissions", return_value=(["slack_send_message:C5XMACTML"], [])),
        patch("authz_flow.run_agent_loop"),
        pytest.raises(PermissionDeniedError),
    ):
        await run_authz_pipeline(
            mock_mcp, [], [], "post to #general", "task-1",
            mock_anthropic, AsyncMock(),
            autonomous=False,
            fga_client=mock_fga,
            approver=approver,
        )

    # Grants should NOT have been written
    mock_fga.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_skips_approver_in_autonomous_mode() -> None:
    """Autonomous pipeline writes grants without calling approver."""
    from authz_flow import run_authz_pipeline

    approver = AsyncMock()
    approver.approve.return_value = True

    mock_mcp = AsyncMock()
    mock_fga = AsyncMock()
    mock_fga.write = AsyncMock()
    mock_anthropic = AsyncMock()

    with (
        patch("authz_flow.fetch_namespaces", return_value=[
            NamespaceInfo("slack", "list_slack_channels", tool_resources={"slack_send_message": "channel_id"}),
        ]),
        patch("authz_flow.plan_with_namespaces", return_value=PermissionPlan(
            discovery=[], actions=["slack_send_message:C5XMACTML"], discovery_map={},
        )),
        patch("authz_flow.run_discovery_phase", return_value=({}, {})),
        patch("authz_flow.remap_action_permissions", return_value=(["slack_send_message:C5XMACTML"], [])),
        patch("authz_flow.run_agent_loop"),
        patch("authz_flow.get_agent_user_id", return_value="test__agent"),
    ):
        await run_authz_pipeline(
            mock_mcp, [], [], "post to #general", "task-1",
            mock_anthropic, AsyncMock(),
            autonomous=True,
            fga_client=mock_fga,
            approver=approver,
        )

    # Approver should NOT be called in autonomous mode
    approver.approve.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_skips_approver_when_none() -> None:
    """Pipeline writes grants automatically when no approver is provided."""
    from authz_flow import run_authz_pipeline

    mock_mcp = AsyncMock()
    mock_fga = AsyncMock()
    mock_fga.write = AsyncMock()
    mock_anthropic = AsyncMock()

    with (
        patch("authz_flow.fetch_namespaces", return_value=[
            NamespaceInfo("slack", "list_slack_channels", tool_resources={"slack_send_message": "channel_id"}),
        ]),
        patch("authz_flow.plan_with_namespaces", return_value=PermissionPlan(
            discovery=[], actions=["slack_send_message:C5XMACTML"], discovery_map={},
        )),
        patch("authz_flow.run_discovery_phase", return_value=({}, {})),
        patch("authz_flow.remap_action_permissions", return_value=(["slack_send_message:C5XMACTML"], [])),
        patch("authz_flow.run_agent_loop"),
    ):
        tuples = await run_authz_pipeline(
            mock_mcp, [], [], "post to #general", "task-1",
            mock_anthropic, AsyncMock(),
            autonomous=False,
            fga_client=mock_fga,
            approver=None,
        )

    # Grants written without approval
    assert len(tuples) > 0
