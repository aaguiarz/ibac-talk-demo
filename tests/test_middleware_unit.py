"""Unit tests for OpenFGAPermissionMiddleware internals."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openfga_sdk.client.models import ClientTuple

from task_authz.config import ResourceType
from task_authz.middleware import OpenFGAPermissionMiddleware


# ---------------------------------------------------------------------------
# _build_fga_object
# ---------------------------------------------------------------------------


def test_build_fga_object_tool_resource() -> None:
    mw = OpenFGAPermissionMiddleware(
        resource_types=[ResourceType("slack", tool_resources={"slack_send_message": "channel_id"})],
    )
    result = mw._build_fga_object("slack_send_message", {"channel_id": "C123"})
    assert result == "tool_resource:slack_send_message/slack_C123"


def test_build_fga_object_tool_level_when_no_arg() -> None:
    mw = OpenFGAPermissionMiddleware(
        resource_types=[ResourceType("slack", tool_resources={"slack_send_message": "channel_id"})],
    )
    result = mw._build_fga_object("slack_send_message", {})
    assert result == "tool:slack_send_message"


def test_build_fga_object_configured_tool() -> None:
    mw = OpenFGAPermissionMiddleware(tool_config={"my_tool": None})
    result = mw._build_fga_object("my_tool", {})
    assert result == "tool:my_tool"


def test_build_fga_object_unconfigured_returns_none() -> None:
    mw = OpenFGAPermissionMiddleware()
    assert mw._build_fga_object("unknown", {}) is None


def test_send_email_uses_to_as_resource_identifier() -> None:
    mw = OpenFGAPermissionMiddleware(
        resource_types=[ResourceType("email", tool_resources={"send_email": "to"})],
    )
    result = mw._build_fga_object(
        "send_email",
        {"to": "alex@example.com", "subject": "Hi", "text": "Hello"},
    )
    assert result == "tool_resource:send_email/email_alex_example.com"


# ---------------------------------------------------------------------------
# _contextual_parent_tool
# ---------------------------------------------------------------------------


def test_contextual_parent_tool_for_tool_resource() -> None:
    mw = OpenFGAPermissionMiddleware()
    result = mw._contextual_parent_tool("slack_send_message", "tool_resource:slack_send_message/slack_C123")
    assert result is not None
    assert len(result) == 1
    assert result[0].user == "tool:slack_send_message"
    assert result[0].relation == "parent_tool"


def test_contextual_parent_tool_for_tool_returns_none() -> None:
    mw = OpenFGAPermissionMiddleware()
    assert mw._contextual_parent_tool("slack_send_message", "tool:slack_send_message") is None


# ---------------------------------------------------------------------------
# _build_grant_tuples
# ---------------------------------------------------------------------------


def test_build_grant_tuples_once() -> None:
    mw = OpenFGAPermissionMiddleware()
    tuples = mw._build_grant_tuples("once", "t1", "s1", "au1", "tool:x", "x")
    assert len(tuples) == 1
    assert tuples[0].relation == "can_call_task"
    assert tuples[0].user == "task:t1"


def test_build_grant_tuples_session() -> None:
    mw = OpenFGAPermissionMiddleware()
    tuples = mw._build_grant_tuples("session", "t1", "s1", "au1", "tool:x", "x")
    assert len(tuples) == 1
    assert tuples[0].relation == "can_call_session"
    assert tuples[0].user == "session:s1#task"


def test_build_grant_tuples_always() -> None:
    mw = OpenFGAPermissionMiddleware()
    tuples = mw._build_grant_tuples("always", "t1", "s1", "au1", "tool:x", "x")
    assert len(tuples) == 1
    assert tuples[0].relation == "can_call_agent_user"
    assert tuples[0].user == "agent_user:au1#task"


def test_build_grant_tuples_invalid_scope() -> None:
    mw = OpenFGAPermissionMiddleware()
    tuples = mw._build_grant_tuples("invalid", "t1", "s1", "au1", "tool:x", "x")
    assert tuples == []


# ---------------------------------------------------------------------------
# clear_task_resources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_task_resources_removes_task() -> None:
    mw = OpenFGAPermissionMiddleware()
    async with mw._state_lock:
        mw._known_tasks.add("task-1")
    await mw.clear_task_resources("task-1")
    assert "task-1" not in mw._known_tasks


@pytest.mark.asyncio
async def test_clear_task_resources_noop_for_unknown_task() -> None:
    mw = OpenFGAPermissionMiddleware()
    await mw.clear_task_resources("nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# State lock exists and is usable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_lock_is_asyncio_lock() -> None:
    mw = OpenFGAPermissionMiddleware()
    assert isinstance(mw._state_lock, asyncio.Lock)
    async with mw._state_lock:
        pass  # Should not deadlock


# ---------------------------------------------------------------------------
# agent_user_in_context: contextual tuple validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_includes_agent_user_in_context_for_tool() -> None:
    """_check is called with agent_user_in_context contextual tuple for tool objects."""
    mw = OpenFGAPermissionMiddleware(
        tool_config={"my_tool": None},
    )
    # Mock the FGA client so _check captures the call args
    mock_fga = AsyncMock()
    mock_fga.check = AsyncMock(return_value=MagicMock(allowed=True))
    mw._fga = mock_fga

    await mw._check(
        "task:t1",
        "can_call",
        "tool:my_tool",
        contextual_tuples=[
            ClientTuple(
                user="agent_user:alice__mcp",
                relation="agent_user_in_context",
                object="tool:my_tool",
            ),
        ],
    )

    # Verify _check passed the contextual tuple to the FGA client
    mock_fga.check.assert_called_once()
    request = mock_fga.check.call_args[0][0]
    assert request.contextual_tuples is not None
    ctx_tuple = request.contextual_tuples[0]
    assert ctx_tuple.user == "agent_user:alice__mcp"
    assert ctx_tuple.relation == "agent_user_in_context"
    assert ctx_tuple.object == "tool:my_tool"


@pytest.mark.asyncio
async def test_batch_check_includes_agent_user_in_context() -> None:
    """_batch_check includes agent_user_in_context for each check item."""
    mw = OpenFGAPermissionMiddleware()
    mock_fga = AsyncMock()
    mock_result = MagicMock()
    mock_result.result = [
        MagicMock(correlation_id="0", allowed=True, error=None),
        MagicMock(correlation_id="1", allowed=True, error=None),
    ]
    mock_fga.batch_check = AsyncMock(return_value=mock_result)
    mw._fga = mock_fga

    await mw._batch_check(
        [
            ("task:t1", "can_call", "tool:read_item"),
            ("task:t1", "can_call", "tool_resource:send_message/slack_C123"),
        ],
        agent_user_id="alice__mcp",
    )

    mock_fga.batch_check.assert_called_once()
    request = mock_fga.batch_check.call_args[0][0]
    items = request.checks

    # First item: tool — should have agent_user_in_context only
    tool_ctx = items[0].contextual_tuples
    assert any(
        t.relation == "agent_user_in_context"
        and t.user == "agent_user:alice__mcp"
        and t.object == "tool:read_item"
        for t in tool_ctx
    )

    # Second item: tool_resource — should have both parent_tool AND agent_user_in_context
    tr_ctx = items[1].contextual_tuples
    assert any(
        t.relation == "parent_tool" and t.user == "tool:send_message" for t in tr_ctx
    )
    assert any(
        t.relation == "agent_user_in_context"
        and t.user == "agent_user:alice__mcp"
        and t.object == "tool_resource:send_message/slack_C123"
        for t in tr_ctx
    )


@pytest.mark.asyncio
async def test_batch_check_raises_without_agent_user_id() -> None:
    """_batch_check raises ValueError when agent_user_id is empty."""
    mw = OpenFGAPermissionMiddleware()
    mw._fga = AsyncMock()

    with pytest.raises(ValueError, match="agent_user_id is required"):
        await mw._batch_check(
            [("task:t1", "can_call", "tool:x")],
            agent_user_id="",
        )


@pytest.mark.asyncio
async def test_on_call_tool_passes_agent_user_in_context() -> None:
    """on_call_tool passes agent_user_in_context contextual tuple to _check."""
    mw = OpenFGAPermissionMiddleware(
        tool_config={"my_tool": None},
    )
    # Patch _check to capture the contextual_tuples argument
    captured_calls: list[dict] = []

    async def spy_check(
        user: str,
        relation: str,
        obj: str,
        contextual_tuples: list[ClientTuple] | None = None,
    ) -> bool:
        captured_calls.append(
            {
                "user": user,
                "relation": relation,
                "object": obj,
                "contextual_tuples": contextual_tuples,
            }
        )
        return True

    mw._check = spy_check  # type: ignore[assignment]

    # Simulate session info
    mock_ctx = MagicMock()
    mock_ctx.session = MagicMock()
    mock_ctx.session_id = "sess-1"
    mock_ctx.elicit = AsyncMock()
    mock_ctx.info = AsyncMock()
    mw._session_info[id(mock_ctx.session)] = ("alice__mcp", "sess-1", "mcp_0.1.0")
    mw._known_tasks.add("task-1")

    # Build middleware context
    mock_message = MagicMock()
    mock_message.name = "my_tool"
    mock_message.arguments = {}
    context = MagicMock()
    context.message = mock_message
    context.fastmcp_context = mock_ctx

    # Mock _get_task_id to return our task
    with patch("task_authz.middleware._get_task_id", return_value="task-1"):
        call_next = AsyncMock(return_value="result")
        await mw.on_call_tool(context, call_next)

    # Verify _check was called with agent_user_in_context
    assert len(captured_calls) == 1
    ctx_tuples = captured_calls[0]["contextual_tuples"]
    assert ctx_tuples is not None
    agent_ctx = [t for t in ctx_tuples if t.relation == "agent_user_in_context"]
    assert len(agent_ctx) == 1
    assert agent_ctx[0].user == "agent_user:alice__mcp"
    assert agent_ctx[0].object == "tool:my_tool"


@pytest.mark.asyncio
async def test_on_call_tool_raises_without_agent_user_id() -> None:
    """on_call_tool raises ToolError when agent_user_id is empty."""
    from fastmcp.exceptions import ToolError

    mw = OpenFGAPermissionMiddleware(
        tool_config={"my_tool": None},
    )

    # Simulate session info with empty agent_user_id
    mock_ctx = MagicMock()
    mock_ctx.session = MagicMock()
    mock_ctx.session_id = "sess-1"
    mw._session_info[id(mock_ctx.session)] = ("", "sess-1", "mcp_0.1.0")
    mw._known_tasks.add("task-1")

    mock_message = MagicMock()
    mock_message.name = "my_tool"
    mock_message.arguments = {}
    context = MagicMock()
    context.message = mock_message
    context.fastmcp_context = mock_ctx

    with patch("task_authz.middleware._get_task_id", return_value="task-1"):
        with pytest.raises(ToolError, match="agent_user_id is required"):
            await mw.on_call_tool(context, AsyncMock())
