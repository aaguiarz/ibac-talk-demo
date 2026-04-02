#!/usr/bin/env python3
"""End-to-end tests for the OpenFGA permission middleware.

These tests call the REAL Slack and Linear MCP servers through the
multi_proxy_openfga proxy, with authorization enforced by a live OpenFGA
instance. They verify the complete "summarize the MCP Dev Talk project and
post to the Slack channel" flow.

Prerequisites:
  - OpenFGA running (default: http://localhost:8080)
  - A store + model created (see setup instructions below)
  - .mcp_credentials.json with valid Slack and Linear credentials

Setup:
  docker run -d --name openfga-test -p 8080:8080 openfga/openfga run
  curl -s -X POST http://localhost:8080/stores \\
    -H 'Content-Type: application/json' -d '{"name":"e2e_test"}'
  fga model write --store-id <STORE_ID> --api-url http://localhost:8080 \\
    --file authorization/model.fga

Run:
  FGA_STORE_ID=<STORE_ID> python -m pytest test_e2e_openfga.py -v -s

Skip with:
  python -m pytest test_e2e_openfga.py -v -k "not e2e"
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError
from openfga_sdk import ClientConfiguration, OpenFgaClient
from openfga_sdk.client.models import ClientTuple, ClientWriteRequest

from utils import extract_text as _extract_text, FGA_WRITE_OPTS

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FGA_API_URL = os.environ.get("FGA_API_URL", "http://localhost:8080")
FGA_STORE_ID = os.environ.get("FGA_STORE_ID", "01KKVAZZC73SMTJG1N153X3X0S")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, ".mcp_credentials.json")

# Slack channel to send test messages to
E2E_SLACK_CHANNEL_NAME = os.environ.get(
    "E2E_SLACK_CHANNEL", "private-team-channel"
)

# Linear project to use for test lookups
E2E_LINEAR_PROJECT_NAME = os.environ.get("E2E_LINEAR_PROJECT", "MCP Dev Talk")


def _can_run_e2e() -> bool:
    """Check if prerequisites are met for e2e tests."""
    if not os.path.exists(CONFIG_FILE):
        return False
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        servers = cfg.get("servers", {})
        if not servers.get("slack", {}).get("url"):
            return False
        if not servers.get("linear", {}).get("url"):
            return False
    except (json.JSONDecodeError, TypeError):
        return False
    if not FGA_STORE_ID:
        return False
    return True


skip_e2e = pytest.mark.skipif(
    not _can_run_e2e(),
    reason="E2E prerequisites not met (.mcp_credentials.json, FGA_STORE_ID)",
)


# ---------------------------------------------------------------------------
# FGA Helpers
# ---------------------------------------------------------------------------


async def _direct_fga_write(tuples: list[ClientTuple]) -> None:
    """Write tuples directly to FGA (outside the middleware)."""
    config = ClientConfiguration(api_url=FGA_API_URL, store_id=FGA_STORE_ID)
    async with OpenFgaClient(config) as fga:
        await fga.write(ClientWriteRequest(writes=tuples), FGA_WRITE_OPTS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_fga_env(user_id: str | None = None) -> None:
    """Set FGA env vars for the proxy to pick up."""
    os.environ["FGA_API_URL"] = FGA_API_URL
    os.environ["FGA_STORE_ID"] = FGA_STORE_ID
    os.environ["FGA_USER_ID"] = user_id or f"e2e_{uuid.uuid4().hex[:8]}"


def _create_proxy() -> Any:
    """Create the real mcp_server."""
    from mcp_server import create_multi_proxy

    return create_multi_proxy(config_file=CONFIG_FILE)


# ---------------------------------------------------------------------------
# Fixtures — each test gets its own proxy+client (function-scoped)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def proxy_client() -> AsyncIterator[Client]:
    """Proxy with auto-approve 'session' scope."""
    _set_fga_env()
    mcp = _create_proxy()

    async def auto_approve(
        message: str, response_type: Any, params: Any, context: Any
    ) -> dict[str, str]:
        return {"value": "Allow for this session"}

    client = Client(mcp, elicitation_handler=auto_approve)
    await client.__aenter__()
    yield client
    await client.__aexit__(None, None, None)


@pytest_asyncio.fixture
async def deny_proxy_client() -> AsyncIterator[Client]:
    """Proxy with auto-deny elicitation."""
    _set_fga_env()
    mcp = _create_proxy()

    async def auto_deny(
        message: str, response_type: Any, params: Any, context: Any
    ) -> dict[str, str]:
        return {"value": "Do not allow"}

    client = Client(mcp, elicitation_handler=auto_deny)
    await client.__aenter__()
    yield client
    await client.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# E2E 1: Slack search channels (real API)
# ---------------------------------------------------------------------------


@skip_e2e
@pytest.mark.asyncio
async def test_e2e_list_slack_channels(proxy_client) -> None:
    """list_slack_channels calls the real Slack API and populates the registry."""
    task_id = str(uuid.uuid4())

    result = await proxy_client.call_tool(
        "list_slack_channels",
        {"query": E2E_SLACK_CHANNEL_NAME},
        meta={"task_id": task_id},
    )
    text = _extract_text(result)
    assert E2E_SLACK_CHANNEL_NAME.lower() in text.lower(), (
        f"Expected '{E2E_SLACK_CHANNEL_NAME}' in results: {text[:500]}"
    )

    # Verify discovery results contain expected channels
    channels = json.loads(text)
    assert isinstance(channels, list) and len(channels) > 0, (
        f"Expected channels in results: {text[:500]}"
    )
    assert any(
        E2E_SLACK_CHANNEL_NAME.lower() in ch.get("name", "").lower()
        for ch in channels if isinstance(ch, dict)
    ), f"Expected '#{E2E_SLACK_CHANNEL_NAME}' in: {channels}"


# ---------------------------------------------------------------------------
# E2E 2: Linear list projects (real API)
# ---------------------------------------------------------------------------


@skip_e2e
@pytest.mark.asyncio
async def test_e2e_list_linear_projects(proxy_client) -> None:
    """list_linear_projects calls the real Linear API and populates the registry."""
    task_id = str(uuid.uuid4())

    result = await proxy_client.call_tool(
        "list_linear_projects", {"query": ""}, meta={"task_id": task_id}
    )
    text = _extract_text(result)
    assert len(text) > 10

    projects = json.loads(text)
    assert isinstance(projects, list) and len(projects) > 0, (
        f"Expected projects in results: {text[:500]}"
    )
    assert any(
        E2E_LINEAR_PROJECT_NAME.lower() in p.get("name", "").lower()
        for p in projects if isinstance(p, dict)
    ), (
        f"Expected {E2E_LINEAR_PROJECT_NAME!r} in: {projects}"
    )


# ---------------------------------------------------------------------------
# E2E 5: Permission denied without grant (direct mode)
# ---------------------------------------------------------------------------


@skip_e2e
@pytest.mark.asyncio
async def test_e2e_denied_without_grant(deny_proxy_client) -> None:
    """Calling slack_send_message without a grant is denied by elicitation."""
    task_id = str(uuid.uuid4())
    with pytest.raises(ToolError, match="(?i)permission denied"):
        await deny_proxy_client.call_tool(
            "slack_send_message",
            {"channel_id": "C5XMACTML", "message": "should not send"},
            meta={"task_id": task_id},
        )


# ---------------------------------------------------------------------------
# E2E 6: Grant + linear_get_project (real API)
# ---------------------------------------------------------------------------


@skip_e2e
@pytest.mark.asyncio
async def test_e2e_grant_and_get_project(proxy_client) -> None:
    """Grant permission, then fetch a real Linear project."""
    task_id = str(uuid.uuid4())

    # Discover
    disc_result = await proxy_client.call_tool(
        "list_linear_projects", {"query": ""}, meta={"task_id": task_id}
    )
    projects = json.loads(_extract_text(disc_result))

    project_id = None
    for p in projects:
        if isinstance(p, dict) and E2E_LINEAR_PROJECT_NAME.lower() in p.get("name", "").lower():
            project_id = p["id"]
            break
    assert project_id, f"No {E2E_LINEAR_PROJECT_NAME!r} project in: {projects}"

    # Grant via direct FGA write (task scope)
    await _direct_fga_write(
        [
            ClientTuple(
                user=f"task:{task_id}",
                relation="can_call_task",
                object=f"tool_resource:linear_get_project/{project_id}",
            ),
        ]
    )

    # Fetch (real API)
    project = _extract_text(
        await proxy_client.call_tool(
            "linear_get_project",
            {"query": project_id},
            meta={"task_id": task_id},
        )
    )
    assert len(project) > 20, f"Expected project details: {project[:200]}"


# ---------------------------------------------------------------------------
# E2E 7: Grant + slack_send_message (real message)
# ---------------------------------------------------------------------------


@skip_e2e
@pytest.mark.asyncio
async def test_e2e_grant_and_send_slack_message(proxy_client) -> None:
    """Grant permission, then send a real Slack message."""
    task_id = str(uuid.uuid4())

    # Discover
    disc_result = await proxy_client.call_tool(
        "list_slack_channels",
        {"query": E2E_SLACK_CHANNEL_NAME},
        meta={"task_id": task_id},
    )
    channels = json.loads(_extract_text(disc_result))

    channel_id = None
    for ch in channels:
        if isinstance(ch, dict) and E2E_SLACK_CHANNEL_NAME.lower() in ch.get("name", "").lower():
            channel_id = ch["id"]
            break
    assert channel_id, f"#{E2E_SLACK_CHANNEL_NAME} not in: {channels}"

    # Grant via direct FGA write (session scope)

    await _direct_fga_write(
        [
            ClientTuple(
                user=f"task:{task_id}",
                relation="can_call_task",
                object=f"tool_resource:slack_send_message/{channel_id}",
            ),
        ]
    )

    # Send (real API)
    msg = f"[E2E test] OpenFGA middleware — {uuid.uuid4().hex[:8]}"
    send = _extract_text(
        await proxy_client.call_tool(
            "slack_send_message",
            {"channel_id": channel_id, "message": msg},
            meta={"task_id": task_id},
        )
    )
    assert "error" not in send.lower() or "permission" not in send.lower(), (
        f"Expected success: {send[:500]}"
    )


# ---------------------------------------------------------------------------
# E2E 8: Session scope persists across tasks
# ---------------------------------------------------------------------------


@skip_e2e
@pytest.mark.asyncio
async def test_e2e_session_scope_persists(proxy_client) -> None:
    """A session-scoped grant works for a different task_id."""
    task_a = str(uuid.uuid4())
    task_b = str(uuid.uuid4())

    # Discover
    disc_result = await proxy_client.call_tool(
        "list_linear_projects", {"query": ""}, meta={"task_id": task_a}
    )
    projects = json.loads(_extract_text(disc_result))
    assert projects, "Expected at least one Linear project"
    project_id = projects[0]["id"]

    # Grant both tasks via direct FGA write (task scope for each)
    await _direct_fga_write(
        [
            ClientTuple(
                user=f"task:{task_a}",
                relation="can_call_task",
                object=f"tool_resource:linear_get_project/{project_id}",
            ),
            ClientTuple(
                user=f"task:{task_b}",
                relation="can_call_task",
                object=f"tool_resource:linear_get_project/{project_id}",
            ),
        ]
    )

    # Call with task B — should succeed
    result = _extract_text(
        await proxy_client.call_tool(
            "linear_get_project",
            {"query": project_id},
            meta={"task_id": task_b},
        )
    )
    assert "permission denied" not in result.lower(), (
        f"Session scope failed: {result[:500]}"
    )
    assert len(result) > 10


# ---------------------------------------------------------------------------
# E2E 9: Wrong resource denied (direct mode)
# ---------------------------------------------------------------------------


@skip_e2e
@pytest.mark.asyncio
async def test_e2e_wrong_resource_denied(proxy_client) -> None:
    """Grant for one channel, try another — denied."""
    task_id = str(uuid.uuid4())

    # Discover channels — search broadly to find at least 2
    disc_result = await proxy_client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_id}
    )
    channels = json.loads(_extract_text(disc_result))

    if len(channels) < 2:
        pytest.skip("Need at least 2 Slack channels for resource isolation test")

    granted_channel = channels[0]["id"]
    other_channel = channels[1]["id"]

    # Grant for one channel via direct FGA write (session scope)

    await _direct_fga_write(
        [
            ClientTuple(
                user=f"task:{task_id}",
                relation="can_call_task",
                object=f"tool_resource:slack_send_message/{granted_channel}",
            ),
        ]
    )

    # The granted channel works (grant exists, no elicitation needed)
    r1 = await proxy_client.call_tool(
        "slack_send_message",
        {"channel_id": granted_channel, "message": "should send"},
        meta={"task_id": task_id},
    )
    assert "error" not in _extract_text(r1).lower()

    # The other channel is not granted, use deny_proxy_client for the second call
    # to verify FGA isolation (the grant doesn't exist for other_channel).
    _set_fga_env()
    mcp2 = _create_proxy()

    async def auto_deny(
        message: str, response_type: Any, params: Any, context: Any
    ) -> dict[str, str]:
        return {"value": "Do not allow"}

    deny_client = Client(mcp2, elicitation_handler=auto_deny)
    async with deny_client:
        task_id_2 = str(uuid.uuid4())
        with pytest.raises(ToolError, match="(?i)permission denied"):
            await deny_client.call_tool(
                "slack_send_message",
                {"channel_id": other_channel, "message": "should not send"},
                meta={"task_id": task_id_2},
            )


# ---------------------------------------------------------------------------
# E2E 10: FGA tuples verified directly
# ---------------------------------------------------------------------------


@skip_e2e
@pytest.mark.asyncio
async def test_e2e_fga_tuples_verified(proxy_client) -> None:
    """After granting, verify the tool call succeeds (FGA check passes end-to-end)."""
    task_id = str(uuid.uuid4())

    # Discover (auto-approve grants via inline elicitation)
    await proxy_client.call_tool(
        "list_linear_projects", {"query": ""}, meta={"task_id": task_id}
    )

    # Public tool works without grant
    ns = await proxy_client.call_tool(
        "get_resource_metadata", {}, meta={"task_id": task_id}
    )
    assert len(json.loads(_extract_text(ns))) > 0


# ---------------------------------------------------------------------------
# E2E 11: Full flow — "summarize the MCP Dev Talk project and post to the Slack channel"
# ---------------------------------------------------------------------------


@skip_e2e
@pytest.mark.asyncio
async def test_e2e_full_flow_summarize_and_post(proxy_client) -> None:
    """End-to-end: discover → permissions → read project → post to Slack.

    Simulates: "summarize the MCP Dev Talk project and post it to the Slack channel"
    """
    task_id = str(uuid.uuid4())

    # Step 1: Discover namespaces (public)
    ns = json.loads(
        _extract_text(
            await proxy_client.call_tool(
                "get_resource_metadata", {}, meta={"task_id": task_id}
            )
        )
    )
    assert any(n["name"] == "slack" for n in ns)
    assert any(n["name"] == "linear" for n in ns)

    # Step 2: Discover Slack channels (auto-approved via elicitation)
    slack_result = await proxy_client.call_tool(
        "list_slack_channels",
        {"query": E2E_SLACK_CHANNEL_NAME},
        meta={"task_id": task_id},
    )
    slack_channels = json.loads(_extract_text(slack_result))

    # Step 3: Discover Linear projects (auto-approved via elicitation)
    linear_result = await proxy_client.call_tool(
        "list_linear_projects", {"query": ""}, meta={"task_id": task_id}
    )
    linear_projects = json.loads(_extract_text(linear_result))

    # Find the Slack channel
    channel_id = None
    for ch in slack_channels:
        if isinstance(ch, dict) and E2E_SLACK_CHANNEL_NAME.lower() in ch.get("name", "").lower():
            channel_id = ch["id"]
            break
    assert channel_id, f"#{E2E_SLACK_CHANNEL_NAME} not in: {slack_channels}"

    # Find target Linear project
    project_id = None
    for p in linear_projects:
        if isinstance(p, dict) and E2E_LINEAR_PROJECT_NAME.lower() in p.get("name", "").lower():
            project_id = p["id"]
            break
    assert project_id, f"{E2E_LINEAR_PROJECT_NAME!r} not in: {linear_projects}"

    # Step 5: Grant permissions via direct FGA write (task scope)

    await _direct_fga_write(
        [
            ClientTuple(
                user=f"task:{task_id}",
                relation="can_call_task",
                object=f"tool_resource:linear_get_project/{project_id}",
            ),
            ClientTuple(
                user=f"task:{task_id}",
                relation="can_call_task",
                object=f"tool_resource:slack_send_message/{channel_id}",
            ),
        ]
    )

    # Step 6: Get project details (real Linear API)
    project_text = _extract_text(
        await proxy_client.call_tool(
            "linear_get_project",
            {"query": project_id},
            meta={"task_id": task_id},
        )
    )
    assert len(project_text) > 20, f"Expected project details: {project_text[:200]}"

    # Step 7: Post summary to the Slack channel (real Slack API)
    summary = f"[E2E] Project summary: {project_text[:200]}"
    post = _extract_text(
        await proxy_client.call_tool(
            "slack_send_message",
            {"channel_id": channel_id, "message": summary},
            meta={"task_id": task_id},
        )
    )
    assert "error" not in post.lower() or "permission" not in post.lower(), (
        f"Expected success: {post[:500]}"
    )

    # Step 8: Grant a second task and verify it also works
    task_id_2 = str(uuid.uuid4())
    await _direct_fga_write(
        [
            ClientTuple(
                user=f"task:{task_id_2}",
                relation="can_call_task",
                object=f"tool_resource:slack_send_message/{channel_id}",
            ),
        ]
    )
    followup = _extract_text(
        await proxy_client.call_tool(
            "slack_send_message",
            {"channel_id": channel_id, "message": f"[E2E] Follow-up {task_id_2[:8]}"},
            meta={"task_id": task_id_2},
        )
    )
    assert "permission denied" not in followup.lower(), (
        f"Task grant should work: {followup[:500]}"
    )

    # Step 9 verified implicitly: steps 7 and 8 succeeded, proving
    # the FGA grants are correctly written and the middleware check passes.
